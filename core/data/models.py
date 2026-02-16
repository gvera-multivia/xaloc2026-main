from __future__ import annotations
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field

class JobState(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD = "dead"

class Mandatario(BaseModel):
    tipo_persona: str  # JURIDICA | FISICA
    razon_social: Optional[str] = None
    cif_documento: Optional[str] = None
    cif_control: Optional[str] = None
    tipo_doc: Optional[str] = None
    doc_numero: Optional[str] = None
    doc_control: Optional[str] = None
    nombre: Optional[str] = None
    apellido1: Optional[str] = None
    apellido2: Optional[str] = None

class Resource(BaseModel):
    """
    Represents a resource fetched from SQL Server or another source.
    """
    id_recurso: int = Field(alias="idRecurso")
    id_exp: Optional[float] = Field(None, alias="idExp")
    expediente: str
    fase_procedimiento: str
    sujeto_recurso: str

    # Raw payload for flexibility until all sites are fully typed
    raw_data: Dict[str, Any] = Field(default_factory=dict)

class TaskPayload(BaseModel):
    """
    Standardized payload for execution.
    """
    job_id: str
    site_id: str
    protocol: Optional[str] = None
    resource_id: Optional[int] = Field(None, alias="idRecurso")
    expediente: str

    # Contact & Vehicle
    user_email: str
    plate_number: Optional[str] = None

    # Legal
    motivos: str
    mandatario: Optional[Mandatario] = None

    # Attachments
    adjuntos: List[Dict[str, Any]] = Field(default_factory=list)
    archivos: List[str] = Field(default_factory=list) # Paths to files

    # Flags
    disable_gesdoc: bool = False
    skip_auto_complete: bool = False

    # Extra dynamic fields
    extra: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        extra = "allow" # Allow extra fields from legacy payloads

class Job(BaseModel):
    """
    Represents a job in the queue (State Machine).
    """
    job_id: str
    site_id: str
    state: JobState = JobState.CREATED
    payload: TaskPayload
    attempt: int = 0
    max_attempts: int = 3
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    worker_id: Optional[str] = None
    error_message: Optional[str] = None
