import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from core.sqlite_db import SQLiteDatabase


@dataclass
class SuccessRecord:
    id_recurso: int | None
    expediente: str
    justificante_path: str | None
    elapsed_seconds: float
    organismo: str
    site_id: str
    timestamp: str


class ExecutionTracker:
    def __init__(self, db: SQLiteDatabase, run_id: str):
        self.db = db
        self.run_id = run_id
        self.successes: list[SuccessRecord] = []

    def record_success(
        self,
        *,
        payload: dict[str, Any],
        site_id: str,
        justificante_path: str | None,
        elapsed_seconds: float,
    ) -> None:
        id_recurso = payload.get("idRecurso")
        try:
            id_recurso = int(id_recurso) if id_recurso is not None else None
        except Exception:
            id_recurso = None

        expediente = str(
            payload.get("expediente")
            or payload.get("expediente_num")
            or payload.get("denuncia_num")
            or ""
        )
        organismo = str(payload.get("organismo") or site_id)
        self.successes.append(
            SuccessRecord(
                id_recurso=id_recurso,
                expediente=expediente,
                justificante_path=justificante_path,
                elapsed_seconds=float(elapsed_seconds),
                organismo=organismo,
                site_id=site_id,
                timestamp=datetime.now().isoformat(),
            )
        )

    def build_incidents_report(self) -> dict[str, Any]:
        incidents = self.db.list_incidents()
        return {
            "run_id": self.run_id,
            "generated_at": datetime.now().isoformat(),
            "total_incidencias": len(incidents),
            "incidencias": incidents,
        }

    def build_success_report(self) -> dict[str, Any]:
        by_site = Counter(rec.site_id for rec in self.successes)
        by_org = Counter(rec.organismo for rec in self.successes)
        return {
            "run_id": self.run_id,
            "generated_at": datetime.now().isoformat(),
            "total_exitos": len(self.successes),
            "exitos_por_site": dict(sorted(by_site.items())),
            "exitos_por_organismo": dict(sorted(by_org.items())),
            "detalle_exitos": [rec.__dict__ for rec in self.successes],
        }

    def save_reports(self, output_dir: str | Path = "logs") -> dict[str, str]:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        incidents_report = self.build_incidents_report()
        success_report = self.build_success_report()

        incidents_path = out_dir / f"worker_run_{self.run_id}_incidencias.json"
        success_path = out_dir / f"worker_run_{self.run_id}_exitos.json"
        incidents_path.write_text(
            json.dumps(incidents_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        success_path.write_text(
            json.dumps(success_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return {
            "incidencias": str(incidents_path),
            "exitos": str(success_path),
        }
