from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import aiohttp
import asyncio
import re

@dataclass
class AttachmentInfo:
    """Información de un adjunto a descargar."""
    id: str
    filename: str
    url: str

@dataclass
class AttachmentDownloadResult:
    """Resultado de descarga de un adjunto."""
    success: bool
    attachment_id: str
    filename: str
    local_path: Optional[Path]
    error: Optional[str]
    file_size_bytes: int = 0

class AttachmentDownloader:
    """
    Descargador de adjuntos desde el servidor XVIA.

    Características:
    - Descarga paralela de múltiples adjuntos
    - Validación de archivos descargados
    - Gestión de timeouts y reintentos
    - Almacenamiento organizado por idRecurso
    """

    URL_TEMPLATE = "http://www.xvia-grupoeuropa.net/intranet/xvia-grupoeuropa/public/servicio/recursos/expedientes/pdf-adjuntos/{id}"

    def __init__(
        self,
        download_dir: Path = Path("tmp/downloads/adjuntos"),
        timeout_seconds: int = 30,
        max_retries: int = 3,
        max_concurrent: int = 5
    ):
        self.download_dir = download_dir
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.max_retries = max_retries
        self.max_concurrent = max_concurrent
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def build_url(self, attachment_id: str) -> str:
        """Construye URL de descarga para un adjunto."""
        return self.URL_TEMPLATE.format(id=attachment_id)

    async def download_single(
        self,
        attachment: AttachmentInfo,
        id_recurso: str
    ) -> AttachmentDownloadResult:
        """
        Descarga un único adjunto.

        Args:
            attachment: Información del adjunto
            id_recurso: ID del recurso (para organizar en carpetas)

        Returns:
            Resultado de la descarga
        """
        # Crear subcarpeta por idRecurso
        recurso_dir = self.download_dir / id_recurso
        recurso_dir.mkdir(parents=True, exist_ok=True)

        # Sanitizar nombre de archivo
        safe_filename = self._sanitize_filename(attachment.filename)
        local_path = recurso_dir / safe_filename

        for attempt in range(1, self.max_retries + 1):
            try:
                async with aiohttp.ClientSession(timeout=self.timeout) as session:
                    async with session.get(attachment.url) as response:
                        if response.status != 200:
                            raise Exception(f"HTTP {response.status}")

                        content = await response.read()

                        # Validar que no esté vacío
                        if len(content) == 0:
                            raise Exception("Archivo vacío")

                        # Guardar archivo
                        local_path.write_bytes(content)

                        return AttachmentDownloadResult(
                            success=True,
                            attachment_id=attachment.id,
                            filename=attachment.filename,
                            local_path=local_path,
                            error=None,
                            file_size_bytes=len(content)
                        )

            except Exception as e:
                if attempt == self.max_retries:
                    return AttachmentDownloadResult(
                        success=False,
                        attachment_id=attachment.id,
                        filename=attachment.filename,
                        local_path=None,
                        error=f"Fallo tras {self.max_retries} intentos: {str(e)}"
                    )
                await asyncio.sleep(2 ** attempt)  # Backoff exponencial

        # Should not reach here
        return AttachmentDownloadResult(
            success=False,
            attachment_id=attachment.id,
            filename=attachment.filename,
            local_path=None,
            error="Unexpected error loop termination"
        )

    async def download_batch(
        self,
        attachments: list[AttachmentInfo],
        id_recurso: str
    ) -> list[AttachmentDownloadResult]:
        """
        Descarga múltiples adjuntos en paralelo (con límite de concurrencia).

        Args:
            attachments: Lista de adjuntos a descargar
            id_recurso: ID del recurso

        Returns:
            Lista de resultados de descarga
        """
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def download_with_semaphore(att: AttachmentInfo):
            async with semaphore:
                return await self.download_single(att, id_recurso)

        tasks = [download_with_semaphore(att) for att in attachments]
        return await asyncio.gather(*tasks)

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Sanitiza nombre de archivo para evitar problemas de sistema."""
        # Eliminar caracteres no permitidos
        safe = re.sub(r'[<>:"/\\|?*]', '_', filename)
        # Limitar longitud
        if len(safe) > 200:
            name, ext = safe.rsplit('.', 1) if '.' in safe else (safe, '')
            safe = name[:200 - len(ext) - 1] + '.' + ext if ext else name[:200]
        return safe
