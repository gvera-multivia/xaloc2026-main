"""
Modelos de datos para el sitio Madrid Ayuntamiento.
Basado en explore-html/llenar formulario-madrid.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class TipoExpediente(Enum):
    """Tipo de formato de referencia del expediente."""
    OPCION1 = "opcion1"  # NNN/EEEEEEEEE.D (ej: 911/102532229.3)
    OPCION2 = "opcion2"  # LLL/AAAA/EEEEEEEEE (ej: MSA/2025/123456789)


class NaturalezaEscrito(Enum):
    """Naturaleza del escrito a presentar."""
    ALEGACION = "A"                # Alegación
    RECURSO = "R"                  # Recurso
    IDENTIFICACION_CONDUCTOR = "I" # Identificación del conductor/a


class TipoDocumento(Enum):
    """Tipo de documento de identidad."""
    NIF = "NIF"
    NIE = "NIE"
    PASAPORTE = "PASAPORTE"


@dataclass
class ExpedienteData:
    """
    Datos de la referencia del expediente.
    Según el tipo, se usan campos diferentes.
    """
    tipo: TipoExpediente = TipoExpediente.OPCION1
    
    # Para opcion1 (NNN/EEEEEEEEE.D)
    nnn: str = ""        # 3 dígitos
    eeeeeeeee: str = ""  # 9 dígitos
    d: str = ""          # 1 dígito
    
    # Para opcion2 (LLL/AAAA/EEEEEEEEE)
    lll: str = ""        # 3 letras
    aaaa: str = ""       # Año (4 dígitos)
    exp_num: str = ""    # 9 dígitos


@dataclass
class DireccionData:
    """Datos de dirección (usado para representante y notificación)."""
    tipo_via: str = ""       # Selector: Calle, Avenida, Plaza, etc.
    nombre_via: str = ""
    tipo_numeracion: str = "" # Selector
    numero: str = ""
    portal: str = ""
    escalera: str = ""
    planta: str = ""
    puerta: str = ""
    codigo_postal: str = ""
    municipio: str = ""
    provincia: str = ""      # Selector
    pais: str = ""     # Selector


@dataclass
class ContactoData:
    """Datos de contacto."""
    email: str = ""
    movil: str = ""
    telefono: str = ""


@dataclass
class IdentificacionData:
    """Datos de identificación de persona/entidad."""
    tipo_documento: TipoDocumento = TipoDocumento.NIF
    numero_documento: str = ""
    nombre: str = ""
    apellido1: str = ""
    apellido2: str = ""
    razon_social: str = ""  # Para personas jurídicas


@dataclass
class NotificacionData:
    """Datos a efectos de notificación (sección 5 del formulario)."""
    # Copiar desde interesado o representante
    copiar_desde: str = ""  # "interesado" o "representante" o vacío
    
    # Identificación
    identificacion: IdentificacionData = field(default_factory=IdentificacionData)
    
    # Dirección
    direccion: DireccionData = field(default_factory=DireccionData)
    
    # Contacto
    contacto: ContactoData = field(default_factory=ContactoData)


@dataclass
class RepresentanteData:
    """Datos del representante (sección 4 del formulario)."""
    # Dirección (los campos de identificación vienen pre-rellenados)
    direccion: DireccionData = field(default_factory=DireccionData)
    
    # Contacto
    contacto: ContactoData = field(default_factory=ContactoData)


@dataclass
class InteresadoData:
    """Datos del interesado (sección 3 del formulario)."""
    # Teléfono (campo editable)
    telefono: str = ""
    
    # Checkboxes de confirmación
    confirmar_email: bool = False
    confirmar_sms: bool = False


@dataclass
class MadridFormData:
    """
    Datos completos del formulario de Madrid.
    Basado en explore-html/llenar formulario-madrid.md
    """
    # Sección 1: Datos del expediente
    expediente: ExpedienteData = field(default_factory=ExpedienteData)
    
    # Sección 2: Matrícula del vehículo
    matricula: str = ""
    
    # Sección 3: Datos del interesado
    interesado: InteresadoData = field(default_factory=InteresadoData)
    
    # Sección 4: Datos del representante
    representante: RepresentanteData = field(default_factory=RepresentanteData)
    
    # Sección 5: Datos de notificación
    notificacion: NotificacionData = field(default_factory=NotificacionData)
    
    # Sección 6: Naturaleza del escrito
    naturaleza: NaturalezaEscrito = NaturalezaEscrito.ALEGACION
    
    # Sección 7: Expone y Solicita
    expone: str = ""
    solicita: str = ""


@dataclass
class MadridTarget:
    """
    Contenedor principal de datos para la automatización de Madrid.
    Similar a BaseOnlineTarget.
    """
    # ID del recurso (para nombrar archivos de verificación)
    idRecurso: Optional[int] = None
    
    # Datos del formulario
    form_data: MadridFormData = field(default_factory=MadridFormData)
    
    # Archivos adjuntos (para la pantalla posterior)
    archivos_adjuntos: list[Path] = field(default_factory=list)

    # Payload crudo original (para lógica de paths y notificaciones)
    payload: dict = field(default_factory=dict)
    
    # Metadatos de ejecución
    headless: bool = True
