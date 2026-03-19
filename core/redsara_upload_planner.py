from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from PIL import Image

from core.pdf_bundle import bundle_documents_to_single_pdf_for_palma

CompressionTier = Literal["passthrough", "rewrite", "hq", "balanced", "split"]

REDSARA_MAX_ATTACHMENTS = int((os.getenv("REDSARA_MAX_ATTACHMENTS") or "5").strip())
REDSARA_TOTAL_UPLOAD_BYTES = int((os.getenv("REDSARA_TOTAL_UPLOAD_BYTES") or str(15 * 1024 * 1024)).strip())
REDSARA_PER_FILE_UPLOAD_BYTES = int((os.getenv("REDSARA_PER_FILE_UPLOAD_BYTES") or str(10 * 1024 * 1024)).strip())
REDSARA_SOFT_TOTAL_TARGET_BYTES = int((os.getenv("REDSARA_SOFT_TOTAL_TARGET_BYTES") or str(int(14.25 * 1024 * 1024))).strip())
REDSARA_SOFT_FILE_TARGET_BYTES = int((os.getenv("REDSARA_SOFT_FILE_TARGET_BYTES") or str(int(9.25 * 1024 * 1024))).strip())
REDSARA_ENABLE_FOLLOWUP_REGISTRY = (os.getenv("REDSARA_ENABLE_FOLLOWUP_REGISTRY") or "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
    "si",
    "sí",
}


@dataclass
class PreparedDocument:
    source_path: str
    working_path: str
    display_name: str
    source_size_bytes: int
    working_size_bytes: int
    priority: int
    kind: str
    compression_tier: CompressionTier
    page_count: int | None = None
    source_paths: list[str] = field(default_factory=list)


@dataclass
class PreparedBatch:
    batch_index: int
    file_paths: list[str]
    total_size_bytes: int
    source_paths: list[str]
    manifest_path: str
    followup_registry_reference_required: bool = False


@dataclass
class PreparedUploadPlan:
    id_recurso: str
    documents: list[PreparedDocument]
    batches: list[PreparedBatch]
    total_input_files: int
    followup_registry_used: bool
    manifest_paths: list[str]
    limits: dict[str, int]

    def to_payload_dict(self) -> dict:
        return {
            "id_recurso": self.id_recurso,
            "documents": [asdict(doc) for doc in self.documents],
            "batches": [asdict(batch) for batch in self.batches],
            "total_input_files": self.total_input_files,
            "followup_registry_used": self.followup_registry_used,
            "manifest_paths": list(self.manifest_paths),
            "limits": dict(self.limits),
        }


def _size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except Exception:
        return 0


def _is_pdf_file(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(4) == b"%PDF"
    except Exception:
        return False


def _is_convertible_image_file(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            header = fh.read(16)
    except Exception:
        return False
    return header.startswith(b"\xff\xd8\xff") or header.startswith(b"\x89PNG\r\n\x1a\n")


def _convert_image_to_pdf(src: Path, *, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{src.stem}.converted.pdf"
    with Image.open(src) as image:
        if image.mode not in {"RGB"}:
            image = image.convert("RGB")
        image.save(out_path, format="PDF", resolution=150.0)
    if not _is_pdf_file(out_path):
        raise RuntimeError(f"REDSARA: no se pudo convertir la imagen a PDF: {src}")
    return out_path


def _load_pdf_reader():
    try:
        from pypdf import PdfReader  # type: ignore

        return PdfReader
    except Exception:
        from PyPDF2 import PdfReader  # type: ignore

        return PdfReader


def _load_pdf_writer():
    try:
        from pypdf import PdfWriter  # type: ignore

        return PdfWriter
    except Exception:
        from PyPDF2 import PdfWriter  # type: ignore

        return PdfWriter


def _read_pdf_page_count(path: Path) -> int | None:
    try:
        reader_cls = _load_pdf_reader()
        with path.open("rb") as fh:
            reader = reader_cls(fh)
            return int(len(reader.pages))
    except Exception:
        return None


def _rewrite_pdf(src: Path, *, output_dir: Path) -> Path | None:
    if not _is_pdf_file(src):
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{src.stem}.rewrite.pdf"
    try:
        reader_cls = _load_pdf_reader()
        writer_cls = _load_pdf_writer()
        with src.open("rb") as fh:
            reader = reader_cls(fh)
            writer = writer_cls()
            for page in reader.pages:
                writer.add_page(page)
            if hasattr(writer, "add_metadata"):
                writer.add_metadata({})
            with out_path.open("wb") as out_fh:
                writer.write(out_fh)
        if out_path.exists() and _is_pdf_file(out_path) and _size(out_path) > 0:
            return out_path
    except Exception:
        return None
    return None


def _find_gs() -> str | None:
    for exe in ("gs", "gswin64c", "gswin32c"):
        found = shutil.which(exe)
        if found:
            return found
    return None


def _compress_pdf_with_tier(src: Path, *, tier: Literal["hq", "balanced"], output_dir: Path) -> Path | None:
    gs = _find_gs()
    if not gs or not _is_pdf_file(src):
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = "hq" if tier == "hq" else "balanced"
    out_path = output_dir / f"{src.stem}.{suffix}.pdf"
    if tier == "hq":
        jpeg_q = "92"
        color_res = "200"
        gray_res = "200"
        mono_res = "300"
    else:
        jpeg_q = "85"
        color_res = "150"
        gray_res = "150"
        mono_res = "300"

    cmd = [
        gs,
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        "-dAutoRotatePages=/None",
        "-dDetectDuplicateImages=true",
        "-dCompressFonts=true",
        "-dSubsetFonts=true",
        "-dDownsampleColorImages=true",
        "-dColorImageDownsampleType=/Bicubic",
        f"-dColorImageResolution={color_res}",
        "-dDownsampleGrayImages=true",
        "-dGrayImageDownsampleType=/Bicubic",
        f"-dGrayImageResolution={gray_res}",
        "-dDownsampleMonoImages=true",
        "-dMonoImageDownsampleType=/Subsample",
        f"-dMonoImageResolution={mono_res}",
        f"-dJPEGQ={jpeg_q}",
        f"-sOutputFile={str(out_path)}",
        str(src),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        if out_path.exists() and _is_pdf_file(out_path):
            return out_path
    except Exception:
        return None
    return None


def _split_pdf_to_size(src: Path, *, max_bytes: int, output_dir: Path) -> list[Path] | None:
    if not _is_pdf_file(src):
        return None
    try:
        reader_cls = _load_pdf_reader()
        writer_cls = _load_pdf_writer()
        reader = reader_cls(str(src))
        total_pages = len(reader.pages)
    except Exception:
        return None

    if total_pages <= 1:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", src.stem) or "documento"
    probe_path = output_dir / f"{safe_stem}.probe.pdf"
    chunks: list[tuple[int, int]] = []
    start = 0
    while start < total_pages:
        best_end = -1
        for end in range(start + 1, total_pages + 1):
            writer = writer_cls()
            for idx in range(start, end):
                writer.add_page(reader.pages[idx])
            with probe_path.open("wb") as fh:
                writer.write(fh)
            if _size(probe_path) <= max_bytes:
                best_end = end
                continue
            break
        if best_end <= start:
            probe_path.unlink(missing_ok=True)
            return None
        chunks.append((start, best_end))
        start = best_end

    out_files: list[Path] = []
    for idx, (page_start, page_end) in enumerate(chunks, start=1):
        out_path = output_dir / f"{safe_stem}.part{idx:02d}.pdf"
        writer = writer_cls()
        for page_idx in range(page_start, page_end):
            writer.add_page(reader.pages[page_idx])
        with out_path.open("wb") as fh:
            writer.write(fh)
        if _size(out_path) > max_bytes or not _is_pdf_file(out_path):
            probe_path.unlink(missing_ok=True)
            return None
        out_files.append(out_path)
    probe_path.unlink(missing_ok=True)
    return out_files


def _priority_for_path(path: Path) -> int:
    name = path.name.upper()
    if "RECURSO" in name or "ESCRITO" in name:
        return 1
    if "AUT" in name or "PODER" in name or "REPRESENT" in name:
        return 2
    if "DNI" in name or "NIE" in name or "PASAPORTE" in name or "CIF" in name:
        return 3
    if "RESOL" in name or "REQUER" in name or "NOTIFIC" in name:
        return 4
    return 5


def _kind_for_path(path: Path) -> str:
    if _is_pdf_file(path):
        return "pdf"
    if _is_convertible_image_file(path):
        return "image"
    return "unknown"


def _make_prepared_document(
    *,
    source_path: Path,
    working_path: Path,
    kind: str,
    compression_tier: CompressionTier,
) -> PreparedDocument:
    return PreparedDocument(
        source_path=str(source_path),
        working_path=str(working_path),
        display_name=source_path.name,
        source_size_bytes=_size(source_path),
        working_size_bytes=_size(working_path),
        priority=_priority_for_path(source_path),
        kind=kind,
        compression_tier=compression_tier,
        page_count=_read_pdf_page_count(working_path) if _is_pdf_file(working_path) else None,
        source_paths=[str(source_path)],
    )


def _optimize_document(
    path: Path,
    *,
    soft_target_bytes: int,
    hard_target_bytes: int,
    output_dir: Path,
) -> list[PreparedDocument]:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"REDSARA: archivo no encontrado para planificar adjunto: {source}")

    kind = _kind_for_path(source)
    if kind == "unknown":
        raise ValueError(f"REDSARA: formato no soportado para compresion automatica: {source.name}")

    working = source
    tier: CompressionTier = "passthrough"
    if kind == "image":
        working = _convert_image_to_pdf(source, output_dir=output_dir / "converted")
        kind = "pdf"
        tier = "rewrite"

    current = _make_prepared_document(source_path=source, working_path=working, kind=kind, compression_tier=tier)
    target_bytes = soft_target_bytes if current.working_size_bytes > soft_target_bytes else current.working_size_bytes
    target_bytes = max(target_bytes, min(soft_target_bytes, hard_target_bytes))
    if current.working_size_bytes <= soft_target_bytes and current.working_size_bytes <= hard_target_bytes:
        return [current]

    rewrite = _rewrite_pdf(working, output_dir=output_dir / "rewrite")
    if rewrite and 0 < _size(rewrite) < current.working_size_bytes:
        current = _make_prepared_document(source_path=source, working_path=rewrite, kind=kind, compression_tier="rewrite")
        if current.working_size_bytes <= soft_target_bytes:
            return [current]

    for next_tier in ("hq", "balanced"):
        compressed = _compress_pdf_with_tier(Path(current.working_path), tier=next_tier, output_dir=output_dir / next_tier)
        if compressed and 0 < _size(compressed) < current.working_size_bytes:
            current = _make_prepared_document(
                source_path=source,
                working_path=compressed,
                kind=kind,
                compression_tier=next_tier,
            )
            if current.working_size_bytes <= soft_target_bytes:
                return [current]

    if current.working_size_bytes <= hard_target_bytes:
        return [current]

    split_parts = _split_pdf_to_size(Path(current.working_path), max_bytes=hard_target_bytes, output_dir=output_dir / "split")
    if not split_parts:
        return [current]

    split_docs: list[PreparedDocument] = []
    for split_part in split_parts:
        split_docs.append(
            PreparedDocument(
                source_path=str(source),
                working_path=str(split_part),
                display_name=source.name,
                source_size_bytes=_size(source),
                working_size_bytes=_size(split_part),
                priority=_priority_for_path(source),
                kind="pdf",
                compression_tier="split",
                page_count=_read_pdf_page_count(split_part),
                source_paths=[str(source)],
            )
        )
    return split_docs


def _total_size(docs: list[PreparedDocument]) -> int:
    return sum(int(doc.working_size_bytes) for doc in docs)


def _tighten_documents_to_total(
    docs: list[PreparedDocument],
    *,
    hard_total_bytes: int,
    output_dir: Path,
) -> list[PreparedDocument]:
    tightened = list(docs)
    if _total_size(tightened) <= hard_total_bytes:
        return tightened

    tier_rank = {"passthrough": 0, "rewrite": 1, "hq": 2, "balanced": 3, "split": 4}
    for desired_tier in ("hq", "balanced"):
        changed = True
        while _total_size(tightened) > hard_total_bytes and changed:
            changed = False
            candidates = sorted(
                [doc for doc in tightened if tier_rank.get(doc.compression_tier, 0) < tier_rank[desired_tier] and _is_pdf_file(Path(doc.working_path))],
                key=lambda doc: (-doc.priority, -doc.working_size_bytes),
            )
            for candidate in candidates:
                compressed = _compress_pdf_with_tier(
                    Path(candidate.working_path),
                    tier=desired_tier,
                    output_dir=output_dir / f"retighten_{desired_tier}",
                )
                if not compressed or _size(compressed) >= candidate.working_size_bytes:
                    continue
                idx = tightened.index(candidate)
                tightened[idx] = PreparedDocument(
                    source_path=candidate.source_path,
                    working_path=str(compressed),
                    display_name=candidate.display_name,
                    source_size_bytes=candidate.source_size_bytes,
                    working_size_bytes=_size(compressed),
                    priority=candidate.priority,
                    kind=candidate.kind,
                    compression_tier=desired_tier,
                    page_count=_read_pdf_page_count(compressed),
                    source_paths=list(candidate.source_paths or [candidate.source_path]),
                )
                changed = True
                if _total_size(tightened) <= hard_total_bytes:
                    return tightened
    return tightened


def _first_fit_decreasing_groups(docs: list[PreparedDocument], *, max_bins: int, capacity_bytes: int) -> list[list[PreparedDocument]] | None:
    bins: list[tuple[list[PreparedDocument], int]] = []
    ordered = sorted(docs, key=lambda doc: doc.working_size_bytes, reverse=True)
    for doc in ordered:
        if doc.working_size_bytes > REDSARA_PER_FILE_UPLOAD_BYTES:
            return None
        placed = False
        for idx, (bucket, used) in enumerate(bins):
            if used + doc.working_size_bytes <= capacity_bytes:
                bucket.append(doc)
                bins[idx] = (bucket, used + doc.working_size_bytes)
                placed = True
                break
        if placed:
            continue
        if len(bins) >= max_bins:
            return None
        bins.append(([doc], doc.working_size_bytes))
    return [bucket for bucket, _ in bins]


def _heuristic_groups(docs: list[PreparedDocument]) -> list[list[PreparedDocument]]:
    ordered = sorted(docs, key=lambda doc: (doc.priority, doc.display_name.lower()))
    count = len(ordered)
    total_bytes = _total_size(ordered)
    if count <= 2:
        return [[doc] for doc in ordered]
    if count == 3:
        if total_bytes <= REDSARA_SOFT_TOTAL_TARGET_BYTES:
            return [[doc] for doc in ordered]
        return [[ordered[0]], ordered[1:]]
    if count == 4:
        if total_bytes <= REDSARA_SOFT_TOTAL_TARGET_BYTES:
            return [[doc] for doc in ordered]
        return [[ordered[0]], [ordered[1]], ordered[2:]]
    if count == 5:
        if total_bytes <= REDSARA_SOFT_TOTAL_TARGET_BYTES:
            return [[doc] for doc in ordered]
        keep = ordered[:3]
        tail = ordered[3:]
        return [[keep[0]], [keep[1]], [keep[2]], tail]
    partitions = _first_fit_decreasing_groups(
        ordered,
        max_bins=REDSARA_MAX_ATTACHMENTS,
        capacity_bytes=REDSARA_SOFT_FILE_TARGET_BYTES,
    )
    if partitions is None:
        partitions = _first_fit_decreasing_groups(
            ordered,
            max_bins=REDSARA_MAX_ATTACHMENTS,
            capacity_bytes=REDSARA_PER_FILE_UPLOAD_BYTES,
        )
    if partitions is None:
        raise ValueError("REDSARA: no se pudieron agrupar los adjuntos en un maximo de 5 ficheros.")
    return partitions


def _bundle_group(
    group: list[PreparedDocument],
    *,
    batch_output_dir: Path,
    bundle_name: str,
) -> list[Path]:
    if len(group) == 1:
        return [Path(group[0].working_path)]
    bundle_path = bundle_documents_to_single_pdf_for_palma(
        [Path(doc.working_path) for doc in group],
        id_recurso=bundle_name,
        output_dir=batch_output_dir,
    )
    current = bundle_path
    if _size(current) > REDSARA_SOFT_FILE_TARGET_BYTES:
        for tier in ("hq", "balanced"):
            compressed = _compress_pdf_with_tier(current, tier=tier, output_dir=batch_output_dir / tier)
            if compressed and _size(compressed) < _size(current):
                current = compressed
                if _size(current) <= REDSARA_SOFT_FILE_TARGET_BYTES:
                    break
    if _size(current) <= REDSARA_PER_FILE_UPLOAD_BYTES:
        return [current]
    split_parts = _split_pdf_to_size(current, max_bytes=REDSARA_PER_FILE_UPLOAD_BYTES, output_dir=batch_output_dir / "split")
    if split_parts:
        return split_parts
    raise ValueError(
        f"REDSARA: bundle supera el limite por archivo y no se pudo dividir: {current.name} ({_size(current)} bytes)"
    )


def _write_batch_manifest(
    *,
    output_path: Path,
    id_recurso: str,
    batch_index: int,
    file_paths: list[Path],
    docs: list[PreparedDocument],
    followup_required: bool,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id_recurso": id_recurso,
        "batch_index": batch_index,
        "followup_registry_reference_required": followup_required,
        "file_count": len(file_paths),
        "total_size_bytes": sum(_size(path) for path in file_paths),
        "files": [{"path": str(path), "name": path.name, "size_bytes": _size(path)} for path in file_paths],
        "source_documents": [asdict(doc) for doc in docs],
    }
    output_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    return output_path


def _materialize_batch(
    docs: list[PreparedDocument],
    *,
    id_recurso: str,
    batch_index: int,
    output_dir: Path,
    followup_required: bool,
) -> PreparedBatch:
    groups = _heuristic_groups(docs)
    batch_dir = output_dir / f"batch_{batch_index:02d}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    file_paths: list[Path] = []
    for group_idx, group in enumerate(groups, start=1):
        outputs = _bundle_group(
            group,
            batch_output_dir=batch_dir / f"group_{group_idx:02d}",
            bundle_name=f"{id_recurso}_batch{batch_index}_group{group_idx}",
        )
        file_paths.extend(outputs)
    if len(file_paths) > REDSARA_MAX_ATTACHMENTS:
        raise ValueError(
            f"REDSARA: el batch {batch_index} genera {len(file_paths)} adjuntos y supera el maximo permitido."
        )
    total_size = sum(_size(path) for path in file_paths)
    if any(_size(path) > REDSARA_PER_FILE_UPLOAD_BYTES for path in file_paths):
        raise ValueError(f"REDSARA: el batch {batch_index} contiene adjuntos que superan 10 MiB.")
    if total_size > REDSARA_TOTAL_UPLOAD_BYTES:
        raise ValueError(f"REDSARA: el batch {batch_index} supera el limite total de 15 MiB.")

    manifest_path = _write_batch_manifest(
        output_path=batch_dir / "manifest.json",
        id_recurso=id_recurso,
        batch_index=batch_index,
        file_paths=file_paths,
        docs=docs,
        followup_required=followup_required,
    )
    return PreparedBatch(
        batch_index=batch_index,
        file_paths=[str(path) for path in file_paths],
        total_size_bytes=total_size,
        source_paths=sorted({src for doc in docs for src in (doc.source_paths or [doc.source_path])}),
        manifest_path=str(manifest_path),
        followup_registry_reference_required=followup_required,
    )


def _minimum_first_batch_docs(docs: list[PreparedDocument]) -> list[PreparedDocument]:
    ordered = sorted(docs, key=lambda doc: (doc.priority, doc.display_name.lower()))
    primary = [doc for doc in ordered if doc.priority == 1]
    if not primary and ordered:
        primary = [ordered[0]]

    supporting = [doc for doc in ordered if doc.priority == 2]
    if not supporting:
        supporting = [doc for doc in ordered if doc.priority == 3][:1]

    selected: list[PreparedDocument] = []
    seen: set[str] = set()
    for doc in [*primary[:1], *supporting[:1]]:
        key = doc.working_path
        if key in seen:
            continue
        selected.append(doc)
        seen.add(key)
    if not selected and ordered:
        selected.append(ordered[0])
    return selected


def prepare_redsara_upload_plan(
    files: list[Path],
    *,
    id_recurso: int | str | None,
    output_dir: Path = Path("logs/redsara/upload_planner"),
) -> PreparedUploadPlan:
    normalized = [Path(path) for path in (files or []) if path]
    if not normalized:
        raise ValueError("REDSARA: no hay archivos para preparar.")

    rid = str(id_recurso or "unknown").strip() or "unknown"
    safe_rid = re.sub(r"[^A-Za-z0-9._-]+", "_", rid) or "unknown"
    planner_root = output_dir / safe_rid
    planner_root.mkdir(parents=True, exist_ok=True)

    prepared_docs: list[PreparedDocument] = []
    for src in normalized:
        prepared_docs.extend(
            _optimize_document(
                src,
                soft_target_bytes=REDSARA_SOFT_FILE_TARGET_BYTES,
                hard_target_bytes=REDSARA_PER_FILE_UPLOAD_BYTES,
                output_dir=planner_root / "documents" / re.sub(r"[^A-Za-z0-9._-]+", "_", src.stem),
            )
        )

    prepared_docs = _tighten_documents_to_total(
        prepared_docs,
        hard_total_bytes=REDSARA_TOTAL_UPLOAD_BYTES,
        output_dir=planner_root / "retighten",
    )

    manifest_paths: list[str] = []
    try:
        single_batch = _materialize_batch(
            prepared_docs,
            id_recurso=safe_rid,
            batch_index=1,
            output_dir=planner_root / "batches",
            followup_required=False,
        )
        batches = [single_batch]
        manifest_paths.append(single_batch.manifest_path)
        return PreparedUploadPlan(
            id_recurso=rid,
            documents=prepared_docs,
            batches=batches,
            total_input_files=len(normalized),
            followup_registry_used=False,
            manifest_paths=manifest_paths,
            limits={
                "max_attachments": REDSARA_MAX_ATTACHMENTS,
                "hard_total_bytes": REDSARA_TOTAL_UPLOAD_BYTES,
                "hard_file_bytes": REDSARA_PER_FILE_UPLOAD_BYTES,
                "soft_total_bytes": REDSARA_SOFT_TOTAL_TARGET_BYTES,
                "soft_file_bytes": REDSARA_SOFT_FILE_TARGET_BYTES,
            },
        )
    except Exception as single_error:
        if not REDSARA_ENABLE_FOLLOWUP_REGISTRY:
            raise

        first_batch_docs = _minimum_first_batch_docs(prepared_docs)
        first_keys = {doc.working_path for doc in first_batch_docs}
        second_batch_docs = [doc for doc in prepared_docs if doc.working_path not in first_keys]
        if not second_batch_docs:
            raise single_error

        batch1 = _materialize_batch(
            first_batch_docs,
            id_recurso=safe_rid,
            batch_index=1,
            output_dir=planner_root / "batches",
            followup_required=False,
        )
        batch2 = _materialize_batch(
            second_batch_docs,
            id_recurso=safe_rid,
            batch_index=2,
            output_dir=planner_root / "batches",
            followup_required=True,
        )
        manifest_paths.extend([batch1.manifest_path, batch2.manifest_path])
        return PreparedUploadPlan(
            id_recurso=rid,
            documents=prepared_docs,
            batches=[batch1, batch2],
            total_input_files=len(normalized),
            followup_registry_used=True,
            manifest_paths=manifest_paths,
            limits={
                "max_attachments": REDSARA_MAX_ATTACHMENTS,
                "hard_total_bytes": REDSARA_TOTAL_UPLOAD_BYTES,
                "hard_file_bytes": REDSARA_PER_FILE_UPLOAD_BYTES,
                "soft_total_bytes": REDSARA_SOFT_TOTAL_TARGET_BYTES,
                "soft_file_bytes": REDSARA_SOFT_FILE_TARGET_BYTES,
            },
        )
