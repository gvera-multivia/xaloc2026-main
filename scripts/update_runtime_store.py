import sys
from pathlib import Path

path = Path('core/pg_runtime_store.py')
content = path.read_text(encoding='utf-8')

target1 = 'def block_resource(self, *, site_id: str, resource_id: int, reason: str | None = None, source: str | None = None) -> None:'
replacement1 = 'def block_resource(self, *, site_id: str, resource_id: int, reason: str | None = None, source: str | None = None, screenshot_url: str | None = None) -> None:'

target2 = 'self.admin_store.block_resource(site_id=site_id, resource_id=resource_id, reason=reason, source=source)'
replacement2 = 'self.admin_store.block_resource(site_id=site_id, resource_id=resource_id, reason=reason, source=source, screenshot_url=screenshot_url)'

if target1 in content:
    content = content.replace(target1, replacement1)
    print("Found and replaced target1")
else:
    print("Could not find target1")

if target2 in content:
    content = content.replace(target2, replacement2)
    print("Found and replaced target2")
else:
    print("Could not find target2")

path.write_text(content, encoding='utf-8')
