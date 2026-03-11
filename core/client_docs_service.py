from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.client_documentation import (
    check_requires_gesdoc,
    build_required_client_documents_for_payload,
)


async def get_required_client_documents(
    payload: dict,
    *,
    gesdoc_user: Optional[str] = None,
    gesdoc_pwd: Optional[str] = None,
    sqlserver_conn_str: Optional[str] = None,
    strict: bool = True,
    merge_if_multiple: bool = False,
    pdftk_path: str | Path = r"C:\Program Files (x86)\PDFtk\bin\pdftk.exe",
    output_dir: Path = Path("tmp/client_docs"),
    output_label: str = "client",
) -> list[Path]:
    return await build_required_client_documents_for_payload(
        payload=payload,
        gesdoc_user=gesdoc_user,
        gesdoc_pwd=gesdoc_pwd,
        sqlserver_conn_str=sqlserver_conn_str,
        strict=strict,
        merge_if_multiple=merge_if_multiple,
        pdftk_path=pdftk_path,
        output_dir=output_dir,
        output_label=output_label,
    )


def requires_gesdoc_authorization(payload: dict, *, base_path: str | None = None) -> tuple[bool, str | None]:
    return check_requires_gesdoc(payload=payload, base_path=base_path)

