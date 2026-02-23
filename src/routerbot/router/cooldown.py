"""Cooldown management for the RouterBot router.

Tracks deployment failure counts and temporarily marks failing deployments
as unavailable once the failure threshold is exceeded.
"""

from __future__ import annotations

import logging
import time
from threading import Lock

logger = logging.getLogger(__name__)


class CooldownManager:
    """Per-deployment cooldown tracker stored in memory.

    Thread-safe implementation using a simple lock. In a multi-process
    deployment, this will be replaced by a Redis-backed implementation
    in Stage 4.

    Parameters
    ----------
    allowed_fails:
        Number of consecutive failures before entering cooldown.
    cooldown_seconds:
        Duration in seconds to keep a deployment in cooldown.
    """

    def __init__(
        self,
        allowed_fails: int = 3,
        cooldown_seconds: int = 60,
    ) -> None:
        self.allowed_fails = allowed_fails
        self.cooldown_seconds = cooldown_seconds
        self._failures: dict[str, int] = {}
        self._cooldown_until: dict[str, float] = {}
        self._lock = Lock()

    def record_success(self, deployment_id: str) -> None:
        """Reset the failure counter for a deployment on success."""
        with self._lock:
            self._failures.pop(deployment_id, None)
            self._cooldown_until.pop(deployment_id, None)

    def record_failure(self, deployment_id: str) -> None:
        """Increment the failure counter; enter cooldown if threshold exceeded."""
        with self._lock:
            self._failures[deployment_id] = self._failures.get(deployment_id, 0) + 1
            if self._failures[deployment_id] >= self.allowed_fails:
                cooldown_until = time.monotonic() + self.cooldown_seconds
                self._cooldown_until[deployment_id] = cooldown_until
                logger.warning(
                    "Deployment %r entered cooldown for %ds (fail #%d)",
                    deployment_id,
                    self.cooldown_seconds,
                    self._failures[deployment_id],
                )

    def is_in_cooldown(self, deployment_id: str) -> bool:
        """Return True if the deployment is currently in cooldown."""
        with self._lock:
            until = self._cooldown_until.get(deployment_id)
            if until is None:
                return False
            if time.monotonic() < until:
                return True
            # Cooldown expired — clear it
            self._cooldown_until.pop(deployment_id, None)
            self._failures.pop(deployment_id, None)
            logger.info("Deployment %r cooldown expired, restoring", deployment_id)
            return False

    def failure_count(self, deployment_id: str) -> int:
        """Return the current failure count for a deployment."""
        with self._lock:
            return self._failures.get(deployment_id, 0)

    def reset(self, deployment_id: str) -> None:
        """Manually reset cooldown state for a deployment."""
        with self._lock:
            self._failures.pop(deployment_id, None)
            self._cooldown_until.pop(deployment_id, None)

    def all_in_cooldown(self) -> list[str]:
        """Return a list of currently cooling deployment IDs."""
        now = time.monotonic()
        with self._lock:
            return [did for did, until in self._cooldown_until.items() if now < until]
