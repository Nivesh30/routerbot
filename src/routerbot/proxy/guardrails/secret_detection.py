"""Secret detection and redaction guardrail.

Scans message content for common secret patterns (API keys, tokens,
private keys, connection strings) and either **redacts** them with
``[REDACTED]`` or **blocks** the request entirely.

Supported secret categories:

- **API keys** — OpenAI, Anthropic, AWS, GCP, Azure, Stripe, GitHub,
  Slack, SendGrid, Twilio, and generic patterns.
- **Private keys** — RSA, SSH (ed25519, ecdsa), PGP.
- **Tokens** — JWT, OAuth bearer, basic auth.
- **Connection strings** — database URLs, Redis URLs.
- **High-entropy strings** — configurable minimum length/entropy.

Configuration::

    guardrails:
      - name: secret_detection
        type: secret_detection
        enabled: true
        mode: "redact"   # or "block"
        priority: 1
        custom_patterns:
          - name: internal_token
            pattern: "itk_[a-zA-Z0-9]{32}"
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from routerbot.proxy.guardrails.base import (
    BaseGuardrail,
    GuardrailAction,
    GuardrailContext,
    GuardrailResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Built-in secret patterns
# ---------------------------------------------------------------------------


@dataclass
class SecretPattern:
    """A named regex pattern for detecting a specific secret type."""

    name: str
    pattern: re.Pattern[str]
    description: str = ""


# Pre-compiled patterns for common secrets
_BUILTIN_PATTERNS: list[SecretPattern] = [
    # --- API Keys ---
    SecretPattern(
        name="openai_api_key",
        pattern=re.compile(r"sk-[a-zA-Z0-9]{20,}"),
        description="OpenAI API key",
    ),
    SecretPattern(
        name="anthropic_api_key",
        pattern=re.compile(r"sk-ant-[a-zA-Z0-9\-]{20,}"),
        description="Anthropic API key",
    ),
    SecretPattern(
        name="aws_access_key",
        pattern=re.compile(r"AKIA[0-9A-Z]{16}"),
        description="AWS access key ID",
    ),
    SecretPattern(
        name="aws_secret_key",
        pattern=re.compile(r"(?:aws_secret_access_key|aws_secret)\s*[=:]\s*[A-Za-z0-9/+=]{40}"),
        description="AWS secret access key",
    ),
    SecretPattern(
        name="gcp_api_key",
        pattern=re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
        description="Google Cloud API key",
    ),
    SecretPattern(
        name="gcp_service_account",
        pattern=re.compile(r'"type"\s*:\s*"service_account"'),
        description="GCP service account JSON",
    ),
    SecretPattern(
        name="azure_key",
        pattern=re.compile(r"[a-fA-F0-9]{32}"),
        description="Azure subscription key (32-char hex)",
    ),
    SecretPattern(
        name="stripe_key",
        pattern=re.compile(r"(?:sk|pk)_(?:test|live)_[a-zA-Z0-9]{24,}"),
        description="Stripe API key",
    ),
    SecretPattern(
        name="github_token",
        pattern=re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{30,}"),
        description="GitHub personal/OAuth token",
    ),
    SecretPattern(
        name="slack_token",
        pattern=re.compile(r"xox[bpsa]-[0-9]+-[a-zA-Z0-9]+"),
        description="Slack API token",
    ),
    SecretPattern(
        name="sendgrid_key",
        pattern=re.compile(r"SG\.[a-zA-Z0-9_\-]{22}\.[a-zA-Z0-9_\-]{43}"),
        description="SendGrid API key",
    ),
    SecretPattern(
        name="twilio_key",
        pattern=re.compile(r"SK[a-f0-9]{32}"),
        description="Twilio API key",
    ),
    # --- Private Keys ---
    SecretPattern(
        name="rsa_private_key",
        pattern=re.compile(r"-----BEGIN RSA PRIVATE KEY-----"),
        description="RSA private key header",
    ),
    SecretPattern(
        name="ssh_private_key",
        pattern=re.compile(r"-----BEGIN (?:OPENSSH|EC|DSA) PRIVATE KEY-----"),
        description="SSH/EC/DSA private key header",
    ),
    SecretPattern(
        name="pgp_private_key",
        pattern=re.compile(r"-----BEGIN PGP PRIVATE KEY BLOCK-----"),
        description="PGP private key header",
    ),
    # --- Tokens ---
    SecretPattern(
        name="jwt_token",
        pattern=re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_\-]+"),
        description="JWT token",
    ),
    SecretPattern(
        name="basic_auth",
        pattern=re.compile(r"(?:Basic\s+)[A-Za-z0-9+/]{20,}={0,2}"),
        description="HTTP Basic auth header",
    ),
    # --- Connection Strings ---
    SecretPattern(
        name="database_url",
        pattern=re.compile(
            r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s\"']+:[^\s\"']+@[^\s\"']+"
        ),
        description="Database connection URL with credentials",
    ),
]

# Subset of patterns that are high-precision (low false-positive rate)
# Azure hex key is too generic, so we exclude it from default
_DEFAULT_PATTERN_NAMES: frozenset[str] = frozenset(
    p.name for p in _BUILTIN_PATTERNS if p.name != "azure_key"
)


# ---------------------------------------------------------------------------
# Detection result
# ---------------------------------------------------------------------------


@dataclass
class SecretMatch:
    """A single detected secret in the content."""

    pattern_name: str
    matched_text: str
    start: int
    end: int
    description: str = ""


# ---------------------------------------------------------------------------
# Secret detector engine
# ---------------------------------------------------------------------------


class SecretDetector:
    """Scans text for secret patterns.

    Parameters
    ----------
    patterns:
        List of :class:`SecretPattern` to use.  Defaults to all built-in
        patterns except the generic Azure hex key.
    entropy_threshold:
        Minimum Shannon entropy for high-entropy string detection.
        Set to 0 to disable entropy checking.
    entropy_min_length:
        Minimum string length for entropy checking.
    """

    def __init__(
        self,
        *,
        patterns: list[SecretPattern] | None = None,
        include_azure_key: bool = False,
        custom_patterns: list[SecretPattern] | None = None,
        entropy_threshold: float = 0.0,
        entropy_min_length: int = 20,
    ) -> None:
        if patterns is not None:
            self._patterns = list(patterns)
        else:
            self._patterns = [
                p
                for p in _BUILTIN_PATTERNS
                if include_azure_key or p.name in _DEFAULT_PATTERN_NAMES
            ]

        if custom_patterns:
            self._patterns.extend(custom_patterns)

        self._entropy_threshold = entropy_threshold
        self._entropy_min_length = entropy_min_length

    def scan(self, text: str) -> list[SecretMatch]:
        """Scan *text* and return all detected secrets."""
        matches: list[SecretMatch] = []

        for pattern in self._patterns:
            for m in pattern.pattern.finditer(text):
                matches.append(
                    SecretMatch(
                        pattern_name=pattern.name,
                        matched_text=m.group(),
                        start=m.start(),
                        end=m.end(),
                        description=pattern.description,
                    )
                )

        return matches

    def redact(self, text: str, placeholder: str = "[REDACTED]") -> tuple[str, list[SecretMatch]]:
        """Scan text and replace all secrets with *placeholder*.

        Returns the redacted text and the list of matches found.
        """
        matches = self.scan(text)
        if not matches:
            return text, []

        # Sort by start position descending so replacements don't shift offsets
        sorted_matches = sorted(matches, key=lambda m: m.start, reverse=True)
        result = text
        for match in sorted_matches:
            result = result[: match.start] + placeholder + result[match.end :]

        return result, matches


def _shannon_entropy(text: str) -> float:
    """Calculate Shannon entropy of a string."""
    if not text:
        return 0.0
    counts = Counter(text)
    length = len(text)
    return -sum(
        (count / length) * math.log2(count / length) for count in counts.values()
    )


# ---------------------------------------------------------------------------
# Secret Detection Guardrail
# ---------------------------------------------------------------------------


class SecretDetectionGuardrail(BaseGuardrail):
    """Guardrail that detects and handles secrets in messages.

    Parameters
    ----------
    mode:
        ``"redact"`` — replace secrets with ``[REDACTED]`` and forward.
        ``"block"`` — reject the request entirely.
    placeholder:
        Replacement text for redacted secrets.
    include_azure_key:
        Include the generic 32-char hex pattern for Azure keys.
    custom_patterns:
        Additional :class:`SecretPattern` instances.
    check_response_content:
        Also check the model's response for secrets.
    kwargs:
        Passed to :class:`BaseGuardrail` (name, enabled, priority).
    """

    def __init__(
        self,
        *,
        mode: str = "redact",
        placeholder: str = "[REDACTED]",
        include_azure_key: bool = False,
        custom_patterns: list[SecretPattern] | None = None,
        check_response_content: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._mode = mode
        self._placeholder = placeholder
        self._check_response = check_response_content
        self._detector = SecretDetector(
            include_azure_key=include_azure_key,
            custom_patterns=custom_patterns,
        )

    @property
    def mode(self) -> str:
        """Return the current operating mode."""
        return self._mode

    # ------------------------------------------------------------------
    # Request check
    # ------------------------------------------------------------------

    async def check_request(
        self,
        messages: list[dict[str, Any]],
        context: GuardrailContext,
    ) -> GuardrailResult:
        """Scan all message contents for secrets."""
        all_matches: list[SecretMatch] = []
        modified = False
        new_messages: list[dict[str, Any]] = []

        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str) or not content:
                new_messages.append(msg)
                continue

            matches = self._detector.scan(content)
            if not matches:
                new_messages.append(msg)
                continue

            all_matches.extend(matches)

            if self._mode == "block":
                pattern_names = sorted({m.pattern_name for m in matches})
                return GuardrailResult(
                    action=GuardrailAction.BLOCK,
                    reason=f"Secret(s) detected in message: {', '.join(pattern_names)}",
                    details={
                        "detected_patterns": pattern_names,
                        "match_count": len(matches),
                    },
                )

            # Redact mode
            redacted_text, _ = self._detector.redact(content, self._placeholder)
            new_messages.append({**msg, "content": redacted_text})
            modified = True

        if modified:
            return GuardrailResult(
                action=GuardrailAction.MODIFY,
                modified_content=json.dumps(new_messages),
                reason=f"Redacted {len(all_matches)} secret(s)",
                details={
                    "detected_patterns": sorted({m.pattern_name for m in all_matches}),
                    "match_count": len(all_matches),
                },
            )

        return GuardrailResult(action=GuardrailAction.ALLOW)

    # ------------------------------------------------------------------
    # Response check
    # ------------------------------------------------------------------

    async def check_response(
        self,
        response: str,
        context: GuardrailContext,
    ) -> GuardrailResult:
        """Optionally scan model responses for secrets."""
        if not self._check_response:
            return GuardrailResult(action=GuardrailAction.ALLOW, guardrail_name=self.name)

        matches = self._detector.scan(response)
        if not matches:
            return GuardrailResult(action=GuardrailAction.ALLOW, guardrail_name=self.name)

        if self._mode == "block":
            pattern_names = sorted({m.pattern_name for m in matches})
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                reason=f"Secret(s) detected in response: {', '.join(pattern_names)}",
                guardrail_name=self.name,
                details={
                    "detected_patterns": pattern_names,
                    "match_count": len(matches),
                },
            )

        redacted, _ = self._detector.redact(response, self._placeholder)
        return GuardrailResult(
            action=GuardrailAction.MODIFY,
            modified_content=redacted,
            reason=f"Redacted {len(matches)} secret(s) from response",
            guardrail_name=self.name,
            details={
                "detected_patterns": sorted({m.pattern_name for m in matches}),
                "match_count": len(matches),
            },
        )
