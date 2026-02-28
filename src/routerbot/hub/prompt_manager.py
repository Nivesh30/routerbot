"""Prompt template management.

Provides CRUD for prompt templates with versioning, variable substitution,
A/B testing, and analytics tracking.
"""

from __future__ import annotations

import logging
import random
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from routerbot.hub.models import (
    HubConfig,
    PromptABTest,
    PromptAnalytics,
    PromptStatus,
    PromptTemplate,
    PromptVariable,
    PromptVersion,
)

logger = logging.getLogger(__name__)

_VARIABLE_RE = re.compile(r"\{\{(\w+)\}\}")


class PromptManager:
    """Manages prompt templates with versioning and A/B testing.

    Parameters
    ----------
    config:
        Hub configuration.
    """

    def __init__(self, config: HubConfig | None = None) -> None:
        self.config = config or HubConfig()
        self._templates: dict[str, PromptTemplate] = {}
        self._versions: dict[str, list[PromptVersion]] = {}  # template_id -> versions
        self._ab_tests: dict[str, PromptABTest] = {}
        self._analytics: dict[str, PromptAnalytics] = {}  # "tid:version" -> analytics

    # -- Template CRUD -------------------------------------------------------

    def create_template(
        self,
        name: str,
        content: str,
        *,
        description: str = "",
        variables: list[PromptVariable] | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PromptTemplate:
        """Create a new prompt template.

        Variables are auto-detected from ``{{var}}`` placeholders if not provided.
        """
        if len(self._templates) >= self.config.max_prompt_templates:
            raise PromptCapacityError(f"Max templates reached: {self.config.max_prompt_templates}")

        template_id = f"pt_{uuid.uuid4().hex[:12]}"
        now = datetime.now(tz=UTC)

        # Auto-detect variables from content
        if variables is None:
            var_names = _VARIABLE_RE.findall(content)
            variables = [PromptVariable(name=v) for v in dict.fromkeys(var_names)]

        template = PromptTemplate(
            template_id=template_id,
            name=name,
            description=description,
            content=content,
            variables=variables,
            version=1,
            status=PromptStatus.DRAFT,
            tags=tags or [],
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        self._templates[template_id] = template

        # Store version 1
        self._versions[template_id] = [
            PromptVersion(
                template_id=template_id,
                version=1,
                content=content,
                variables=variables,
                created_at=now,
            )
        ]

        logger.info("Prompt template %s created: %s", template_id, name)
        return template

    def get_template(self, template_id: str) -> PromptTemplate | None:
        """Get a template by ID."""
        return self._templates.get(template_id)

    def update_template(
        self,
        template_id: str,
        content: str,
        *,
        variables: list[PromptVariable] | None = None,
    ) -> PromptTemplate | None:
        """Create a new version of a template with updated content.

        Returns the updated template or *None* if not found.
        """
        template = self._templates.get(template_id)
        if template is None:
            return None

        # Auto-detect if not provided
        if variables is None:
            var_names = _VARIABLE_RE.findall(content)
            variables = [PromptVariable(name=v) for v in dict.fromkeys(var_names)]

        now = datetime.now(tz=UTC)
        new_version = template.version + 1

        template.content = content
        template.variables = variables
        template.version = new_version
        template.updated_at = now

        self._versions.setdefault(template_id, []).append(
            PromptVersion(
                template_id=template_id,
                version=new_version,
                content=content,
                variables=variables,
                created_at=now,
            )
        )

        logger.info("Prompt %s updated to version %d", template_id, new_version)
        return template

    def delete_template(self, template_id: str) -> bool:
        """Delete a template and all its versions."""
        if self._templates.pop(template_id, None) is None:
            return False
        self._versions.pop(template_id, None)
        # Clean up analytics
        keys_to_remove = [k for k in self._analytics if k.startswith(f"{template_id}:")]
        for k in keys_to_remove:
            del self._analytics[k]
        return True

    def list_templates(
        self,
        *,
        status: PromptStatus | None = None,
        tag: str | None = None,
        limit: int = 100,
    ) -> list[PromptTemplate]:
        """List templates with optional filters."""
        templates = list(self._templates.values())
        if status:
            templates = [t for t in templates if t.status == status]
        if tag:
            templates = [t for t in templates if tag in t.tags]
        templates.sort(
            key=lambda t: t.updated_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        return templates[:limit]

    def activate_template(self, template_id: str) -> bool:
        """Set template status to active."""
        template = self._templates.get(template_id)
        if template is None:
            return False
        template.status = PromptStatus.ACTIVE
        template.updated_at = datetime.now(tz=UTC)
        return True

    def archive_template(self, template_id: str) -> bool:
        """Set template status to archived."""
        template = self._templates.get(template_id)
        if template is None:
            return False
        template.status = PromptStatus.ARCHIVED
        template.updated_at = datetime.now(tz=UTC)
        return True

    # -- Versioning ----------------------------------------------------------

    def get_versions(self, template_id: str) -> list[PromptVersion]:
        """Get all versions of a template."""
        return self._versions.get(template_id, [])

    def get_version(self, template_id: str, version: int) -> PromptVersion | None:
        """Get a specific version."""
        for v in self._versions.get(template_id, []):
            if v.version == version:
                return v
        return None

    # -- Rendering -----------------------------------------------------------

    def render(
        self,
        template_id: str,
        variables: dict[str, str] | None = None,
        *,
        version: int | None = None,
    ) -> str:
        """Render a prompt template with variables substituted.

        Parameters
        ----------
        template_id:
            Template to render.
        variables:
            Values for template variables.
        version:
            Specific version to render.  Uses latest if *None*.

        Returns
        -------
        str
            Rendered prompt text.

        Raises
        ------
        PromptRenderError
            If required variables are missing.
        PromptNotFoundError
            If the template/version is not found.
        """
        if version is not None:
            ver = self.get_version(template_id, version)
            if ver is None:
                raise PromptNotFoundError(f"Version {version} of {template_id} not found")
            content = ver.content
            template_vars = ver.variables
        else:
            template = self._templates.get(template_id)
            if template is None:
                raise PromptNotFoundError(f"Template {template_id} not found")
            content = template.content
            template_vars = template.variables

        variables = variables or {}

        # Check required variables
        missing = [v.name for v in template_vars if v.required and v.name not in variables and not v.default_value]
        if missing:
            raise PromptRenderError(f"Missing required variables: {', '.join(missing)}")

        # Build substitution map (explicit > default)
        sub_map: dict[str, str] = {}
        for v in template_vars:
            sub_map[v.name] = variables.get(v.name, v.default_value)

        def _replace(match: re.Match[str]) -> str:
            name = match.group(1)
            return sub_map.get(name, match.group(0))

        return _VARIABLE_RE.sub(_replace, content)

    # -- A/B Testing ---------------------------------------------------------

    def create_ab_test(
        self,
        template_id: str,
        variant_a: int,
        variant_b: int,
        *,
        name: str = "",
        traffic_split: float = 0.5,
    ) -> PromptABTest:
        """Create an A/B test between two versions of a template."""
        template = self._templates.get(template_id)
        if template is None:
            raise PromptNotFoundError(f"Template {template_id} not found")

        test_id = f"ab_{uuid.uuid4().hex[:10]}"
        test = PromptABTest(
            test_id=test_id,
            name=name or f"A/B Test {template_id}",
            template_id=template_id,
            variant_a_version=variant_a,
            variant_b_version=variant_b,
            traffic_split=traffic_split,
            created_at=datetime.now(tz=UTC),
        )
        self._ab_tests[test_id] = test
        logger.info("A/B test %s created for %s (v%d vs v%d)", test_id, template_id, variant_a, variant_b)
        return test

    def pick_ab_variant(self, test_id: str) -> int:
        """Pick a variant for an A/B test request.

        Returns the version number of the selected variant.
        """
        test = self._ab_tests.get(test_id)
        if test is None:
            raise PromptNotFoundError(f"A/B test {test_id} not found")

        test.total_requests += 1
        if random.random() < test.traffic_split:  # noqa: S311
            test.variant_a_requests += 1
            return test.variant_a_version
        test.variant_b_requests += 1
        return test.variant_b_version

    def get_ab_test(self, test_id: str) -> PromptABTest | None:
        """Get an A/B test by ID."""
        return self._ab_tests.get(test_id)

    def list_ab_tests(self, template_id: str | None = None) -> list[PromptABTest]:
        """List A/B tests, optionally filtered by template."""
        tests = list(self._ab_tests.values())
        if template_id:
            tests = [t for t in tests if t.template_id == template_id]
        return tests

    # -- Analytics -----------------------------------------------------------

    def record_usage(
        self,
        template_id: str,
        version: int,
        *,
        latency_ms: float = 0.0,
        cost: float = 0.0,
        tokens: int = 0,
        success: bool = True,
    ) -> None:
        """Record a usage event for analytics."""
        key = f"{template_id}:{version}"
        analytics = self._analytics.get(key)
        if analytics is None:
            analytics = PromptAnalytics(template_id=template_id, version=version)
            self._analytics[key] = analytics

        n = analytics.total_uses
        analytics.total_uses += 1
        # Running averages
        if n > 0:
            analytics.average_latency_ms = (analytics.average_latency_ms * n + latency_ms) / (n + 1)
            analytics.average_cost = (analytics.average_cost * n + cost) / (n + 1)
            analytics.average_tokens = (analytics.average_tokens * n + tokens) / (n + 1)
        else:
            analytics.average_latency_ms = latency_ms
            analytics.average_cost = cost
            analytics.average_tokens = float(tokens)

        if success:
            total_successes = analytics.success_rate * n + 1
            analytics.success_rate = total_successes / (n + 1)
        else:
            total_successes = analytics.success_rate * n
            analytics.success_rate = total_successes / (n + 1)

    def get_analytics(self, template_id: str, version: int | None = None) -> list[PromptAnalytics]:
        """Get analytics for a template (all versions or specific)."""
        if version is not None:
            key = f"{template_id}:{version}"
            a = self._analytics.get(key)
            return [a] if a else []
        return [a for k, a in self._analytics.items() if k.startswith(f"{template_id}:")]

    # -- Stats ---------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Return prompt management statistics."""
        counts: dict[str, int] = {s.value: 0 for s in PromptStatus}
        for t in self._templates.values():
            counts[t.status.value] += 1
        return {
            "total_templates": len(self._templates),
            "template_statuses": counts,
            "total_versions": sum(len(v) for v in self._versions.values()),
            "active_ab_tests": len(self._ab_tests),
        }


class PromptNotFoundError(Exception):
    """Raised when a prompt template is not found."""


class PromptRenderError(Exception):
    """Raised when rendering a prompt template fails."""


class PromptCapacityError(Exception):
    """Raised when prompt storage capacity is reached."""
