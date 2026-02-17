"""
Errores específicos del orquestador/flows para controlar el flujo.
"""

from __future__ import annotations


class RestartRequiredError(RuntimeError):
    """
    Señala que el navegador debe cerrarse por completo y reabrirse,
    reiniciando el flujo desde cero.
    """


class RestartWithProfileResetError(RestartRequiredError):
    """
    Reinicio fuerte: además de reiniciar navegador, se debe limpiar el perfil.
    Útil para casos de sesión corrupta o "trámite en curso" bloqueado.
    """


class RetryWithoutAttemptError(RuntimeError):
    """
    Error recuperable que debe reencolar el job sin consumir intento.
    """

