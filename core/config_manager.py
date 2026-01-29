"""
Módulo para la gestión centralizada de la configuración del organismo.
Carga la configuración desde la base de datos (y opcionalmente desde JSON si la DB está vacía).
"""
import logging
from typing import Any, Dict, Optional
from core.sqlite_db import SQLiteDatabase

logger = logging.getLogger("config_manager")

class ConfigManager:
    _instance = None
    _config = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self):
        try:
            db = SQLiteDatabase()
            config = db.get_organismo_config()
            if config:
                self._config = config
                logger.info("Configuración cargada desde DB.")
            else:
                logger.warning("No se encontró configuración en DB. Usando valores por defecto limitados o vacíos.")
                self._config = {}
        except Exception as e:
            logger.error(f"Error cargando configuración: {e}")
            self._config = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    @property
    def login_url(self) -> str:
        return self.get("login_url", "")

    @property
    def document_url_template(self) -> str:
        return self.get("document_url_template", "")

    @property
    def attachment_url_template(self) -> str:
        return self.get("attachment_url_template", "")

    @property
    def http_headers(self) -> Dict[str, str]:
        return self.get("http_headers", {})

    @property
    def timeouts(self) -> Dict[str, int]:
        return self.get("timeouts", {})

    @property
    def paths(self) -> Dict[str, str]:
        return self.get("paths", {})

    @property
    def selectors(self) -> Dict[str, str]:
        return self.get("selectors", {})

    def reload(self):
        """Recarga la configuración desde la DB."""
        self._load_config()

# Instancia global para uso fácil
config_manager = ConfigManager()
