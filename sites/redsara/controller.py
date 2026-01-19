from __future__ import annotations
from pathlib import Path
from .config import RedSaraConfig
from .data_models import DatosRepresentante, DatosDireccion, DatosPresentador, DatosInteresado, ArchivoAdjunto

class RedSaraController:
    site_id = "redsara"
    display_name = "RedSARA"

    def create_config(self, *, headless: bool = False, **kwargs) -> RedSaraConfig:
        config = RedSaraConfig()
        config.navegador.headless = bool(headless)
        return config

    def map_data(self, data: dict) -> dict:
        """
        Mapea claves genéricas de DB a argumentos de create_target.
        """
        return {
            "datos_representante": data.get("representante"),
            "datos_presentador": data.get("presentador"),
            "datos_interesado": data.get("interesado"),
            "archivos": data.get("archivos"),
            "asunto": data.get("asunto"),
            "expone": data.get("expone"),
            "solicita": data.get("solicita"),
            "organismo": data.get("organismo")
        }

    def create_target(self, **kwargs) -> tuple:
        """
        Crea los datos objetivo para la automatización.
        Si no se pasan argumentos, devuelve datos de demo.
        """
        # Si se pasan datos de representante, usarlos
        if kwargs.get("datos_representante"):
            return (
                kwargs["datos_representante"],
                kwargs.get("datos_presentador", DatosPresentador(igual_que_representante=True)),
                kwargs.get("datos_interesado"),
                kwargs.get("archivos", [])
            )
        
        # Si no hay datos, devolver demo
        return self.create_demo_data()

    def create_demo_data(self) -> tuple:
        """Datos de ejemplo para pruebas rápidas"""
        dir_postal = DatosDireccion(
            tipo_via="Ronda",
            direccion="General Mitre, 169",
            provincia="Barcelona",
            ciudad="Barcelona",
            codigo_postal="08003"
        )
        
        repre = DatosRepresentante(
            nif="12345678X",
            nombre="Juan",
            apellido="García López",
            email="juan@example.com",
            telefono="666123456",
            direccion=dir_postal,
            es_representante=True
        )

        interesado = DatosInteresado(
            nombre="Maria",
            apellido="Perez",
            segundo_apellido="Garcia",
            nif="87654321Z",
            tipo_documento="NIF",
            direccion=dir_postal,
            email="maria@example.com",
            telefono="666999888"
        )
        
        presen = DatosPresentador(igual_que_representante=True)
        
        archivos = [
            ArchivoAdjunto(ruta=Path("pdfs-prueba/test1.pdf"), descripcion="Documento de prueba")
        ]
        
        return (repre, presen, interesado, archivos)

def get_controller() -> RedSaraController:
    return RedSaraController()

__all__ = ["RedSaraController", "get_controller"]
