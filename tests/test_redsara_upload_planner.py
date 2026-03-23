from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

import core.redsara_upload_planner as redsara_upload_planner
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
    assert all(Path(path).name.startswith("documentos") for path in plan.batches[0].file_paths)


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


def test_prepare_redsara_upload_plan_falls_back_to_multi_seat_when_single_submission_limit_is_exceeded(
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

    assert len(plan.batches) == 2
    assert all(batch.total_size_bytes <= 15 * 1024 * 1024 for batch in plan.batches)
    flattened = [path for batch in plan.batches for path in batch.file_paths]
    assert len(flattened) == len(set(flattened))
    assert plan.limits.get("max_batches") == 3


def test_prepare_redsara_upload_plan_uses_aggressive_compression_when_near_total_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_a = _pad_file(_make_pdf(tmp_path / "RECURSO.pdf"), target_size=8 * 1024 * 1024)
    source_b = _pad_file(_make_pdf(tmp_path / "ANEXO.pdf"), target_size=8 * 1024 * 1024)

    monkeypatch.setattr("core.redsara_upload_planner._rewrite_pdf", lambda *args, **kwargs: None)

    def _fake_compress(src: Path, *, tier: str, output_dir: Path):
        if tier != "aggressive":
            return None
        output_dir.mkdir(parents=True, exist_ok=True)
        out = _make_pdf(output_dir / f"{src.stem}.aggressive.pdf")
        if src.name.upper().startswith("ANEXO"):
            return _pad_file(out, target_size=5 * 1024 * 1024)
        return _pad_file(out, target_size=7 * 1024 * 1024)

    monkeypatch.setattr("core.redsara_upload_planner._compress_pdf_with_tier", _fake_compress)

    plan = prepare_redsara_upload_plan([source_a, source_b], id_recurso=106, output_dir=tmp_path / "planner")

    assert any(doc.compression_tier == "aggressive" for doc in plan.documents)
    assert plan.batches[0].total_size_bytes <= 15 * 1024 * 1024


def test_aggressive_compression_uses_extreme_ghostscript_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = _make_pdf(tmp_path / "RECURSO.pdf")
    captured: dict[str, list[str]] = {}

    monkeypatch.setattr(redsara_upload_planner, "_find_gs", lambda: "gs")
    monkeypatch.setattr(redsara_upload_planner, "_is_pdf_file", lambda _path: True)

    def _fake_run(cmd, check, capture_output):
        captured["cmd"] = list(cmd)
        output_arg = next(arg for arg in cmd if str(arg).startswith("-sOutputFile="))
        output_path = Path(str(output_arg).split("=", 1)[1])
        _make_pdf(output_path)
        return None

    monkeypatch.setattr(redsara_upload_planner.subprocess, "run", _fake_run)

    out = redsara_upload_planner._compress_pdf_with_tier(
        source,
        tier="aggressive",
        output_dir=tmp_path / "aggressive",
    )

    assert out is not None
    assert "-dJPEGQ=18" in captured["cmd"]
    assert "-dColorImageResolution=30" in captured["cmd"]
    assert "-dGrayImageResolution=30" in captured["cmd"]
    assert "-dMonoImageResolution=72" in captured["cmd"]
    assert "-dPDFSETTINGS=/screen" in captured["cmd"]
    assert "-dColorImageDownsampleThreshold=1.0" in captured["cmd"]
    assert "-dGrayImageDownsampleThreshold=1.0" in captured["cmd"]
    assert "-dMonoImageDownsampleThreshold=1.0" in captured["cmd"]


def test_ultra_compression_uses_stupidly_low_ghostscript_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = _make_pdf(tmp_path / "RECURSO.pdf")
    captured: dict[str, list[str]] = {}

    monkeypatch.setattr(redsara_upload_planner, "_find_gs", lambda: "gs")
    monkeypatch.setattr(redsara_upload_planner, "_is_pdf_file", lambda _path: True)

    def _fake_run(cmd, check, capture_output):
        captured["cmd"] = list(cmd)
        output_arg = next(arg for arg in cmd if str(arg).startswith("-sOutputFile="))
        output_path = Path(str(output_arg).split("=", 1)[1])
        _make_pdf(output_path)
        return None

    monkeypatch.setattr(redsara_upload_planner.subprocess, "run", _fake_run)

    out = redsara_upload_planner._compress_pdf_with_tier(
        source,
        tier="ultra",
        output_dir=tmp_path / "ultra",
    )

    assert out is not None
    assert "-dJPEGQ=1" in captured["cmd"]
    assert "-dColorImageResolution=10" in captured["cmd"]
    assert "-dGrayImageResolution=10" in captured["cmd"]
    assert "-dMonoImageResolution=18" in captured["cmd"]
    assert "-dTextAlphaBits=1" in captured["cmd"]
    assert "-dGraphicsAlphaBits=1" in captured["cmd"]


def test_nuclear_rasterization_uses_brutal_low_resolution_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = _make_pdf(tmp_path / "RECURSO.pdf", pages=2)
    captured: dict[str, list[str]] = {}

    monkeypatch.setattr(redsara_upload_planner, "_find_gs", lambda: "gs")
    monkeypatch.setattr(redsara_upload_planner, "_is_pdf_file", lambda _path: True)

    def _fake_run(cmd, check, capture_output):
        captured["cmd"] = list(cmd)
        output_arg = next(arg for arg in cmd if str(arg).startswith("-sOutputFile="))
        pattern = str(output_arg).split("=", 1)[1]
        page_path = Path(pattern.replace("%03d", "001"))
        page_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("L", (16, 16), color=255).save(page_path, format="JPEG", quality=10)
        second_path = Path(pattern.replace("%03d", "002"))
        Image.new("L", (16, 16), color=200).save(second_path, format="JPEG", quality=10)
        return None

    monkeypatch.setattr(redsara_upload_planner.subprocess, "run", _fake_run)

    out = redsara_upload_planner._rasterize_pdf_nuclear(
        source,
        output_dir=tmp_path / "nuclear",
    )

    assert out is not None
    assert "-sDEVICE=jpeggray" in captured["cmd"]
    assert "-r24" in captured["cmd"]
    assert "-dJPEGQ=1" in captured["cmd"]
    assert "-dTextAlphaBits=1" in captured["cmd"]
    assert "-dGraphicsAlphaBits=1" in captured["cmd"]


def test_prepare_redsara_upload_plan_uses_nuclear_compression_when_aggressive_is_not_enough(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_a = _pad_file(_make_pdf(tmp_path / "RECURSO.pdf"), target_size=8 * 1024 * 1024)
    source_b = _pad_file(_make_pdf(tmp_path / "ANEXO.pdf"), target_size=8 * 1024 * 1024)

    monkeypatch.setattr("core.redsara_upload_planner._rewrite_pdf", lambda *args, **kwargs: None)

    def _fake_compress(src: Path, *, tier: str, output_dir: Path):
        if tier != "aggressive":
            return None
        output_dir.mkdir(parents=True, exist_ok=True)
        out = _make_pdf(output_dir / f"{src.stem}.aggressive.pdf")
        return _pad_file(out, target_size=7_800_000)

    def _fake_nuclear(src: Path, *, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        out = _make_pdf(output_dir / f"{src.stem}.nuclear.pdf")
        return _pad_file(out, target_size=5_000_000)

    monkeypatch.setattr("core.redsara_upload_planner._compress_pdf_with_tier", _fake_compress)
    monkeypatch.setattr("core.redsara_upload_planner._rasterize_pdf_nuclear", _fake_nuclear)

    plan = prepare_redsara_upload_plan([source_a, source_b], id_recurso=107, output_dir=tmp_path / "planner")

    assert any(doc.compression_tier == "nuclear" for doc in plan.documents)
    assert plan.batches[0].total_size_bytes <= 15 * 1024 * 1024


def test_prepare_redsara_upload_plan_uses_ultra_compression_when_nuclear_is_not_enough(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_a = _pad_file(_make_pdf(tmp_path / "RECURSO.pdf"), target_size=8 * 1024 * 1024)
    source_b = _pad_file(_make_pdf(tmp_path / "ANEXO.pdf"), target_size=8 * 1024 * 1024)

    monkeypatch.setattr("core.redsara_upload_planner._rewrite_pdf", lambda *args, **kwargs: None)

    def _fake_compress(src: Path, *, tier: str, output_dir: Path):
        if tier != "aggressive":
            return None
        output_dir.mkdir(parents=True, exist_ok=True)
        out = _make_pdf(output_dir / f"{src.stem}.aggressive.pdf")
        return _pad_file(out, target_size=7_800_000)

    monkeypatch.setattr("core.redsara_upload_planner._compress_pdf_with_tier", _fake_compress)
    monkeypatch.setattr("core.redsara_upload_planner._rasterize_pdf_nuclear", lambda *args, **kwargs: None)

    def _fake_ultra(src: Path, *, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        out = _make_pdf(output_dir / f"{src.stem}.ultra.pdf")
        return _pad_file(out, target_size=4_500_000)

    monkeypatch.setattr("core.redsara_upload_planner._rasterize_pdf_ultra", _fake_ultra)

    plan = prepare_redsara_upload_plan([source_a, source_b], id_recurso=108, output_dir=tmp_path / "planner")

    assert any(doc.compression_tier == "ultra" for doc in plan.documents)
    assert plan.batches[0].total_size_bytes <= 15 * 1024 * 1024


@pytest.mark.asyncio
async def test_process_task_redsara_executes_single_batch_and_preserves_subject(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    batch1_file = _make_pdf(tmp_path / "batch1.pdf")
    batch1 = PreparedBatch(
        batch_index=1,
        file_paths=[str(batch1_file)],
        total_size_bytes=batch1_file.stat().st_size,
        source_paths=[str(batch1_file)],
        manifest_path=str(tmp_path / "batch1_manifest.json"),
    )
    plan = PreparedUploadPlan(
        id_recurso="999",
        documents=[],
        batches=[batch1],
        total_input_files=1,
        manifest_paths=[batch1.manifest_path],
        limits={},
    )

    async def _fake_download_document_and_attachments(**kwargs):
        return [batch1_file]

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
    assert len(executed_batches) == 1
    assert executed_batches[0][1] == "Recurso principal"
    assert executed_batches[0][2] == "Solicito admision."
    assert outcome.payload_updates["redsara_registry_uuids"] == ["uuid-1"]
    assert len(outcome.payload_updates["redsara_justificante_paths"]) == 1
    assert mark_complete_calls == [999]


@pytest.mark.asyncio
async def test_process_task_redsara_multi_seat_adds_reference_and_registry_numbers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    batch1_file = _make_pdf(tmp_path / "batch1.pdf")
    batch2_file = _make_pdf(tmp_path / "batch2.pdf")
    receipt1 = _make_pdf(tmp_path / "receipt1.pdf")
    receipt2 = _make_pdf(tmp_path / "receipt2.pdf")

    batch1 = PreparedBatch(
        batch_index=1,
        file_paths=[str(batch1_file)],
        total_size_bytes=batch1_file.stat().st_size,
        source_paths=[str(batch1_file)],
        manifest_path=str(tmp_path / "batch1_manifest.json"),
    )
    batch2 = PreparedBatch(
        batch_index=2,
        file_paths=[str(batch2_file)],
        total_size_bytes=batch2_file.stat().st_size,
        source_paths=[str(batch2_file)],
        manifest_path=str(tmp_path / "batch2_manifest.json"),
    )
    plan = PreparedUploadPlan(
        id_recurso="1001",
        documents=[],
        batches=[batch1, batch2],
        total_input_files=2,
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
        receipt_path = receipt1 if batch_index == 1 else receipt2
        return ProcessOutcome(
            success=True,
            payload_updates={
                "redsara_registry_uuid": f"uuid-{batch_index}",
                "redsara_justificante_artifact_path": str(receipt_path),
            },
        )

    monkeypatch.setattr(task_orchestrator, "execute_browser_flow", _fake_browser_flow)
    monkeypatch.setattr(
        task_orchestrator,
        "resolve_redsara_receipt_dir",
        lambda _payload: tmp_path / "cliente",
    )

    def _fake_parse(path: Path):
        name = Path(path).name
        if name == "receipt1.pdf":
            return "REGAGE26E00000000001"
        if name == "receipt2.pdf":
            return "REGAGE26E00000000002"
        return None

    monkeypatch.setattr(task_orchestrator, "parse_regage_from_receipt_pdf", _fake_parse)

    def _fake_persist(*, source_path, destination_dir, filename):
        destination_dir.mkdir(parents=True, exist_ok=True)
        out = destination_dir / filename
        Path(out).write_bytes(Path(source_path).read_bytes())
        return out

    monkeypatch.setattr(task_orchestrator, "persist_redsara_receipt_with_dedupe", _fake_persist)

    mark_complete_calls: list[int] = []

    async def _fake_mark_complete(_session, payload):
        mark_complete_calls.append(int(payload["idRecurso"]))
        return True

    monkeypatch.setattr(task_orchestrator, "mark_resource_complete", _fake_mark_complete)

    payload = {
        "idRecurso": 1001,
        "numclient": 1,
        "cliente_nombre": "Juan",
        "cliente_apellido1": "Perez",
        "subject": "Recurso de Reposicion",
        "solicit": "Solicito admision.",
        "expediente": "2025SACR0996394",
    }
    outcome = await task_orchestrator.process_task(
        task_id=1001,
        site_id="redsara",
        protocol=None,
        payload=payload,
        auth_session=object(),
    )

    assert outcome.success is True
    assert len(executed_batches) == 2
    assert executed_batches[0][1] == "Recurso de Reposicion"
    assert "REGAGE26E00000000001" in executed_batches[1][1]
    assert "lote 2/2" in executed_batches[1][2].lower()
    assert outcome.payload_updates["redsara_registry_numbers"] == [
        "REGAGE26E00000000001",
        "REGAGE26E00000000002",
    ]
    assert outcome.payload_updates["redsara_followup_registry_used"] is True
    assert outcome.payload_updates["redsara_followup_chain_mode"] == "regage"
    assert mark_complete_calls == [1001]


@pytest.mark.asyncio
async def test_process_task_redsara_multi_seat_falls_back_to_expediente_reference_when_regage_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    batch1_file = _make_pdf(tmp_path / "batch1.pdf")
    batch2_file = _make_pdf(tmp_path / "batch2.pdf")
    receipt1 = _make_pdf(tmp_path / "receipt1.pdf")
    receipt2 = _make_pdf(tmp_path / "receipt2.pdf")

    plan = PreparedUploadPlan(
        id_recurso="1002",
        documents=[],
        batches=[
            PreparedBatch(
                batch_index=1,
                file_paths=[str(batch1_file)],
                total_size_bytes=batch1_file.stat().st_size,
                source_paths=[str(batch1_file)],
                manifest_path=str(tmp_path / "batch1_manifest.json"),
            ),
            PreparedBatch(
                batch_index=2,
                file_paths=[str(batch2_file)],
                total_size_bytes=batch2_file.stat().st_size,
                source_paths=[str(batch2_file)],
                manifest_path=str(tmp_path / "batch2_manifest.json"),
            ),
        ],
        total_input_files=2,
        manifest_paths=[str(tmp_path / "batch1_manifest.json"), str(tmp_path / "batch2_manifest.json")],
        limits={},
    )

    async def _fake_download_document_and_attachments(**kwargs):
        return [batch1_file, batch2_file]

    monkeypatch.setattr(task_orchestrator, "download_document_and_attachments", _fake_download_document_and_attachments)
    monkeypatch.setattr(task_orchestrator, "prepare_redsara_upload_plan", lambda *args, **kwargs: plan)
    monkeypatch.setattr(task_orchestrator, "use_remote_playwright_runner", lambda: False)

    async def _fake_append(payload, archivos_para_subir, *, site_id=None):
        return archivos_para_subir

    monkeypatch.setattr(task_orchestrator, "_append_required_client_docs", _fake_append)

    executed_subjects: list[str] = []

    async def _fake_browser_flow(*, site_id, protocol, payload, archivos_para_subir):
        batch_index = int(payload["redsara_batch_index"])
        executed_subjects.append(str(payload.get("subject") or ""))
        return ProcessOutcome(
            success=True,
            payload_updates={
                "redsara_registry_uuid": f"uuid-{batch_index}",
                "redsara_justificante_artifact_path": str(receipt1 if batch_index == 1 else receipt2),
            },
        )

    monkeypatch.setattr(task_orchestrator, "execute_browser_flow", _fake_browser_flow)
    monkeypatch.setattr(task_orchestrator, "parse_regage_from_receipt_pdf", lambda _path: None)
    monkeypatch.setattr(task_orchestrator, "resolve_redsara_receipt_dir", lambda _payload: tmp_path / "cliente")
    monkeypatch.setattr(task_orchestrator, "persist_redsara_receipt_with_dedupe", lambda **kwargs: tmp_path / "cliente" / kwargs["filename"])

    async def _fake_mark_complete(*_args, **_kwargs):
        return True

    monkeypatch.setattr(task_orchestrator, "mark_resource_complete", _fake_mark_complete)

    payload = {
        "idRecurso": 1002,
        "numclient": 1,
        "cliente_nombre": "Juan",
        "cliente_apellido1": "Perez",
        "subject": "Recurso base",
        "solicit": "Solicito admision.",
        "expediente": "EXP-123",
    }
    outcome = await task_orchestrator.process_task(
        task_id=1002,
        site_id="redsara",
        protocol=None,
        payload=payload,
        auth_session=object(),
    )

    assert outcome.success is True
    assert len(executed_subjects) == 2
    assert "expediente exp-123" in executed_subjects[1].lower()
    assert outcome.payload_updates["redsara_followup_chain_mode"] == "expediente_fallback"
