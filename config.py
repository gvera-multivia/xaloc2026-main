"""
Configuración del proyecto Xaloc Automation
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List


@dataclass
class ConfigNavegador:
    """Configuración del navegador Playwright"""
    headless: bool = False
    perfil_path: Path = Path("profiles/edge_xaloc")
    canal: str = "msedge"
    # Common Name del certificado digital (dejar vacío para selección manual)
   
    certificado_cn: str = os.getenv("certificado_cn", "")
    args: List[str] = field(default_factory=lambda: [
        "--start-maximized",
        "--disable-blink-features=AutomationControlled"
    ])


@dataclass
class Timeouts:
    """Tiempos de espera en milisegundos - STA es lento"""
    general: int = 30000
    login: int = 60000          # VÀLid + certificado
    transicion: int = 30000     # Entre pantallas STA
    subida_archivo: int = 60000


@dataclass
class DatosMulta:
    """Datos específicos del trámite de multas"""
    email: str
    num_denuncia: str
    matricula: str
    num_expediente: str
    motivos: str
    archivo_adjunto: Optional[Path] = None


@dataclass
class Config:
    """Configuración principal del proyecto"""
    navegador: ConfigNavegador = field(default_factory=ConfigNavegador)
    timeouts: Timeouts = field(default_factory=Timeouts)
    
    # URLs
    url_base: str = "https://www.xalocgirona.cat/seu-electronica?view=tramits&id=11"
    
    # Directorios
    dir_screenshots: Path = Path("screenshots")
    dir_logs: Path = Path("logs")
    dir_auth: Path = Path("auth")                   # Directorio para estado de autenticación
    auth_state_path: Path = Path("auth/auth_state.json") # Archivo de estado
    
    def __post_init__(self):
        """Crear directorios si no existen"""
        self.dir_screenshots.mkdir(exist_ok=True)
        self.dir_logs.mkdir(exist_ok=True)
        self.dir_auth.mkdir(exist_ok=True)          # Crear directorio auth
        self.navegador.perfil_path.mkdir(parents=True, exist_ok=True)
