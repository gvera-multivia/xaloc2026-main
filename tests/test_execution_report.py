import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.append(os.getcwd())

from core.execution_report import ExecutionTracker
from core.sqlite_db import SQLiteDatabase


def _make_db_path() -> Path:
    root = Path("tmp") / "pytest_local"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"execution_report_{uuid4().hex}.db"


def test_execution_tracker_saves_reports() -> None:
    db_path = _make_db_path()
    db = SQLiteDatabase(str(db_path))
    tracker = ExecutionTracker(db=db, run_id="run_test")

    db.add_incident(
        id_recurso=1001,
        n_exp="2026/0001-MUL",
        tipo="RETRY_EXHAUSTED",
        motivo="Timeout",
        site_id="xaloc_girona",
    )
    tracker.record_success(
        payload={"idRecurso": 2002, "expediente": "2026/0002-MUL", "organismo": "XALOC"},
        site_id="xaloc_girona",
        justificante_path="tmp/downloads/2002.pdf",
        elapsed_seconds=4.2,
    )

    out_dir = Path("tmp") / f"report_out_{uuid4().hex}"
    paths = tracker.save_reports(out_dir)

    incidencias_path = Path(paths["incidencias"])
    exitos_path = Path(paths["exitos"])
    assert incidencias_path.exists()
    assert exitos_path.exists()

    incidencias_data = incidencias_path.read_text(encoding="utf-8")
    exitos_data = exitos_path.read_text(encoding="utf-8")
    assert "RETRY_EXHAUSTED" in incidencias_data
    assert "2026/0002-MUL" in exitos_data
    assert "\"total_exitos\": 1" in exitos_data

    incidencias_path.unlink(missing_ok=True)
    exitos_path.unlink(missing_ok=True)
    out_dir.rmdir()
    db_path.unlink(missing_ok=True)
