from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from core.data.models import TaskPayload

class SitePlugin(ABC):
    """
    Abstract interface for a Site Automation Plugin.
    Decouples the 'how' (Playwright logic) from the 'what' (Business logic).
    """

    @property
    @abstractmethod
    def site_id(self) -> str:
        """Unique identifier for the site (e.g., 'madrid')."""
        pass

    @abstractmethod
    def validate_payload(self, payload: Dict[str, Any]) -> TaskPayload:
        """
        Validates raw payload and converts it to a typed model.
        Raises ValueError if invalid.
        """
        pass

    @abstractmethod
    async def execute(self, task: TaskPayload, headless: bool = True) -> Dict[str, Any]:
        """
        Executes the automation flow.
        Returns a result dictionary (e.g. {'screenshot_path': ...}).
        Raises exceptions on failure.
        """
        pass
