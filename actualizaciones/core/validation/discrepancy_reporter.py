import webbrowser
from pathlib import Path
from typing import Any, List
from jinja2 import Environment, FileSystemLoader
import logging

logger = logging.getLogger("worker")

class DiscrepancyReporter:
    def __init__(self, template_dir: Path = Path("templates")):
        self.template_dir = template_dir
        self.env = Environment(loader=FileSystemLoader(str(template_dir)))

    def generate_html(
        self, 
        payload: dict[str, Any], 
        errors: List[Any], 
        warnings: List[Any],
        id_exp: str,
        output_path: Path = Path("tmp/discrepancy_report.html")
    ) -> Path:
        """
        Genera un archivo HTML con los datos del payload resaltando los campos erróneos y con advertencias.
        """
        template = self.env.get_template("discrepancy_report.html")
        
        # Convertimos los errores y warnings a mapas para facilitar el resaltado en el HTML
        error_fields = {err.field: err.message for err in errors}
        warning_fields = {warn.field: warn.message for warn in warnings}
        
        html_content = template.render(
            id_exp=id_exp,
            payload=payload,
            error_fields=error_fields,
            warning_fields=warning_fields
        )
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        logger.info(f"Reporte de discrepancia generado en: {output_path}")
        return output_path

    def open_in_browser(self, html_path: Path) -> None:
        """Abre el archivo HTML en el navegador del usuario."""
        logger.info(f"Abriendo reporte en el navegador: {html_path.absolute()}")
        webbrowser.open(f"file://{html_path.absolute()}")
