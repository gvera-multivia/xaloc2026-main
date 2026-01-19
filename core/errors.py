"""
Errores específicos del orquestador/flows para controlar el flujo.
"""

from __future__ import annotations


class RestartRequiredError(RuntimeError):
    """
    Señala que el navegador debe cerrarse por completo y reabrirse,
    reiniciando el flujo desde cero.
    """

