from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.client_paths import resolve_client_docs_base_path


JUSTIFICANTE_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+-\s+.*?Justificante guardado en:\s+(?P<path>.+?)\s*$",
    re.IGNORECASE,
)
EXP_FROM_FILENAME_RE = re.compile(
    r"JUSTIFICANTE\s*[- ]\s*(?P<exp>.+?)\.pdf$|JUSTIFICANTE\s+(?P<exp2>.+?)\.pdf$",
    re.IGNORECASE,
)
TS_SUFFIX_RE = re.compile(r"\s+\(\d{2}-\d{2}-\d{4}_\d{2}-\d{2}-\d{2}\)(?:_\d+)?$", re.IGNORECASE)


@dataclass
class SaveEvent:
    site_id: str
    log_file: Path
    ts: datetime
    raw_path: str
    resolved_path: Path
    expediente_base: str
    filename: str


def _parse_dt(text: str) -> datetime | None:
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _extract_expediente_from_filename(filename: str) -> str:
    m = EXP_FROM_FILENAME_RE.search(filename)
    if not m:
        return Path(filename).stem.strip().upper()
    exp = (m.group("exp") or m.group("exp2") or "").strip()
    exp = TS_SUFFIX_RE.sub("", exp).strip()
    return exp.upper()


def _resolve_logged_path(raw_path: str, docs_base: Path) -> Path:
    normalized = raw_path.strip().replace("\\", "/")
    if normalized.lower().startswith("/mnt/clientes/"):
        suffix = normalized[len("/mnt/clientes/") :].strip("/")
        return docs_base / Path(suffix)
    if normalized.lower() == "/mnt/clientes":
        return docs_base
    return Path(raw_path)


def _iter_site_logs(logs_dir: Path, sites: set[str] | None) -> Iterable[tuple[str, Path]]:
    if sites:
        for site in sorted(sites):
            p = logs_dir / f"{site}.log"
            if p.exists():
                yield site, p
        return

    for p in sorted(logs_dir.glob("*.log")):
        site_id = p.stem.strip().lower()
        if site_id in {"worker", "worker_out", "brain", "brain_out"}:
            continue
        yield site_id, p


def load_events(
    *,
    logs_dir: Path,
    docs_base: Path,
    sites: set[str] | None,
    since: datetime | None,
    until: datetime | None,
) -> list[SaveEvent]:
    events: list[SaveEvent] = []
    for site_id, log_file in _iter_site_logs(logs_dir, sites):
        with log_file.open("r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                m = JUSTIFICANTE_LINE_RE.search(line)
                if not m:
                    continue
                ts = _parse_dt(m.group("ts"))
                if not ts:
                    continue
                if since and ts < since:
                    continue
                if until and ts > until:
                    continue

                raw = m.group("path").strip()
                resolved = _resolve_logged_path(raw, docs_base=docs_base)
                filename = resolved.name
                exp_base = _extract_expediente_from_filename(filename)
                events.append(
                    SaveEvent(
                        site_id=site_id,
                        log_file=log_file,
                        ts=ts,
                        raw_path=raw,
                        resolved_path=resolved,
                        expediente_base=exp_base,
                        filename=filename,
                    )
                )
    return events


def build_report(events: list[SaveEvent], *, check_fs_exists: bool) -> dict:
    grouped: dict[tuple[str, str], list[SaveEvent]] = defaultdict(list)
    for ev in events:
        grouped[(ev.site_id, ev.expediente_base)].append(ev)

    suspicious: list[dict] = []
    for (site_id, expediente), group in sorted(grouped.items(), key=lambda x: (x[0][0], x[0][1])):
        group.sort(key=lambda x: x.ts)
        unique_paths = {str(g.resolved_path) for g in group}
        existing_paths = {str(g.resolved_path) for g in group if check_fs_exists and g.resolved_path.exists()}

        reason: list[str] = []
        if len(group) > 1 and len(unique_paths) == 1:
            reason.append("same_target_path_reused")
        if check_fs_exists and len(group) > len(existing_paths):
            reason.append("logged_saves_gt_existing_files")
        if not reason:
            continue

        suspicious.append(
            {
                "site_id": site_id,
                "expediente": expediente,
                "events_count": len(group),
                "unique_target_paths": len(unique_paths),
                "existing_target_paths": len(existing_paths),
                "first_seen": group[0].ts.isoformat(sep=" "),
                "last_seen": group[-1].ts.isoformat(sep=" "),
                "sample_target_path": str(group[-1].resolved_path),
                "reasons": reason,
                "log_files": sorted({str(g.log_file) for g in group}),
            }
        )

    by_site = defaultdict(int)
    for item in suspicious:
        by_site[item["site_id"]] += 1

    return {
        "generated_at": datetime.now().isoformat(),
        "total_events": len(events),
        "grouped_expedientes": len(grouped),
        "suspicious_count": len(suspicious),
        "suspicious_by_site": dict(sorted(by_site.items())),
        "suspicious": suspicious,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audita posible historico perdido de justificantes cruzando logs de guardado "
            "con existencia actual de ficheros."
        )
    )
    parser.add_argument("--logs-dir", default="logs", help="Carpeta con logs de sites.")
    parser.add_argument(
        "--sites",
        nargs="*",
        default=None,
        help="Sites a incluir (ej: xaloc_girona madrid). Si se omite, usa todos los *.log de sites.",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="Fecha inicio (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--until",
        default=None,
        help="Fecha fin (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--docs-base",
        default=None,
        help=(
            "Base docs cliente para resolver rutas /mnt/clientes en logs. "
            "Si se omite usa resolve_client_docs_base_path()."
        ),
    )
    parser.add_argument(
        "--out",
        default="tmp/audit_justificantes_history.json",
        help="Ruta de salida JSON.",
    )
    parser.add_argument("--top", type=int, default=20, help="Numero de filas a imprimir por pantalla.")
    args = parser.parse_args()

    logs_dir = Path(args.logs_dir)
    if not logs_dir.exists():
        raise SystemExit(f"No existe logs dir: {logs_dir}")

    docs_base = Path(args.docs_base or resolve_client_docs_base_path())
    sites = {s.strip().lower() for s in (args.sites or []) if str(s).strip()} or None
    since = datetime.strptime(args.since, "%Y-%m-%d") if args.since else None
    until = datetime.strptime(args.until, "%Y-%m-%d") if args.until else None

    events = load_events(
        logs_dir=logs_dir,
        docs_base=docs_base,
        sites=sites,
        since=since,
        until=until,
    )
    check_fs_exists = docs_base.exists()
    report = build_report(events, check_fs_exists=check_fs_exists)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[audit] docs_base={docs_base}")
    print(f"[audit] docs_base_accessible={check_fs_exists}")
    print(f"[audit] events={report['total_events']} grouped={report['grouped_expedientes']}")
    print(f"[audit] suspicious={report['suspicious_count']} out={out_path}")
    for row in report["suspicious"][: max(0, args.top)]:
        reasons = ",".join(row["reasons"])
        print(
            f"- {row['site_id']} | {row['expediente']} | events={row['events_count']} "
            f"| existing={row['existing_target_paths']} | reasons={reasons}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
