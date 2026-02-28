"""PII (Personally Identifiable Information) detection and redaction guardrail.

Scans message content for common PII entities and either **redacts** them,
**blocks** the request, or replaces them with a deterministic **hash**.

Supported entity types:

- **Email addresses**
- **Phone numbers** — US and international formats
- **Social Security Numbers** (SSN)
- **Credit card numbers** — with Luhn check validation
- **IP addresses** — IPv4 and IPv6
- **Physical addresses** — basic US street address patterns

Configuration::

    guardrails:
      - name: pii_detection
        type: pii_detection
        enabled: true
        mode: "redact"   # or "block" or "hash"
        priority: 3
        entity_types: ["email", "phone", "ssn", "credit_card", "ip_address"]
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
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
# PII entity patterns
# ---------------------------------------------------------------------------


@dataclass
class PIIPattern:
    """A named regex pattern for detecting a PII entity type."""

    name: str
    pattern: re.Pattern[str]
    placeholder: str
    description: str = ""
    validator: Any = None  # Optional callable(match_text) -> bool


def _luhn_check(number: str) -> bool:
    """Validate a credit card number using the Luhn algorithm."""
    digits = [int(d) for d in number if d.isdigit()]
    if len(digits) < 13:
        return False

    # Luhn algorithm
    checksum = 0
    reverse_digits = digits[::-1]
    for i, digit in enumerate(reverse_digits):
        if i % 2 == 1:
            doubled = digit * 2
            checksum += doubled - 9 if doubled > 9 else doubled
        else:
            checksum += digit

    return checksum % 10 == 0


def _is_valid_ipv4(text: str) -> bool:
    """Validate that an IPv4 address has valid octets (0-255)."""
    parts = text.split(".")
    if len(parts) != 4:
        return False
    return all(0 <= int(p) <= 255 for p in parts if p.isdigit())


# Pre-compiled patterns for common PII entities
_BUILTIN_PII_PATTERNS: list[PIIPattern] = [
    PIIPattern(
        name="email",
        pattern=re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"),
        placeholder="[EMAIL]",
        description="Email address",
    ),
    PIIPattern(
        name="phone",
        pattern=re.compile(
            r"(?<!\d)"  # Not preceded by a digit
            r"(?:"
            r"\+?1[\s\-.]?"  # US country code
            r")?"
            r"(?:"
            r"\(?\d{3}\)?[\s\-.]?"  # Area code
            r"\d{3}[\s\-.]?"  # Exchange
            r"\d{4}"  # Subscriber
            r")"
            r"(?!\d)"  # Not followed by a digit
        ),
        placeholder="[PHONE]",
        description="Phone number (US format)",
    ),
    PIIPattern(
        name="phone_intl",
        pattern=re.compile(
            r"\+(?!1[\s\-.]?\(?\d{3})"  # Not US
            r"\d{1,3}[\s\-.]?"
            r"\d{2,4}[\s\-.]?"
            r"\d{3,4}[\s\-.]?"
            r"\d{3,4}"
        ),
        placeholder="[PHONE]",
        description="International phone number",
    ),
    PIIPattern(
        name="ssn",
        pattern=re.compile(
            r"\b(?!000|666|9\d{2})\d{3}"  # Area number
            r"[\s\-]?"
            r"(?!00)\d{2}"  # Group number
            r"[\s\-]?"
            r"(?!0000)\d{4}\b"  # Serial number
        ),
        placeholder="[SSN]",
        description="US Social Security Number",
    ),
    PIIPattern(
        name="credit_card",
        pattern=re.compile(
            r"\b(?:"
            r"4\d{3}|"  # Visa
            r"5[1-5]\d{2}|"  # Mastercard
            r"3[47]\d{2}|"  # Amex
            r"6(?:011|5\d{2})"  # Discover
            r")"
            r"[\s\-]?\d{4,6}"
            r"[\s\-]?\d{4,5}"
            r"(?:[\s\-]?\d{4})?"
            r"\b"
        ),
        placeholder="[CREDIT_CARD]",
        description="Credit card number",
        validator=_luhn_check,
    ),
    PIIPattern(
        name="ip_address",
        pattern=re.compile(
            r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
        ),
        placeholder="[IP_ADDRESS]",
        description="IPv4 address",
        validator=_is_valid_ipv4,
    ),
    PIIPattern(
        name="ipv6_address",
        pattern=re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"),
        placeholder="[IP_ADDRESS]",
        description="IPv6 address",
    ),
    PIIPattern(
        name="street_address",
        pattern=re.compile(
            r"\b\d{1,5}\s+"
            r"(?:[NSEW]\.?\s+)?"
            r"(?:[A-Z][a-z]+\s+){1,3}"
            r"(?:St(?:reet)?|Ave(?:nue)?|Blvd|Boulevard|Dr(?:ive)?|"
            r"Ln|Lane|Rd|Road|Ct|Court|Pl|Place|Way|Cir(?:cle)?|"
            r"Pkwy|Parkway|Hwy|Highway)"
            r"\.?\b",
            re.IGNORECASE,
        ),
        placeholder="[ADDRESS]",
        description="US street address",
    ),
]

# Default entities to detect (all except street_address which has higher false positives)
_DEFAULT_ENTITY_TYPES: frozenset[str] = frozenset(
    ["email", "phone", "phone_intl", "ssn", "credit_card", "ip_address", "ipv6_address"]
)


# ---------------------------------------------------------------------------
# Detection result
# ---------------------------------------------------------------------------


@dataclass
class PIIMatch:
    """A single detected PII entity in the content."""

    entity_type: str
    matched_text: str
    start: int
    end: int
    description: str = ""


# ---------------------------------------------------------------------------
# PII detector engine
# ---------------------------------------------------------------------------


class PIIDetector:
    """Scans text for PII patterns.

    Parameters
    ----------
    entity_types:
        Which entity types to enable.  ``None`` means all defaults.
    include_address:
        Include street address detection (higher false-positive rate).
    custom_patterns:
        Additional :class:`PIIPattern` instances.
    """

    def __init__(
        self,
        *,
        entity_types: list[str] | None = None,
        include_address: bool = False,
        custom_patterns: list[PIIPattern] | None = None,
    ) -> None:
        allowed = set(entity_types) if entity_types else set(_DEFAULT_ENTITY_TYPES)
        if include_address:
            allowed.add("street_address")

        self._patterns = [p for p in _BUILTIN_PII_PATTERNS if p.name in allowed]

        if custom_patterns:
            self._patterns.extend(custom_patterns)

    def scan(self, text: str) -> list[PIIMatch]:
        """Scan *text* and return all detected PII entities."""
        matches: list[PIIMatch] = []

        for pattern in self._patterns:
            for m in pattern.pattern.finditer(text):
                matched_text = m.group()

                # Run optional validator (e.g. Luhn check for credit cards)
                if pattern.validator and not pattern.validator(matched_text):
                    continue

                matches.append(
                    PIIMatch(
                        entity_type=pattern.name,
                        matched_text=matched_text,
                        start=m.start(),
                        end=m.end(),
                        description=pattern.description,
                    )
                )

        return matches

    def redact(
        self,
        text: str,
        *,
        placeholders: dict[str, str] | None = None,
    ) -> tuple[str, list[PIIMatch]]:
        """Scan text and replace PII with entity-type placeholders.

        Returns the redacted text and the list of matches.
        """
        matches = self.scan(text)
        if not matches:
            return text, []

        # Build placeholder lookup from patterns + overrides
        placeholder_map: dict[str, str] = {p.name: p.placeholder for p in self._patterns}
        if placeholders:
            placeholder_map.update(placeholders)

        # Sort by start descending so replacements don't shift offsets
        sorted_matches = sorted(matches, key=lambda m: m.start, reverse=True)
        result = text
        for match in sorted_matches:
            replacement = placeholder_map.get(match.entity_type, "[PII]")
            result = result[: match.start] + replacement + result[match.end :]

        return result, matches

    def hash_pii(
        self,
        text: str,
        *,
        salt: str = "",
    ) -> tuple[str, list[PIIMatch]]:
        """Scan text and replace PII with deterministic hashes.

        Returns the hashed text and the list of matches.
        Uses SHA-256 truncated to 8 hex chars for readability.
        """
        matches = self.scan(text)
        if not matches:
            return text, []

        sorted_matches = sorted(matches, key=lambda m: m.start, reverse=True)
        result = text
        for match in sorted_matches:
            hash_val = hashlib.sha256((salt + match.matched_text).encode()).hexdigest()[:8]
            replacement = f"[{match.entity_type.upper()}:{hash_val}]"
            result = result[: match.start] + replacement + result[match.end :]

        return result, matches


# ---------------------------------------------------------------------------
# PII Detection Guardrail
# ---------------------------------------------------------------------------


class PIIDetectionGuardrail(BaseGuardrail):
    """Guardrail that detects and handles PII in messages.

    Parameters
    ----------
    mode:
        ``"redact"`` — replace PII with entity-type placeholders.
        ``"block"`` — reject the request entirely.
        ``"hash"`` — replace PII with deterministic hashes.
    entity_types:
        Which entity types to detect.  ``None`` for all defaults.
    include_address:
        Include street address detection.
    custom_patterns:
        Additional :class:`PIIPattern` instances.
    check_response_content:
        Also check the model's response for PII.
    hash_salt:
        Salt for deterministic hashing in hash mode.
    kwargs:
        Passed to :class:`BaseGuardrail` (name, enabled, priority).
    """

    def __init__(
        self,
        *,
        mode: str = "redact",
        entity_types: list[str] | None = None,
        include_address: bool = False,
        custom_patterns: list[PIIPattern] | None = None,
        check_response_content: bool = False,
        hash_salt: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._mode = mode
        self._check_response = check_response_content
        self._hash_salt = hash_salt
        self._detector = PIIDetector(
            entity_types=entity_types,
            include_address=include_address,
            custom_patterns=custom_patterns,
        )

    @property
    def mode(self) -> str:
        """Return the current operating mode."""
        return self._mode

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _process_text(self, text: str) -> tuple[str | None, list[PIIMatch]]:
        """Process text based on mode, returning (processed_text, matches)."""
        if self._mode == "hash":
            return self._detector.hash_pii(text, salt=self._hash_salt)
        return self._detector.redact(text)

    # ------------------------------------------------------------------
    # Request check
    # ------------------------------------------------------------------

    async def check_request(
        self,
        messages: list[dict[str, Any]],
        context: GuardrailContext,
    ) -> GuardrailResult:
        """Scan all message contents for PII."""
        all_matches: list[PIIMatch] = []
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
                entity_types = sorted({m.entity_type for m in matches})
                return GuardrailResult(
                    action=GuardrailAction.BLOCK,
                    reason=f"PII detected in message: {', '.join(entity_types)}",
                    guardrail_name=self.name,
                    details={
                        "detected_entities": entity_types,
                        "match_count": len(matches),
                    },
                )

            # Redact or hash mode
            processed_text, _ = self._process_text(content)
            new_messages.append({**msg, "content": processed_text})
            modified = True

        if modified:
            entity_types = sorted({m.entity_type for m in all_matches})
            action_verb = "Hashed" if self._mode == "hash" else "Redacted"
            return GuardrailResult(
                action=GuardrailAction.MODIFY,
                modified_content=json.dumps(new_messages),
                reason=f"{action_verb} {len(all_matches)} PII entit{'y' if len(all_matches) == 1 else 'ies'}",
                guardrail_name=self.name,
                details={
                    "detected_entities": entity_types,
                    "match_count": len(all_matches),
                },
            )

        return GuardrailResult(action=GuardrailAction.ALLOW, guardrail_name=self.name)

    # ------------------------------------------------------------------
    # Response check
    # ------------------------------------------------------------------

    async def check_response(
        self,
        response: str,
        context: GuardrailContext,
    ) -> GuardrailResult:
        """Optionally scan model responses for PII."""
        if not self._check_response:
            return GuardrailResult(action=GuardrailAction.ALLOW, guardrail_name=self.name)

        matches = self._detector.scan(response)
        if not matches:
            return GuardrailResult(action=GuardrailAction.ALLOW, guardrail_name=self.name)

        entity_types = sorted({m.entity_type for m in matches})

        if self._mode == "block":
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                reason=f"PII detected in response: {', '.join(entity_types)}",
                guardrail_name=self.name,
                details={
                    "detected_entities": entity_types,
                    "match_count": len(matches),
                },
            )

        processed, _ = self._process_text(response)
        action_verb = "Hashed" if self._mode == "hash" else "Redacted"
        return GuardrailResult(
            action=GuardrailAction.MODIFY,
            modified_content=processed,
            reason=f"{action_verb} {len(matches)} PII entit{'y' if len(matches) == 1 else 'ies'} from response",
            guardrail_name=self.name,
            details={
                "detected_entities": entity_types,
                "match_count": len(matches),
            },
        )
