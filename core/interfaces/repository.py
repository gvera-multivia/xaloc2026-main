from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from core.data.models import Job, Resource

class JobRepository(ABC):
    """
    Abstract interface for Job persistence (SQLite, Redis, Postgres).
    """

    @abstractmethod
    def enqueue(self, job: Job) -> bool:
        """Add job to queue. Returns True if enqueued, False if duplicate."""
        pass

    @abstractmethod
    def reserve_job(self, worker_id: str) -> Optional[Job]:
        """Lock and return the next pending job."""
        pass

    @abstractmethod
    def complete_job(self, job_id: str, result: Dict[str, Any]) -> None:
        """Mark job as successfully completed."""
        pass

    @abstractmethod
    def fail_job(self, job_id: str, error: str, retry: bool = True) -> None:
        """Mark job as failed, optionally rescheduling it."""
        pass

class ResourceRepository(ABC):
    """
    Abstract interface for fetching external resources (SQL Server).
    """

    @abstractmethod
    def fetch_pending_resources(self, site_id: str, limit: int) -> List[Resource]:
        """Get list of resources ready to be processed."""
        pass

    @abstractmethod
    def mark_as_claimed(self, resource_id: int, user: str) -> bool:
        """Mark resource as claimed in the external system."""
        pass
