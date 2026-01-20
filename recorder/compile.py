import json
import os
from pathlib import Path
from recorder.extract import get_best_selector

def compile_recording(site: str, recording_file: Path):
    print(f"Compiling recording for {site} from {recording_file}")

    events = []
    seen_timestamps = set()
    
    with open(recording_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    event = json.loads(line)
                    # Deduplicate based on timestamp (events recorded twice have same ts)
                    ts = event.get('ts')
                    if ts not in seen_timestamps:
                        seen_timestamps.add(ts)
                        events.append(event)
                except json.JSONDecodeError:
                    pass

    if not events:
        print("No events found.")
        return
    
    print(f"Loaded {len(events)} unique events (deduplicated from file)")

    # 1. Identify Phases
    phases = []
    current_phase = {"name": "start", "events": []}

    last_url = None
    last_h1 = None
    last_fingerprint = None

    for i, event in enumerate(events):
        url = event.get("url")
        h1 = event.get("h1")
        fingerprint = event.get("fingerprint")

        # Determine if new phase
        # Skip if it's the very first event
        is_new_phase = False
        if i > 0:
            if url != last_url:
                is_new_phase = True
                phase_name = "navigation"
            elif h1 != last_h1:
                is_new_phase = True
                phase_name = "screen_change"
            elif fingerprint and last_fingerprint and fingerprint != last_fingerprint:
                is_new_phase = True
                phase_name = "dom_change"

        if is_new_phase:
            phases.append(current_phase)
            current_phase = {"name": f"phase_{len(phases)}", "events": []}

        current_phase["events"].append(event)
        last_url = url
        last_h1 = h1
        last_fingerprint = fingerprint

    phases.append(current_phase)

    # 2. Generate MD
    generate_md(site, phases)

    # 3. Generate Skeleton Code
    generate_skeleton(site, phases)

def get_best_target_description(event):
    """Get the most descriptive identifier for an element."""
    field = event.get('field', {})
    locators = event.get('locators', [])
    
    # Priority: ID > name > label > text > tagName
    parts = []
    
    # Add ID if available
    if field.get('id'):
        parts.append(f"#{field['id']}")
    elif field.get('name'):
        parts.append(f"[name={field['name']}]")
    
    # Add text content from locators
    for loc in locators:
        if loc['kind'] == 'text' and loc['value']:
            parts.append(f'"{loc["value"]}"')
            break
    
    # Fallback to tagName
    if not parts:
        parts.append(field.get('tagName', 'element'))
    
    return ' '.join(parts)

def generate_md(site, phases):
    md_lines = [f"# Recording for {site}", ""]
    md_lines.append(f"**Total phases:** {len(phases)}")
    md_lines.append(f"**Total events:** {sum(len(p['events']) for p in phases)}")
    md_lines.append("")

    for phase in phases:
        md_lines.append(f"## Phase: {phase['name']}")
        first_event = phase['events'][0] if phase['events'] else {}
        md_lines.append(f"**URL:** `{first_event.get('url', 'unknown')}`")
        md_lines.append(f"**Title:** {first_event.get('title', 'unknown')}")
        md_lines.append("")
        
        md_lines.append("### Actions:")
        md_lines.append("")
        md_lines.append("| # | Action | Target | Selector | Value |")
        md_lines.append("|---|--------|--------|----------|-------|")

        for idx, event in enumerate(phase['events'], 1):
            action = event['action']
            target = get_best_target_description(event)
            
            # Get best selector for code
            selector = get_best_selector(event.get('locators', []))
            selector_short = selector[:50] + "..." if len(selector) > 50 else selector
            
            value = event.get('field', {}).get('value', '')
            value_short = value[:30] + "..." if len(str(value)) > 30 else value
            
            md_lines.append(f"| {idx} | **{action}** | `{target}` | `{selector_short}` | {value_short} |")

        md_lines.append("")

    output_path = Path(f"explore-html/{site}-recording.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    print(f"Generated {output_path}")


def generate_skeleton(site, phases):
    base_dir = Path(f"sites/{site}")
    flows_dir = base_dir / "flows"
    flows_dir.mkdir(parents=True, exist_ok=True)

    # Ensure __init__.py exists
    if not (flows_dir / "__init__.py").exists():
        with open(flows_dir / "__init__.py", "w") as f:
            f.write("")

    # Generate data_models.py
    fields = set()
    for phase in phases:
        for event in phase['events']:
            if event['action'] in ['fill', 'select', 'check', 'uncheck']:
                field_name = event.get('field', {}).get('name') or event.get('field', {}).get('id') or "unknown_field"
                if field_name:
                    # Sanitize field name
                    field_name = field_name.replace("-", "_").replace(" ", "_").replace(".", "_")
                    fields.add(field_name)

    with open(base_dir / "data_models.py", "w", encoding="utf-8") as f:
        f.write("from dataclasses import dataclass\n\n")
        f.write("@dataclass\nclass TramiteData:\n")
        if fields:
            for field in sorted(fields):
                f.write(f"    {field}: str = ''\n")
        else:
            f.write("    pass\n")
        f.write("\n")

    # Generate config.py
    start_url = phases[0]['events'][0].get('url', '') if phases and phases[0]['events'] else ''
    with open(base_dir / "config.py", "w", encoding="utf-8") as f:
        f.write(f"BASE_URL = '{start_url}'\n")
        f.write("TIMEOUT_MS = 30000\n")

    # Generate flows
    for i, phase in enumerate(phases):
        phase_name = phase['name']
        if phase_name == "start": phase_name = "initial"

        filename = f"phase_{i:02d}.py" # Simple naming

        lines = ["from playwright.async_api import Page", ""]
        lines.append(f"class Phase{i:02d}:")
        lines.append(f"    def __init__(self, page: Page):")
        lines.append(f"        self.page = page")
        lines.append("")
        lines.append("    async def execute(self, data):")

        if not phase['events']:
            lines.append("        pass")

        for event in phase['events']:
            action = event['action']
            selector = get_best_selector(event.get('locators', []))

            if action == 'click':
                lines.append(f"        await {selector}.click()")
            elif action == 'fill':
                val = event.get('field', {}).get('value', 'data.unknown')
                # Heuristic to map to data model
                field_id = event.get('field', {}).get('name') or event.get('field', {}).get('id')
                if field_id:
                     field_id = field_id.replace("-", "_").replace(" ", "_").replace(".", "_")
                     val = f"data.{field_id}"
                else:
                     val = f"'{val}'"
                lines.append(f"        await {selector}.fill({val})")
            elif action == 'select':
                 val = event.get('field', {}).get('value', '')
                 lines.append(f"        await {selector}.select_option('{val}')")
            elif action == 'check':
                 lines.append(f"        await {selector}.check()")
            elif action == 'uncheck':
                 lines.append(f"        await {selector}.uncheck()")
            elif action == 'upload':
                 lines.append(f"        # Upload detected on {selector}")

        with open(flows_dir / filename, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    print(f"Generated skeleton code in {base_dir}")
