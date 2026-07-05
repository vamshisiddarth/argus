from __future__ import annotations

from abc import ABC, abstractmethod

from core.remediation.models import ChangeProposal


class ChangeTracker(ABC):
    """
    Integration-agnostic interface for tracking change proposals.

    v1 implementation: JiraTracker (creates tickets, deduplicates via labels).
    Future: ServiceNow, Linear, GitHub Issues — same interface, swap the class.
    """

    @abstractmethod
    def create(self, proposal: ChangeProposal) -> str:
        """
        Record a change proposal and return its URL.

        Implementations must:
        - Be idempotent: same proposal on a second call returns the existing URL
        - Update the existing record if the analysis has meaningfully changed
        - Never raise on transient errors — log and re-raise as TrackerError
        """

    @abstractmethod
    def close(self, url: str, reason: str) -> None:
        """Mark a tracked item as resolved (used when a resource is gone)."""


class TrackerError(Exception):
    """Raised when a tracker operation fails after retries."""
