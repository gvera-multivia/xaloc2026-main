"""Flow modules for this site."""

from .login import run_login
from .formulario import run_formulario
from .documentos import run_documentos
from .confirmacion import run_confirmacion
from .presentmul_pas2 import run_presentmul_pas2

__all__ = ["run_login", "run_formulario", "run_documentos", "run_confirmacion", "run_presentmul_pas2"]
