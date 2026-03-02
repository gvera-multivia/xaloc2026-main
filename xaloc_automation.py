"""
Compatibilidad: `from xaloc_automation import XalocAsync`.

El orquestador real vive en `sites/xaloc_girona/automation.py`.
"""

from sites.xaloc_girona.automation import XalocGironaAutomation as XalocAsync

__all__ = ["XalocAsync"]

