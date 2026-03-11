"""Flow modules for this site."""

from .login import run_login
from .formulario import run_formulario
from .documentos import run_documentos
from .confirmacion import run_confirmacion

__all__ = ["run_login", "run_formulario", "run_documentos", "run_confirmacion"]
