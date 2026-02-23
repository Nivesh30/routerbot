"""Router health checker.

Runs periodic background health checks against registered deployments.
A deployment that fails a health probe records a failure in the
:class:`~routerbot.router.cooldown.CooldownManager` so the router can
skip it until it recovers.

The health check sends a minimal ``/chat/completions`` request
(``max_tokens=1``) and marks the deployment healthy or unhealthy based
on whether the provider responds without raising an exception.

Usage::

    checker = HealthChecker(router, interval=300)
    await checker.start()   # starts the background loop
    ...
    await checker.stop()    # cancels the background loop
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from routerbot.router.router import Deployment, Router

logger = logging.getLogger(__name__)


class HealthChecker:
    """Periodically probe all deployments registered in a :class:`Router`.

    Parameters
    ----------
    router:
        The :class:`Router` instance whose deployments will be checked.
    interval:
        How often (in seconds) to run the health-check loop.  Defaults
        to 300 s (5 minutes).
    timeout:
        Per-deployment probe timeout in seconds.  Defaults to 10 s.
    """

    def __init__(
        self,
        router: Router,
        interval: int = 300,
        timeout: float = 10.0,
    ) -> None:
        self._router = router
        self._interval = interval
        self._timeout = timeout
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the health-check background task."""
        if self._task is not None and not self._task.done():
            logger.debug("HealthChecker already running — ignoring start()")
            return
        self._task = asyncio.create_task(self._check_loop(), name="routerbot-health-check")
        logger.info(
            "HealthChecker started (interval=%ds, timeout=%.1fs)",
            self._interval,
            self._timeout,
        )

    async def stop(self) -> None:
        """Cancel the health-check background task and wait for it to finish."""
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
        logger.info("HealthChecker stopped")

    @property
    def is_running(self) -> bool:
        """``True`` if the background task is alive."""
        return self._task is not None and not self._task.done()

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _check_loop(self) -> None:
        """Run health checks at the configured interval forever."""
        while True:
            try:
                await self._run_checks()
            except Exception:
                logger.exception("Unexpected error in health-check loop — continuing")
            await asyncio.sleep(self._interval)

    async def _run_checks(self) -> None:
        """Probe every deployment once."""
        all_deployments: list[Deployment] = []
        for deps in self._router._deployments.values():
            all_deployments.extend(deps)

        if not all_deployments:
            logger.debug("HealthChecker: no deployments to check")
            return

        tasks = [asyncio.create_task(self._check_deployment(dep), name=f"health-{dep.name}") for dep in all_deployments]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for dep, result in zip(all_deployments, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning("Health check for %r raised: %s", dep.name, result)

    async def _check_deployment(self, deployment: Deployment) -> bool:
        """Send a minimal probe to *deployment*.

        Returns ``True`` if the deployment responded successfully,
        ``False`` otherwise.  Also updates the cooldown manager.
        """
        from routerbot.core.enums import Role
        from routerbot.core.exceptions import RouterBotError
        from routerbot.core.types import CompletionRequest, Message

        probe = CompletionRequest(
            model=deployment.provider_model,
            messages=[Message(role=Role.USER, content="hi")],
            max_tokens=1,
        )

        try:
            async with asyncio.timeout(self._timeout):
                provider = self._router._make_provider(deployment)
                await provider.chat_completion(probe)

            self._router._cooldown.record_success(deployment.name)
            logger.debug("Health check OK: %r", deployment.name)
            return True

        except TimeoutError:
            logger.warning("Health check timed out for %r", deployment.name)
            self._router._cooldown.record_failure(deployment.name)
            return False

        except RouterBotError as exc:
            logger.warning("Health check failed for %r: %s", deployment.name, exc)
            self._router._cooldown.record_failure(deployment.name)
            return False

        except Exception as exc:
            logger.warning("Health check unexpected error for %r: %s", deployment.name, exc)
            self._router._cooldown.record_failure(deployment.name)
            return False
