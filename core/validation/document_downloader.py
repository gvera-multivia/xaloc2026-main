import aiohttp
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from core.config_manager import config_manager

logger = logging.getLogger("worker")

@dataclass
class DownloadResult:
    success: bool
    local_path: Optional[Path] = None
    error: Optional[str] = None

class DocumentDownloader:
    def __init__(self, url_template: str, download_dir: Optional[Path] = None):
        self.url_template = url_template
        if download_dir is None:
            download_dir = Path(config_manager.paths.get("downloads", "tmp/downloads"))
        self.download_dir = download_dir
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def build_url(self, id_recurso: str) -> str:
        """Construye la URL usando el idRecurso."""
        return self.url_template.format(idRecurso=id_recurso)

    async def download(
        self,
        id_recurso: str,
        filename: Optional[str] = None,
        session: Optional[aiohttp.ClientSession] = None
    ) -> DownloadResult:
        url = self.build_url(id_recurso)
        dest_filename = filename or f"{id_recurso}.pdf"
        dest_path = self.download_dir / dest_filename

        logger.info(f"Descargando documento desde: {url}")
        owns_session = session is None
        if session is None:
            session = aiohttp.ClientSession()

        try:
            timeout = config_manager.timeouts.get("general", 30)
            async with session.get(url, timeout=timeout) as response:
                if response.status == 200:
                    content = await response.read()
                    
                    # Validacion basica de PDF
                    if not content.startswith(b"%PDF-"):
                        return DownloadResult(False, error="El archivo descargado no parece un PDF valido")

                    with open(dest_path, "wb") as f:
                        f.write(content)
                    
                    logger.info(f"Documento guardado en: {dest_path}")
                    return DownloadResult(True, local_path=dest_path)
                return DownloadResult(False, error=f"Error HTTP {response.status} al descargar")
        except Exception as e:
            logger.error(f"Error en la descarga: {e}")
            return DownloadResult(False, error=str(e))
        finally:
            if owns_session and session is not None:
                await session.close()
