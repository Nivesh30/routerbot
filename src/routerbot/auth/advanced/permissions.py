"""Fine-grained permission system with custom permission sets.

Extends RBAC roles with named permission sets that support inheritance.
Allows creating custom permission groupings like::

    permission_sets:
      - name: "ml-engineer"
        permissions: ["llm:access", "models:read", "models:create"]
        inherit_from: ["viewer"]
      - name: "data-reader"
        permissions: ["llm:access"]
"""

from __future__ import annotations

import logging
from typing import Any

from routerbot.auth.advanced.models import PermissionCheckResult, PermissionSet

logger = logging.getLogger(__name__)


class PermissionManager:
    """Manages custom fine-grained permission sets.

    Parameters
    ----------
    permission_sets:
        Initial list of permission set definitions.
    """

    def __init__(self, permission_sets: list[PermissionSet] | None = None) -> None:
        self._sets: dict[str, PermissionSet] = {}
        if permission_sets:
            for ps in permission_sets:
                self._sets[ps.name] = ps

    def register(self, permission_set: PermissionSet) -> None:
        """Register or update a permission set."""
        self._sets[permission_set.name] = permission_set
        logger.info("Registered permission set: %s", permission_set.name)

    def remove(self, name: str) -> None:
        """Remove a permission set."""
        self._sets.pop(name, None)

    def get(self, name: str) -> PermissionSet | None:
        """Retrieve a permission set by name."""
        return self._sets.get(name)

    def resolve_permissions(self, set_name: str, visited: set[str] | None = None) -> set[str]:
        """Resolve all permissions for a set, including inherited ones.

        Handles circular inheritance by tracking visited sets.

        Parameters
        ----------
        set_name:
            The permission set to resolve.
        visited:
            Set of already-visited names to prevent cycles.

        Returns
        -------
        set[str]
            All resolved permission strings.
        """
        if visited is None:
            visited = set()

        if set_name in visited:
            logger.warning("Circular permission inheritance detected: %s", set_name)
            return set()

        visited.add(set_name)

        ps = self._sets.get(set_name)
        if ps is None:
            return set()

        permissions = set(ps.permissions)

        # Recursively resolve inherited permissions
        for parent_name in ps.inherit_from:
            permissions |= self.resolve_permissions(parent_name, visited)

        return permissions

    def check_permission(
        self,
        permission: str,
        user_sets: list[str],
    ) -> PermissionCheckResult:
        """Check if a permission is granted by any of the user's permission sets.

        Parameters
        ----------
        permission:
            The permission string to check (e.g. ``"models:create"``).
        user_sets:
            List of permission set names assigned to the user.

        Returns
        -------
        PermissionCheckResult
            Result indicating whether the permission is granted.
        """
        checked: list[str] = []
        for set_name in user_sets:
            checked.append(set_name)
            resolved = self.resolve_permissions(set_name)
            if permission in resolved:
                return PermissionCheckResult(
                    allowed=True,
                    permission=permission,
                    checked_sets=checked,
                )

        return PermissionCheckResult(
            allowed=False,
            permission=permission,
            reason=f"Permission {permission!r} not found in any assigned set",
            checked_sets=checked,
        )

    def check_any_permission(
        self,
        permissions: list[str],
        user_sets: list[str],
    ) -> PermissionCheckResult:
        """Check if any of the permissions are granted."""
        for perm in permissions:
            result = self.check_permission(perm, user_sets)
            if result.allowed:
                return result
        return PermissionCheckResult(
            allowed=False,
            permission=",".join(permissions),
            reason="None of the requested permissions are granted",
            checked_sets=user_sets,
        )

    def check_all_permissions(
        self,
        permissions: list[str],
        user_sets: list[str],
    ) -> PermissionCheckResult:
        """Check if all of the permissions are granted."""
        for perm in permissions:
            result = self.check_permission(perm, user_sets)
            if not result.allowed:
                return result
        return PermissionCheckResult(
            allowed=True,
            permission=",".join(permissions),
            checked_sets=user_sets,
        )

    def list_sets(self) -> list[str]:
        """Return all registered set names."""
        return list(self._sets.keys())

    def summary(self) -> dict[str, Any]:
        """Return a summary of the permission system."""
        return {
            "total_sets": len(self._sets),
            "sets": {
                name: {
                    "permissions": len(ps.permissions),
                    "inherits_from": ps.inherit_from,
                }
                for name, ps in self._sets.items()
            },
        }
