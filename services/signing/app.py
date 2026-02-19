from __future__ import annotations

import base64
import hashlib
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("signing-service")
app = FastAPI(title="signing-service", version="0.1.0")


class SignRequest(BaseModel):
    operation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    payload_b64: str
    algorithm: str = "sha256"
    trace_id: Optional[str] = None


class SignResponse(BaseModel):
    operation_id: str
    algorithm: str
    signature_b64: str
    cert_path: str
    trace_id: Optional[str] = None


def _load_cert_bytes() -> tuple[Path, bytes]:
    cert_path = Path((os.getenv("SIGNING_CERT_PATH") or "/data/certificates/certificate.pfx").strip())
    if not cert_path.exists():
        raise FileNotFoundError(f"Certificado no encontrado en {cert_path}")
    return cert_path, cert_path.read_bytes()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/sign", response_model=SignResponse)
def sign(req: SignRequest) -> SignResponse:
    try:
        cert_path, cert_bytes = _load_cert_bytes()
        payload_bytes = base64.b64decode(req.payload_b64.encode("utf-8"))
        algorithm = req.algorithm.lower()
        if algorithm not in {"sha256"}:
            raise ValueError(f"Algoritmo no soportado: {algorithm}")
        digest = hashlib.sha256(cert_bytes + payload_bytes).digest()
        signature_b64 = base64.b64encode(digest).decode("utf-8")
        logger.info(
            "Operacion firma registrada operation_id=%s trace_id=%s cert=%s",
            req.operation_id,
            req.trace_id,
            cert_path,
        )
        return SignResponse(
            operation_id=req.operation_id,
            algorithm=algorithm,
            signature_b64=signature_b64,
            cert_path=str(cert_path),
            trace_id=req.trace_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
