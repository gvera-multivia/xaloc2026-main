from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from core.redsara_upload_planner import (
    PreparedBatch,
    PreparedUploadPlan,
    prepare_redsara_upload_plan,
)
from core.worker_execution.models import ProcessOutcome
from core.worker_execution import task_orchestrator


def _load_pdf_writer():
    try:
        from pypdf import PdfWriter  # type: ignore

        return PdfWriter
    except Exception:
        from PyPDF2 import PdfWriter  # type: ignore

        return PdfWriter


def _make_pdf(path: Path, *, pages: int = 1) -> Path:
    writer_cls = _load_pdf_writer()
    writer = writer_cls()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def _pad_file(path: Path, *, target_size: int) -> Path:
    current = path.stat().st_size
    if current >= target_size:
        return path
    with path.open("ab") as fh:
        fh.write(b" " * (target_size - current))
    return path


def _fake_bundle_preserving_size(files: list[Path], *, id_recurso, output_dir: Path, strict: bool = True) -> Path:
    out = _make_pdf(output_dir / f"{id_recurso}.pdf")
    total_size = sum(path.stat().st_size for path in files)
    return _pad_file(out, target_size=total_size)


def test_prepare_redsara_upload_plan_single_document_keeps_single_batch(tmp_path: Path) -> None:
    source = _make_pdf(tmp_path / "RECURSO.pdf")

    plan = prepare_redsara_upload_plan([source], id_recurso=101, output_dir=tmp_path / "planner")

    assert plan.followup_registry_used is False
    assert len(plan.documents) == 1
    assert len(plan.batches) == 1
    assert len(plan.batches[0].file_paths) == 1
    assert Path(plan.batches[0].manifest_path).exists()


def test_prepare_redsara_upload_plan_converts_image_once(tmp_path: Path) -> None:
    pdf_path = _make_pdf(tmp_path / "RECURSO.pdf")
    image_path = tmp_path / "DNI.png"
    Image.new("RGB", (300, 300), color="white").save(image_path, format="PNG")

    plan = prepare_redsara_upload_plan([pdf_path, image_path], id_recurso=102, output_dir=tmp_path / "planner")

    image_docs = [doc for doc in plan.documents if doc.source_path.endswith("DNI.png")]
    assert len(image_docs) == 1
    assert image_docs[0].kind == "pdf"
    assert image_docs[0].compression_tier == "rewrite"
    assert image_docs[0].working_path.endswith(".converted.pdf")


def test_prepare_redsara_upload_plan_groups_eight_documents_into_max_five_files(tmp_path: Path) -> None:
    files = [_make_pdf(tmp_path / f"anexo_{idx}.pdf") for idx in range(8)]

    plan = prepare_redsara_upload_plan(files, id_recurso=103, output_dir=tmp_path / "planner")

    assert len(plan.batches) == 1
    assert len(plan.batches[0].file_paths) <= 5
    assert Path(plan.batches[0].manifest_path).exists()


def test_prepare_redsara_upload_plan_splits_large_pdf_when_compression_is_not_enough(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = _pad_file(_make_pdf(tmp_path / "RECURSO.pdf", pages=4), target_size=11 * 1024 * 1024)
    split_a = _make_pdf(tmp_path / "RECURSO.part01.pdf", pages=2)
    split_b = _make_pdf(tmp_path / "RECURSO.part02.pdf", pages=2)

    monkeypatch.setattr("core.redsara_upload_planner._rewrite_pdf", lambda *args, **kwargs: None)
    monkeypatch.setattr("core.redsara_upload_planner._compress_pdf_with_tier", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "core.redsara_upload_planner._split_pdf_to_size",
        lambda *args, **kwargs: [split_a, split_b],
    )

    plan = prepare_redsara_upload_plan([source], id_recurso=104, output_dir=tmp_path / "planner")

    assert len(plan.documents) == 2
    assert {doc.compression_tier for doc in plan.documents} == {"split"}
    assert len(plan.batches[0].file_paths) == 2


def test_prepare_redsara_upload_plan_uses_followup_registry_when_total_size_exceeds_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    files = [
        _pad_file(_make_pdf(tmp_path / "RECURSO.pdf"), target_size=5 * 1024 * 1024)
    ]
    files.append(_pad_file(_make_pdf(tmp_path / "AUTORIZACION.pdf"), target_size=5 * 1024 * 1024))
    files.append(_pad_file(_make_pdf(tmp_path / "DNI.pdf"), target_size=5 * 1024 * 1024))
    files.append(_pad_file(_make_pdf(tmp_path / "REQUERIMIENTO.pdf"), target_size=5 * 1024 * 1024))

    monkeypatch.setattr("core.redsara_upload_planner._rewrite_pdf", lambda *args, **kwargs: None)
    monkeypatch.setattr("core.redsara_upload_planner._compress_pdf_with_tier", lambda *args, **kwargs: None)
    monkeypatch.setattr("core.redsara_upload_planner.bundle_documents_to_single_pdf_for_palma", _fake_bundle_preserving_size)

    plan = prepare_redsara_upload_plan(files, id_recurso=105, output_dir=tmp_path / "planner")

    assert plan.followup_registry_used is True
    assert len(plan.batches) == 2
    assert plan.batches[1].followup_registry_reference_required is True


@pytest.mark.asyncio
async def test_process_task_redsara_executes_two_batches_and_marks_complete_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    batch1_file = _make_pdf(tmp_path / "batch1.pdf")
    batch2_file = _make_pdf(tmp_path / "batch2.pdf")
    batch1 = PreparedBatch(
        batch_index=1,
        file_paths=[str(batch1_file)],
        total_size_bytes=batch1_file.stat().st_size,
        source_paths=[str(batch1_file)],
        manifest_path=str(tmp_path / "batch1_manifest.json"),
        followup_registry_reference_required=False,
    )
    batch2 = PreparedBatch(
        batch_index=2,
        file_paths=[str(batch2_file)],
        total_size_bytes=batch2_file.stat().st_size,
        source_paths=[str(batch2_file)],
        manifest_path=str(tmp_path / "batch2_manifest.json"),
        followup_registry_reference_required=True,
    )
    plan = PreparedUploadPlan(
        id_recurso="999",
        documents=[],
        batches=[batch1, batch2],
        total_input_files=2,
        followup_registry_used=True,
        manifest_paths=[batch1.manifest_path, batch2.manifest_path],
        limits={},
    )

    async def _fake_download_document_and_attachments(**kwargs):
        return [batch1_file, batch2_file]

    monkeypatch.setattr(task_orchestrator, "download_document_and_attachments", _fake_download_document_and_attachments)

    async def _fake_append(payload, archivos_para_subir, *, site_id=None):
        return archivos_para_subir

    monkeypatch.setattr(task_orchestrator, "_append_required_client_docs", _fake_append)
    monkeypatch.setattr(task_orchestrator, "prepare_redsara_upload_plan", lambda *args, **kwargs: plan)
    monkeypatch.setattr(task_orchestrator, "use_remote_playwright_runner", lambda: False)

    executed_batches: list[tuple[int, str, str]] = []

    async def _fake_browser_flow(*, site_id, protocol, payload, archivos_para_subir):
        batch_index = int(payload["redsara_batch_index"])
        executed_batches.append(
            (
                batch_index,
                str(payload.get("subject") or ""),
                str(payload.get("solicit") or ""),
            )
        )
        return ProcessOutcome(
            success=True,
            payload_updates={
                "redsara_registry_uuid": f"uuid-{batch_index}",
                "redsara_justificante_client_path": str(tmp_path / f"JUSTIFICANTE-{batch_index}.pdf"),
            },
        )

    monkeypatch.setattr(task_orchestrator, "execute_browser_flow", _fake_browser_flow)

    mark_complete_calls: list[int] = []

    async def _fake_mark_complete(_session, payload):
        mark_complete_calls.append(int(payload["idRecurso"]))
        return True

    monkeypatch.setattr(task_orchestrator, "mark_resource_complete", _fake_mark_complete)

    payload = {
        "idRecurso": 999,
        "numclient": 1,
        "cliente_nombre": "Juan",
        "cliente_apellido1": "Perez",
        "subject": "Recurso principal",
        "solicit": "Solicito admision.",
    }
    outcome = await task_orchestrator.process_task(
        task_id=999,
        site_id="redsara",
        protocol=None,
        payload=payload,
        auth_session=object(),
    )

    assert outcome.success is True
    assert len(executed_batches) == 2
    assert executed_batches[0][1] == "Recurso principal"
    assert "uuid-1" in executed_batches[1][1]
    assert "uuid-1" in executed_batches[1][2]
    assert outcome.payload_updates["redsara_registry_uuids"] == ["uuid-1", "uuid-2"]
    assert len(outcome.payload_updates["redsara_justificante_paths"]) == 2
    assert mark_complete_calls == [999]
