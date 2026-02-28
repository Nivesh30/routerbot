"""API key scoping - per-endpoint, per-model restrictions.

Validates incoming requests against the scope restrictions attached
to an API key, including endpoint patterns, allowed models, HTTP
methods, rate limits, and expiration.
"""

from __future__ import annotations

import fnmatch
import logging
from datetime import UTC, datetime

from routerbot.auth.advanced.models import KeyScope, KeyScopeValidation

UTC = UTC
logger = logging.getLogger(__name__)


class KeyScopeValidator:
    """Validates requests against API key scopes.

    Parameters
    ----------
    scopes:
        Named scope definitions keyed by scope name.
    """

    def __init__(self, scopes: dict[str, KeyScope] | None = None) -> None:
        self._scopes = scopes or {}

    def register_scope(self, name: str, scope: KeyScope) -> None:
        """Register or update a named scope."""
        self._scopes[name] = scope
        logger.info("Registered key scope: %s", name)

    def remove_scope(self, name: str) -> None:
        """Remove a named scope."""
        self._scopes.pop(name, None)

    def get_scope(self, name: str) -> KeyScope | None:
        """Retrieve a scope by name."""
        return self._scopes.get(name)

    def validate(
        self,
        scope_name: str,
        endpoint: str = "",
        model: str = "",
        method: str = "",
        key_id: str = "",
    ) -> KeyScopeValidation:
        """Validate a request against a named scope.

        Parameters
        ----------
        scope_name:
            The scope name attached to the API key.
        endpoint:
            The request URL path (e.g. ``/v1/chat/completions``).
        model:
            The requested model name (e.g. ``openai/gpt-4o``).
        method:
            The HTTP method (e.g. ``POST``).
        key_id:
            The API key identifier (for logging).

        Returns
        -------
        KeyScopeValidation
            Result indicating whether the request is allowed.
        """
        scope = self._scopes.get(scope_name)
        if scope is None:
            return KeyScopeValidation(
                allowed=False,
                reason=f"Unknown scope: {scope_name}",
                key_id=key_id,
            )

        # Check expiration
        if scope.expires_at:
            now = datetime.now(tz=UTC)
            if now > scope.expires_at:
                return KeyScopeValidation(
                    allowed=False,
                    reason="Key scope has expired",
                    key_id=key_id,
                    matched_scope=scope,
                )

        # Check allowed endpoints
        if scope.allowed_endpoints and endpoint and not any(
            fnmatch.fnmatch(endpoint, pattern) for pattern in scope.allowed_endpoints
        ):
                return KeyScopeValidation(
                    allowed=False,
                    reason=f"Endpoint {endpoint!r} not allowed by scope",
                    key_id=key_id,
                    matched_scope=scope,
                )

        # Check allowed models
        if scope.allowed_models and model and not any(
            fnmatch.fnmatch(model, pattern) for pattern in scope.allowed_models
        ):
                return KeyScopeValidation(
                    allowed=False,
                    reason=f"Model {model!r} not allowed by scope",
                    key_id=key_id,
                    matched_scope=scope,
                )

        # Check allowed methods
        if scope.allowed_methods and method and method.upper() not in [
            m.upper() for m in scope.allowed_methods
        ]:
                return KeyScopeValidation(
                    allowed=False,
                    reason=f"Method {method!r} not allowed by scope",
                    key_id=key_id,
                    matched_scope=scope,
                )

        return KeyScopeValidation(
            allowed=True,
            key_id=key_id,
            matched_scope=scope,
        )

    def list_scopes(self) -> list[str]:
        """Return all registered scope names."""
        return list(self._scopes.keys())

    def summary(self) -> dict[str, int]:
        """Return summary of registered scopes."""
        return {
            "total": len(self._scopes),
            "with_endpoint_restrictions": sum(
                1 for s in self._scopes.values() if s.allowed_endpoints
            ),
            "with_model_restrictions": sum(
                1 for s in self._scopes.values() if s.allowed_models
            ),
            "with_expiration": sum(
                1 for s in self._scopes.values() if s.expires_at
            ),
        }
