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

CompressionTier = Literal["passthrough", "rewrite", "hq", "balanced", "aggressive", "nuclear", "ultra", "split"]

REDSARA_MAX_ATTACHMENTS = int((os.getenv("REDSARA_MAX_ATTACHMENTS") or "5").strip())
REDSARA_TOTAL_UPLOAD_BYTES = int((os.getenv("REDSARA_TOTAL_UPLOAD_BYTES") or str(15 * 1024 * 1024)).strip())
REDSARA_PER_FILE_UPLOAD_BYTES = int((os.getenv("REDSARA_PER_FILE_UPLOAD_BYTES") or str(10 * 1024 * 1024)).strip())
REDSARA_SOFT_TOTAL_TARGET_BYTES = int((os.getenv("REDSARA_SOFT_TOTAL_TARGET_BYTES") or str(int(14.25 * 1024 * 1024))).strip())
REDSARA_SOFT_FILE_TARGET_BYTES = int((os.getenv("REDSARA_SOFT_FILE_TARGET_BYTES") or str(int(9.25 * 1024 * 1024))).strip())
REDSARA_MAX_BATCHES = max(1, int((os.getenv("REDSARA_MAX_BATCHES") or "3").strip()))
REDSARA_NEAR_TOTAL_MARGIN_BYTES = int((os.getenv("REDSARA_NEAR_TOTAL_MARGIN_BYTES") or str(512 * 1024)).strip())
REDSARA_AGGRESSIVE_TOTAL_TRIGGER_BYTES = max(
    REDSARA_SOFT_TOTAL_TARGET_BYTES,
    REDSARA_TOTAL_UPLOAD_BYTES - REDSARA_NEAR_TOTAL_MARGIN_BYTES,
)
REDSARA_ULTRA_DPI = int((os.getenv("REDSARA_ULTRA_DPI") or "10").strip())
REDSARA_ULTRA_JPEG_Q = int((os.getenv("REDSARA_ULTRA_JPEG_Q") or "1").strip())
REDSARA_MIN_REDUCTION_BYTES = int((os.getenv("REDSARA_MIN_REDUCTION_BYTES") or "1024").strip())

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


@dataclass
class PreparedUploadPlan:
    id_recurso: str
    documents: list[PreparedDocument]
    batches: list[PreparedBatch]
    total_input_files: int
    manifest_paths: list[str]
    limits: dict[str, int]

    def to_payload_dict(self) -> dict:
        return {
            "id_recurso": self.id_recurso,
            "documents": [asdict(doc) for doc in self.documents],
            "batches": [asdict(batch) for batch in self.batches],
            "total_input_files": self.total_input_files,
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


def _compress_pdf_with_tier(src: Path, *, tier: Literal["hq", "balanced", "aggressive", "ultra"], output_dir: Path) -> Path | None:
    gs = _find_gs()
    if not gs or not _is_pdf_file(src):
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = str(tier)
    out_path = output_dir / f"{src.stem}.{suffix}.pdf"
    if tier == "hq":
        jpeg_q = "92"
        color_res = "200"
        gray_res = "200"
        mono_res = "300"
        extra_args: list[str] = []
    elif tier == "balanced":
        jpeg_q = "85"
        color_res = "150"
        gray_res = "150"
        mono_res = "300"
        extra_args = []
    elif tier == "aggressive":
        jpeg_q = "18"
        color_res = "30"
        gray_res = "30"
        mono_res = "72"
        extra_args = [
            "-dPDFSETTINGS=/screen",
            "-dColorImageDownsampleThreshold=1.0",
            "-dGrayImageDownsampleThreshold=1.0",
            "-dMonoImageDownsampleThreshold=1.0",
            "-dEncodeColorImages=true",
            "-dEncodeGrayImages=true",
            "-dEncodeMonoImages=true",
        ]
    else:
        jpeg_q = str(max(1, REDSARA_ULTRA_JPEG_Q))
        ultra_dpi = str(max(6, REDSARA_ULTRA_DPI))
        color_res = ultra_dpi
        gray_res = ultra_dpi
        mono_res = "18"
        extra_args = [
            "-dPDFSETTINGS=/screen",
            "-dColorImageDownsampleThreshold=1.0",
            "-dGrayImageDownsampleThreshold=1.0",
            "-dMonoImageDownsampleThreshold=1.0",
            "-dEncodeColorImages=true",
            "-dEncodeGrayImages=true",
            "-dEncodeMonoImages=true",
            "-dTextAlphaBits=1",
            "-dGraphicsAlphaBits=1",
        ]

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
        *extra_args,
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


def _rasterize_pdf_nuclear(src: Path, *, output_dir: Path, dpi: int = 24) -> Path | None:
    gs = _find_gs()
    if not gs or not _is_pdf_file(src):
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", src.stem) or "documento"
    page_dir = output_dir / f"{safe_stem}.pages"
    page_dir.mkdir(parents=True, exist_ok=True)
    page_pattern = page_dir / f"{safe_stem}.page-%03d.jpg"
    out_path = output_dir / f"{src.stem}.nuclear.pdf"

    safe_dpi = max(6, int(dpi))
    cmd = [
        gs,
        "-sDEVICE=jpeggray",
        "-dCompatibilityLevel=1.4",
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        "-dSAFER",
        "-dAutoRotatePages=/None",
        "-dDetectDuplicateImages=true",
        "-dCompressFonts=true",
        "-dSubsetFonts=true",
        "-dTextAlphaBits=1",
        "-dGraphicsAlphaBits=1",
        "-dDownsampleColorImages=true",
        f"-dColorImageResolution={safe_dpi}",
        "-dDownsampleGrayImages=true",
        f"-dGrayImageResolution={safe_dpi}",
        "-dDownsampleMonoImages=true",
        "-dMonoImageResolution=18",
        "-dJPEGQ=1",
        f"-r{safe_dpi}",
        f"-sOutputFile={str(page_pattern)}",
        str(src),
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except Exception:
        return None

    page_files = sorted(page_dir.glob(f"{safe_stem}.page-*.jpg"))
    if not page_files:
        return None

    images: list[Image.Image] = []
    try:
        for page_file in page_files:
            with Image.open(page_file) as page_image:
                images.append(page_image.convert("L"))
        if not images:
            return None
        first_image = images[0]
        first_image.save(
            out_path,
            format="PDF",
            save_all=True,
            append_images=images[1:],
            resolution=float(safe_dpi),
        )
    except Exception:
        return None

    if out_path.exists() and _is_pdf_file(out_path) and _size(out_path) > 0:
        return out_path
    return None


def _rasterize_pdf_ultra(src: Path, *, output_dir: Path) -> Path | None:
    current_size = _size(src)
    best: Path | None = None
    best_size = current_size
    for dpi in (max(6, REDSARA_ULTRA_DPI), 8, 6):
        candidate = _rasterize_pdf_nuclear(src, output_dir=output_dir / f"dpi_{dpi}", dpi=dpi)
        if not candidate:
            continue
        candidate_size = _size(candidate)
        if 0 < candidate_size < best_size:
            best = candidate
            best_size = candidate_size
    return best


def _shrink_pdf_once(src: Path, *, output_dir: Path, allow_split: bool = False) -> list[Path] | None:
    if not _is_pdf_file(src):
        return None
    current_size = _size(src)
    best_path = src
    best_size = current_size

    for tier in ("aggressive", "nuclear", "ultra"):
        if tier == "nuclear":
            candidate = _rasterize_pdf_nuclear(best_path, output_dir=output_dir / tier)
        elif tier == "ultra":
            candidate = _rasterize_pdf_ultra(best_path, output_dir=output_dir / tier)
        else:
            candidate = _compress_pdf_with_tier(best_path, tier="aggressive", output_dir=output_dir / tier)
        if not candidate:
            continue
        candidate_size = _size(candidate)
        if candidate_size <= 0 or candidate_size >= best_size:
            continue
        best_path = candidate
        best_size = candidate_size

    if best_path is not src and (current_size - best_size) >= max(1, REDSARA_MIN_REDUCTION_BYTES):
        return [best_path]

    if allow_split and current_size > REDSARA_PER_FILE_UPLOAD_BYTES:
        split_parts = _split_pdf_to_size(src, max_bytes=REDSARA_PER_FILE_UPLOAD_BYTES, output_dir=output_dir / "split")
        if split_parts:
            return split_parts
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

    aggressive = _compress_pdf_with_tier(Path(current.working_path), tier="aggressive", output_dir=output_dir / "aggressive")
    if aggressive and 0 < _size(aggressive) < current.working_size_bytes:
        current = _make_prepared_document(
            source_path=source,
            working_path=aggressive,
            kind=kind,
            compression_tier="aggressive",
        )
        if current.working_size_bytes <= hard_target_bytes:
            return [current]

    nuclear = _rasterize_pdf_nuclear(Path(current.working_path), output_dir=output_dir / "nuclear")
    if nuclear and 0 < _size(nuclear) < current.working_size_bytes:
        current = _make_prepared_document(
            source_path=source,
            working_path=nuclear,
            kind=kind,
            compression_tier="nuclear",
        )
        if current.working_size_bytes <= hard_target_bytes:
            return [current]

    ultra = _rasterize_pdf_ultra(Path(current.working_path), output_dir=output_dir / "ultra")
    if ultra and 0 < _size(ultra) < current.working_size_bytes:
        current = _make_prepared_document(
            source_path=source,
            working_path=ultra,
            kind=kind,
            compression_tier="ultra",
        )
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
    target_total_bytes: int,
    output_dir: Path,
) -> list[PreparedDocument]:
    tightened = list(docs)
    if _total_size(tightened) <= target_total_bytes:
        return tightened

    tier_rank = {"passthrough": 0, "rewrite": 1, "hq": 2, "balanced": 3, "aggressive": 4, "nuclear": 5, "ultra": 6, "split": 7}
    for desired_tier in ("hq", "balanced", "aggressive", "nuclear", "ultra"):
        changed = True
        while _total_size(tightened) > target_total_bytes and changed:
            changed = False
            candidates = sorted(
                [doc for doc in tightened if tier_rank.get(doc.compression_tier, 0) < tier_rank[desired_tier] and _is_pdf_file(Path(doc.working_path))],
                key=lambda doc: (-doc.priority, -doc.working_size_bytes),
            )
            for candidate in candidates:
                if desired_tier == "nuclear":
                    compressed = _rasterize_pdf_nuclear(
                        Path(candidate.working_path),
                        output_dir=output_dir / f"retighten_{desired_tier}",
                    )
                elif desired_tier == "ultra":
                    compressed = _rasterize_pdf_ultra(
                        Path(candidate.working_path),
                        output_dir=output_dir / f"retighten_{desired_tier}",
                    )
                else:
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
                if _total_size(tightened) <= target_total_bytes:
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
    if not ordered:
        return []
    count = len(ordered)
    if count <= REDSARA_MAX_ATTACHMENTS:
        return [[doc] for doc in ordered]
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


def _partition_docs_into_seats(
    docs: list[PreparedDocument],
    *,
    max_seats: int,
    seat_capacity_bytes: int,
) -> list[list[PreparedDocument]] | None:
    if not docs or max_seats < 2:
        return None

    bins: list[tuple[list[PreparedDocument], int]] = []
    ordered = sorted(docs, key=lambda doc: doc.working_size_bytes, reverse=True)
    for doc in ordered:
        if doc.working_size_bytes > seat_capacity_bytes:
            return None
        placed = False
        for idx, (bucket, used) in enumerate(bins):
            if used + doc.working_size_bytes <= seat_capacity_bytes:
                bucket.append(doc)
                bins[idx] = (bucket, used + doc.working_size_bytes)
                placed = True
                break
        if placed:
            continue
        if len(bins) >= max_seats:
            return None
        bins.append(([doc], doc.working_size_bytes))

    if len(bins) < 2:
        return None

    ordered_bins = sorted(
        bins,
        key=lambda item: (
            min(doc.priority for doc in item[0]),
            -item[1],
            min(doc.display_name.lower() for doc in item[0]),
        ),
    )
    return [sorted(bucket, key=lambda doc: (doc.priority, doc.display_name.lower())) for bucket, _ in ordered_bins]


def _materialize_multi_seat_batches(
    docs: list[PreparedDocument],
    *,
    id_recurso: str,
    output_dir: Path,
) -> list[PreparedBatch]:
    for seat_capacity in (REDSARA_SOFT_TOTAL_TARGET_BYTES, REDSARA_TOTAL_UPLOAD_BYTES):
        for seat_count in range(2, REDSARA_MAX_BATCHES + 1):
            partitions = _partition_docs_into_seats(
                docs,
                max_seats=seat_count,
                seat_capacity_bytes=seat_capacity,
            )
            if not partitions:
                continue
            try:
                batches: list[PreparedBatch] = []
                for idx, seat_docs in enumerate(partitions, start=1):
                    batches.append(
                        _materialize_batch(
                            seat_docs,
                            id_recurso=id_recurso,
                            batch_index=idx,
                            output_dir=output_dir,
                        )
                    )
                return batches
            except Exception:
                continue
    raise ValueError(
        f"REDSARA: no se pudo dividir el envio en un maximo de {REDSARA_MAX_BATCHES} asientos validos."
    )


def _bundle_group(
    group: list[PreparedDocument],
    *,
    batch_output_dir: Path,
    output_basename: str,
) -> list[Path]:
    batch_output_dir.mkdir(parents=True, exist_ok=True)
    if len(group) == 1:
        src = Path(group[0].working_path)
        target = batch_output_dir / f"{output_basename}{src.suffix.lower() or '.pdf'}"
        if src.resolve() == target.resolve():
            return [src]
        shutil.copy2(src, target)
        return [target]
    bundle_path = bundle_documents_to_single_pdf_for_palma(
        [Path(doc.working_path) for doc in group],
        id_recurso=output_basename,
        output_dir=batch_output_dir,
    )
    current = bundle_path
    if _size(current) > REDSARA_SOFT_FILE_TARGET_BYTES:
        for tier in ("hq", "balanced", "aggressive", "ultra"):
            compressed = _compress_pdf_with_tier(current, tier=tier, output_dir=batch_output_dir / tier)
            if compressed and _size(compressed) < _size(current):
                current = compressed
                if _size(current) <= REDSARA_SOFT_FILE_TARGET_BYTES:
                    break
    if _size(current) <= REDSARA_PER_FILE_UPLOAD_BYTES:
        friendly_path = batch_output_dir / f"{output_basename}.pdf"
        if current.resolve() != friendly_path.resolve():
            current = current.replace(friendly_path)
        return [current]
    nuclear = _rasterize_pdf_nuclear(current, output_dir=batch_output_dir / "nuclear")
    if nuclear and _size(nuclear) < _size(current):
        current = nuclear
        if _size(current) <= REDSARA_PER_FILE_UPLOAD_BYTES:
            friendly_path = batch_output_dir / f"{output_basename}.pdf"
            if current.resolve() != friendly_path.resolve():
                current = current.replace(friendly_path)
            return [current]
    ultra = _rasterize_pdf_ultra(current, output_dir=batch_output_dir / "ultra")
    if ultra and _size(ultra) < _size(current):
        current = ultra
        if _size(current) <= REDSARA_PER_FILE_UPLOAD_BYTES:
            friendly_path = batch_output_dir / f"{output_basename}.pdf"
            if current.resolve() != friendly_path.resolve():
                current = current.replace(friendly_path)
            return [current]
    split_parts = _split_pdf_to_size(current, max_bytes=REDSARA_PER_FILE_UPLOAD_BYTES, output_dir=batch_output_dir / "split")
    if split_parts:
        renamed_parts: list[Path] = []
        for idx, split_part in enumerate(split_parts, start=1):
            renamed = batch_output_dir / f"{output_basename}_{idx:02d}.pdf"
            renamed_parts.append(split_part.replace(renamed))
        return renamed_parts
    raise ValueError(
        f"REDSARA: bundle supera el limite por archivo y no se pudo dividir: {current.name} ({_size(current)} bytes)"
    )


def _fit_batch_outputs_to_limits(file_paths: list[Path], *, output_dir: Path) -> list[Path]:
    current = list(file_paths)
    output_dir.mkdir(parents=True, exist_ok=True)

    def _total(paths: list[Path]) -> int:
        return sum(_size(path) for path in paths)

    def _within_limits(paths: list[Path]) -> bool:
        return (
            len(paths) <= REDSARA_MAX_ATTACHMENTS
            and all(_size(path) <= REDSARA_PER_FILE_UPLOAD_BYTES for path in paths)
            and _total(paths) <= REDSARA_TOTAL_UPLOAD_BYTES
        )

    if _within_limits(current):
        return current

    for _ in range(20):
        if _within_limits(current):
            return current
        oversized = [path for path in current if _is_pdf_file(path) and _size(path) > REDSARA_PER_FILE_UPLOAD_BYTES]
        if oversized:
            target = max(oversized, key=_size)
        else:
            pdfs = [path for path in current if _is_pdf_file(path)]
            if not pdfs:
                break
            target = max(pdfs, key=_size)

        replacement = _shrink_pdf_once(
            target,
            output_dir=output_dir / "tighten",
            allow_split=True,
        )
        if not replacement:
            break

        idx = current.index(target)
        current = [*current[:idx], *replacement, *current[idx + 1 :]]
        if len(current) > REDSARA_MAX_ATTACHMENTS:
            break

    if _within_limits(current):
        return current

    pdfs = [path for path in current if _is_pdf_file(path)]
    if len(pdfs) == len(current) and pdfs:
        merged = bundle_documents_to_single_pdf_for_palma(
            pdfs,
            id_recurso="documentos",
            output_dir=output_dir / "final_merge",
        )
        merged_candidate = merged
        for tier in ("aggressive", "nuclear", "ultra"):
            if tier == "nuclear":
                shrunk = _rasterize_pdf_nuclear(merged_candidate, output_dir=output_dir / "final_merge" / tier)
            elif tier == "ultra":
                shrunk = _rasterize_pdf_ultra(merged_candidate, output_dir=output_dir / "final_merge" / tier)
            else:
                shrunk = _compress_pdf_with_tier(merged_candidate, tier="aggressive", output_dir=output_dir / "final_merge" / tier)
            if shrunk and 0 < _size(shrunk) < _size(merged_candidate):
                merged_candidate = shrunk

        if _size(merged_candidate) <= REDSARA_TOTAL_UPLOAD_BYTES:
            if _size(merged_candidate) <= REDSARA_PER_FILE_UPLOAD_BYTES:
                return [merged_candidate]
            split_parts = _split_pdf_to_size(
                merged_candidate,
                max_bytes=REDSARA_PER_FILE_UPLOAD_BYTES,
                output_dir=output_dir / "final_merge" / "split",
            )
            if split_parts and len(split_parts) <= REDSARA_MAX_ATTACHMENTS and _total(split_parts) <= REDSARA_TOTAL_UPLOAD_BYTES:
                return split_parts

    return current


def _write_batch_manifest(
    *,
    output_path: Path,
    id_recurso: str,
    batch_index: int,
    file_paths: list[Path],
    docs: list[PreparedDocument],
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id_recurso": id_recurso,
        "batch_index": batch_index,
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
) -> PreparedBatch:
    groups = _heuristic_groups(docs)
    batch_dir = output_dir / f"batch_{batch_index:02d}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    file_paths: list[Path] = []
    for group_idx, group in enumerate(groups, start=1):
        output_basename = "documentos" if len(groups) == 1 else f"documentos_{group_idx:02d}"
        outputs = _bundle_group(
            group,
            batch_output_dir=batch_dir / f"group_{group_idx:02d}",
            output_basename=output_basename,
        )
        file_paths.extend(outputs)
    file_paths = _fit_batch_outputs_to_limits(file_paths, output_dir=batch_dir / "final_fit")
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
    )
    return PreparedBatch(
        batch_index=batch_index,
        file_paths=[str(path) for path in file_paths],
        total_size_bytes=total_size,
        source_paths=sorted({src for doc in docs for src in (doc.source_paths or [doc.source_path])}),
        manifest_path=str(manifest_path),
    )


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
        target_total_bytes=REDSARA_AGGRESSIVE_TOTAL_TRIGGER_BYTES,
        output_dir=planner_root / "retighten",
    )
    if _total_size(prepared_docs) > REDSARA_TOTAL_UPLOAD_BYTES:
        prepared_docs = _tighten_documents_to_total(
            prepared_docs,
            target_total_bytes=REDSARA_TOTAL_UPLOAD_BYTES,
            output_dir=planner_root / "retighten_hard",
        )

    manifest_paths: list[str] = []
    try:
        single_batch = _materialize_batch(
            prepared_docs,
            id_recurso=safe_rid,
            batch_index=1,
            output_dir=planner_root / "batches",
        )
        batches = [single_batch]
        manifest_paths.append(single_batch.manifest_path)
        return PreparedUploadPlan(
            id_recurso=rid,
            documents=prepared_docs,
            batches=batches,
            total_input_files=len(normalized),
            manifest_paths=manifest_paths,
            limits={
                "max_attachments": REDSARA_MAX_ATTACHMENTS,
                "hard_total_bytes": REDSARA_TOTAL_UPLOAD_BYTES,
                "hard_file_bytes": REDSARA_PER_FILE_UPLOAD_BYTES,
                "soft_total_bytes": REDSARA_SOFT_TOTAL_TARGET_BYTES,
                "soft_file_bytes": REDSARA_SOFT_FILE_TARGET_BYTES,
                "max_batches": REDSARA_MAX_BATCHES,
            },
        )
    except Exception:
        try:
            followup_batches = _materialize_multi_seat_batches(
                prepared_docs,
                id_recurso=safe_rid,
                output_dir=planner_root / "batches",
            )
        except Exception as followup_error:
            raise ValueError(
                f"REDSARA: no se pudo comprimir ni dividir el envio en hasta {REDSARA_MAX_BATCHES} asientos."
            ) from followup_error

        manifest_paths = [batch.manifest_path for batch in followup_batches]
        return PreparedUploadPlan(
            id_recurso=rid,
            documents=prepared_docs,
            batches=followup_batches,
            total_input_files=len(normalized),
            manifest_paths=manifest_paths,
            limits={
                "max_attachments": REDSARA_MAX_ATTACHMENTS,
                "hard_total_bytes": REDSARA_TOTAL_UPLOAD_BYTES,
                "hard_file_bytes": REDSARA_PER_FILE_UPLOAD_BYTES,
                "soft_total_bytes": REDSARA_SOFT_TOTAL_TARGET_BYTES,
                "soft_file_bytes": REDSARA_SOFT_FILE_TARGET_BYTES,
                "max_batches": REDSARA_MAX_BATCHES,
            },
        )
