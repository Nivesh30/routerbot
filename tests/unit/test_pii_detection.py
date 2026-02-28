"""Tests for the PII detection guardrail (Task 6.3).

Covers:
- PIIPattern and PIIMatch dataclasses
- Luhn check validator
- PIIDetector scan, redact, and hash_pii
- PIIDetectionGuardrail in redact, block, and hash modes
- Custom patterns and entity type filtering
- Response checking
- Integration with GuardrailManager
- Edge cases
"""

from __future__ import annotations

import re

import pytest

from routerbot.proxy.guardrails.base import (
    GuardrailAction,
    GuardrailContext,
)
from routerbot.proxy.guardrails.pii_detection import (
    PIIDetectionGuardrail,
    PIIDetector,
    PIIPattern,
    _luhn_check,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def context() -> GuardrailContext:
    return GuardrailContext(request_id="req-pii-001", model="gpt-4")


@pytest.fixture()
def detector() -> PIIDetector:
    """Default detector with built-in patterns."""
    return PIIDetector()


@pytest.fixture()
def redact_guardrail() -> PIIDetectionGuardrail:
    return PIIDetectionGuardrail(mode="redact", name="pii")


@pytest.fixture()
def block_guardrail() -> PIIDetectionGuardrail:
    return PIIDetectionGuardrail(mode="block", name="pii")


@pytest.fixture()
def hash_guardrail() -> PIIDetectionGuardrail:
    return PIIDetectionGuardrail(mode="hash", name="pii", hash_salt="test-salt")


# ===================================================================
# Luhn Check Tests
# ===================================================================


class TestLuhnCheck:
    """Tests for the Luhn algorithm validator."""

    def test_valid_visa(self) -> None:
        assert _luhn_check("4111111111111111") is True

    def test_valid_mastercard(self) -> None:
        assert _luhn_check("5500000000000004") is True

    def test_valid_amex(self) -> None:
        assert _luhn_check("378282246310005") is True

    def test_valid_discover(self) -> None:
        assert _luhn_check("6011111111111117") is True

    def test_invalid_number(self) -> None:
        assert _luhn_check("4111111111111112") is False

    def test_too_short(self) -> None:
        assert _luhn_check("123456") is False

    def test_with_spaces(self) -> None:
        assert _luhn_check("4111 1111 1111 1111") is True

    def test_with_dashes(self) -> None:
        assert _luhn_check("4111-1111-1111-1111") is True


# ===================================================================
# PIIDetector Scan Tests
# ===================================================================


class TestPIIDetectorScan:
    """Tests for PIIDetector.scan()."""

    def test_no_pii(self, detector: PIIDetector) -> None:
        matches = detector.scan("Hello, this is a normal message.")
        assert matches == []

    def test_detect_email(self, detector: PIIDetector) -> None:
        text = "Contact me at john.doe@example.com please"
        matches = detector.scan(text)
        assert any(m.entity_type == "email" for m in matches)
        email_match = next(m for m in matches if m.entity_type == "email")
        assert email_match.matched_text == "john.doe@example.com"

    def test_detect_email_with_plus(self, detector: PIIDetector) -> None:
        text = "Send to user+tag@company.co.uk"
        matches = detector.scan(text)
        assert any(m.entity_type == "email" for m in matches)

    def test_detect_us_phone(self, detector: PIIDetector) -> None:
        text = "Call me at (555) 123-4567"
        matches = detector.scan(text)
        assert any(m.entity_type == "phone" for m in matches)

    def test_detect_us_phone_dashes(self, detector: PIIDetector) -> None:
        text = "Phone: 555-123-4567"
        matches = detector.scan(text)
        assert any(m.entity_type == "phone" for m in matches)

    def test_detect_us_phone_with_country_code(self, detector: PIIDetector) -> None:
        text = "Call +1 555-123-4567"
        matches = detector.scan(text)
        assert any(m.entity_type == "phone" for m in matches)

    def test_detect_ssn_with_dashes(self, detector: PIIDetector) -> None:
        text = "SSN: 123-45-6789"
        matches = detector.scan(text)
        assert any(m.entity_type == "ssn" for m in matches)

    def test_detect_ssn_no_dashes(self, detector: PIIDetector) -> None:
        text = "SSN: 123456789"
        matches = detector.scan(text)
        assert any(m.entity_type == "ssn" for m in matches)

    def test_ssn_rejects_invalid_area(self, detector: PIIDetector) -> None:
        """SSN starting with 000 or 666 should not match."""
        text = "Not an SSN: 000-12-3456"
        matches = detector.scan(text)
        ssn_matches = [m for m in matches if m.entity_type == "ssn"]
        assert len(ssn_matches) == 0

    def test_detect_credit_card_visa(self, detector: PIIDetector) -> None:
        text = "Card: 4111111111111111"
        matches = detector.scan(text)
        assert any(m.entity_type == "credit_card" for m in matches)

    def test_detect_credit_card_with_spaces(self, detector: PIIDetector) -> None:
        text = "Payment: 4111 1111 1111 1111"
        matches = detector.scan(text)
        assert any(m.entity_type == "credit_card" for m in matches)

    def test_credit_card_rejects_invalid_luhn(self, detector: PIIDetector) -> None:
        text = "Not a card: 4111111111111112"
        matches = detector.scan(text)
        cc_matches = [m for m in matches if m.entity_type == "credit_card"]
        assert len(cc_matches) == 0

    def test_detect_ipv4(self, detector: PIIDetector) -> None:
        text = "Server at 192.168.1.100"
        matches = detector.scan(text)
        assert any(m.entity_type == "ip_address" for m in matches)

    def test_detect_ipv6(self, detector: PIIDetector) -> None:
        text = "IPv6: 2001:0db8:85a3:0000:0000:8a2e:0370:7334"
        matches = detector.scan(text)
        assert any(m.entity_type == "ipv6_address" for m in matches)

    def test_multiple_pii(self, detector: PIIDetector) -> None:
        text = "Email john@example.com, phone 555-123-4567"
        matches = detector.scan(text)
        types = {m.entity_type for m in matches}
        assert "email" in types
        assert "phone" in types

    def test_detect_street_address(self) -> None:
        detector = PIIDetector(include_address=True)
        text = "Send to 123 Main Street"
        matches = detector.scan(text)
        assert any(m.entity_type == "street_address" for m in matches)


# ===================================================================
# PIIDetector Redact Tests
# ===================================================================


class TestPIIDetectorRedact:
    """Tests for PIIDetector.redact()."""

    def test_redact_email(self, detector: PIIDetector) -> None:
        text = "Contact john@example.com please"
        redacted, matches = detector.redact(text)
        assert "[EMAIL]" in redacted
        assert "john@example.com" not in redacted
        assert len(matches) > 0

    def test_redact_multiple(self, detector: PIIDetector) -> None:
        text = "Email: john@example.com, SSN: 123-45-6789"
        redacted, _matches = detector.redact(text)
        assert "[EMAIL]" in redacted
        assert "[SSN]" in redacted
        assert "john@example.com" not in redacted

    def test_redact_no_pii(self, detector: PIIDetector) -> None:
        text = "Normal text with no PII"
        redacted, matches = detector.redact(text)
        assert redacted == text
        assert matches == []

    def test_custom_placeholders(self, detector: PIIDetector) -> None:
        text = "Email: john@example.com"
        redacted, _ = detector.redact(text, placeholders={"email": "***EMAIL***"})
        assert "***EMAIL***" in redacted

    def test_redact_preserves_surrounding(self, detector: PIIDetector) -> None:
        text = "Before john@example.com After"
        redacted, _ = detector.redact(text)
        assert redacted.startswith("Before ")
        assert redacted.endswith(" After")


# ===================================================================
# PIIDetector Hash Tests
# ===================================================================


class TestPIIDetectorHash:
    """Tests for PIIDetector.hash_pii()."""

    def test_hash_email(self, detector: PIIDetector) -> None:
        text = "Contact john@example.com"
        hashed, matches = detector.hash_pii(text, salt="s")
        assert "john@example.com" not in hashed
        assert "[EMAIL:" in hashed
        assert len(matches) > 0

    def test_hash_deterministic(self, detector: PIIDetector) -> None:
        text = "john@example.com"
        hashed1, _ = detector.hash_pii(text, salt="s")
        hashed2, _ = detector.hash_pii(text, salt="s")
        assert hashed1 == hashed2

    def test_hash_different_salt(self, detector: PIIDetector) -> None:
        text = "john@example.com"
        hashed1, _ = detector.hash_pii(text, salt="salt1")
        hashed2, _ = detector.hash_pii(text, salt="salt2")
        assert hashed1 != hashed2

    def test_hash_no_pii(self, detector: PIIDetector) -> None:
        text = "Normal text"
        hashed, matches = detector.hash_pii(text)
        assert hashed == text
        assert matches == []


# ===================================================================
# Entity Type Filtering Tests
# ===================================================================


class TestEntityTypeFiltering:
    """Tests for filtering entity types."""

    def test_only_email(self) -> None:
        detector = PIIDetector(entity_types=["email"])
        text = "Email: john@example.com, SSN: 123-45-6789"
        matches = detector.scan(text)
        assert all(m.entity_type == "email" for m in matches)
        assert len(matches) > 0

    def test_only_ssn(self) -> None:
        detector = PIIDetector(entity_types=["ssn"])
        text = "Email: john@example.com, SSN: 123-45-6789"
        matches = detector.scan(text)
        types = {m.entity_type for m in matches}
        assert "ssn" in types
        assert "email" not in types

    def test_address_excluded_by_default(self) -> None:
        detector = PIIDetector()
        text = "123 Main Street"
        matches = detector.scan(text)
        assert not any(m.entity_type == "street_address" for m in matches)


# ===================================================================
# Custom Patterns Tests
# ===================================================================


class TestCustomPatterns:
    """Tests for custom PII patterns."""

    def test_custom_pattern(self) -> None:
        custom = PIIPattern(
            name="employee_id",
            pattern=re.compile(r"EMP-\d{6}"),
            placeholder="[EMPLOYEE_ID]",
        )
        detector = PIIDetector(custom_patterns=[custom])
        text = "Employee: EMP-123456"
        matches = detector.scan(text)
        assert any(m.entity_type == "employee_id" for m in matches)

    def test_custom_pattern_redacted(self) -> None:
        custom = PIIPattern(
            name="employee_id",
            pattern=re.compile(r"EMP-\d{6}"),
            placeholder="[EMPLOYEE_ID]",
        )
        detector = PIIDetector(custom_patterns=[custom])
        text = "Employee: EMP-123456"
        redacted, _ = detector.redact(text)
        assert "[EMPLOYEE_ID]" in redacted


# ===================================================================
# PIIDetectionGuardrail — Redact Mode Tests
# ===================================================================


class TestRedactMode:
    """Tests for the guardrail in redact mode."""

    @pytest.mark.asyncio()
    async def test_no_pii_allow(
        self,
        redact_guardrail: PIIDetectionGuardrail,
        context: GuardrailContext,
    ) -> None:
        messages = [{"role": "user", "content": "Hello, how are you?"}]
        result = await redact_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.ALLOW

    @pytest.mark.asyncio()
    async def test_redacts_email(
        self,
        redact_guardrail: PIIDetectionGuardrail,
        context: GuardrailContext,
    ) -> None:
        messages = [{"role": "user", "content": "My email is john@example.com"}]
        result = await redact_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.MODIFY
        assert result.modified_content is not None
        assert "[EMAIL]" in result.modified_content
        assert "john@example.com" not in result.modified_content

    @pytest.mark.asyncio()
    async def test_redacts_multiple_entities(
        self,
        redact_guardrail: PIIDetectionGuardrail,
        context: GuardrailContext,
    ) -> None:
        messages = [
            {
                "role": "user",
                "content": "Email john@example.com, SSN 123-45-6789",
            }
        ]
        result = await redact_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.MODIFY
        assert result.details["match_count"] >= 2

    @pytest.mark.asyncio()
    async def test_redacts_across_messages(
        self,
        redact_guardrail: PIIDetectionGuardrail,
        context: GuardrailContext,
    ) -> None:
        messages = [
            {"role": "system", "content": "You are a helper."},
            {"role": "user", "content": "Email: john@example.com"},
        ]
        result = await redact_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.MODIFY

        import json

        parsed = json.loads(result.modified_content)
        assert parsed[0]["content"] == "You are a helper."
        assert "[EMAIL]" in parsed[1]["content"]

    @pytest.mark.asyncio()
    async def test_non_string_content(
        self,
        redact_guardrail: PIIDetectionGuardrail,
        context: GuardrailContext,
    ) -> None:
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "hello"}]},
        ]
        result = await redact_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.ALLOW

    @pytest.mark.asyncio()
    async def test_reason_includes_count(
        self,
        redact_guardrail: PIIDetectionGuardrail,
        context: GuardrailContext,
    ) -> None:
        messages = [{"role": "user", "content": "john@example.com"}]
        result = await redact_guardrail.check_request(messages, context)
        assert "1 PII" in (result.reason or "")


# ===================================================================
# PIIDetectionGuardrail — Block Mode Tests
# ===================================================================


class TestBlockMode:
    """Tests for the guardrail in block mode."""

    @pytest.mark.asyncio()
    async def test_no_pii_allow(
        self,
        block_guardrail: PIIDetectionGuardrail,
        context: GuardrailContext,
    ) -> None:
        messages = [{"role": "user", "content": "Hello!"}]
        result = await block_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.ALLOW

    @pytest.mark.asyncio()
    async def test_blocks_on_email(
        self,
        block_guardrail: PIIDetectionGuardrail,
        context: GuardrailContext,
    ) -> None:
        messages = [{"role": "user", "content": "john@example.com"}]
        result = await block_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.BLOCK
        assert "email" in (result.reason or "")

    @pytest.mark.asyncio()
    async def test_block_details(
        self,
        block_guardrail: PIIDetectionGuardrail,
        context: GuardrailContext,
    ) -> None:
        messages = [{"role": "user", "content": "SSN: 123-45-6789"}]
        result = await block_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.BLOCK
        assert "detected_entities" in result.details
        assert result.details["match_count"] >= 1


# ===================================================================
# PIIDetectionGuardrail — Hash Mode Tests
# ===================================================================


class TestHashMode:
    """Tests for the guardrail in hash mode."""

    @pytest.mark.asyncio()
    async def test_hash_pii(
        self,
        hash_guardrail: PIIDetectionGuardrail,
        context: GuardrailContext,
    ) -> None:
        messages = [{"role": "user", "content": "Email: john@example.com"}]
        result = await hash_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.MODIFY
        assert "[EMAIL:" in result.modified_content
        assert "john@example.com" not in result.modified_content

    @pytest.mark.asyncio()
    async def test_hash_reason(
        self,
        hash_guardrail: PIIDetectionGuardrail,
        context: GuardrailContext,
    ) -> None:
        messages = [{"role": "user", "content": "john@example.com"}]
        result = await hash_guardrail.check_request(messages, context)
        assert "Hashed" in (result.reason or "")


# ===================================================================
# Response Checking Tests
# ===================================================================


class TestResponseChecking:
    """Tests for checking model responses."""

    @pytest.mark.asyncio()
    async def test_disabled_by_default(self, context: GuardrailContext) -> None:
        guardrail = PIIDetectionGuardrail(mode="redact")
        result = await guardrail.check_response("john@example.com", context)
        assert result.action == GuardrailAction.ALLOW

    @pytest.mark.asyncio()
    async def test_response_redact(self, context: GuardrailContext) -> None:
        guardrail = PIIDetectionGuardrail(mode="redact", check_response_content=True)
        result = await guardrail.check_response("User email is john@example.com", context)
        assert result.action == GuardrailAction.MODIFY
        assert "[EMAIL]" in result.modified_content

    @pytest.mark.asyncio()
    async def test_response_block(self, context: GuardrailContext) -> None:
        guardrail = PIIDetectionGuardrail(mode="block", check_response_content=True)
        result = await guardrail.check_response("john@example.com", context)
        assert result.action == GuardrailAction.BLOCK

    @pytest.mark.asyncio()
    async def test_response_hash(self, context: GuardrailContext) -> None:
        guardrail = PIIDetectionGuardrail(mode="hash", check_response_content=True, hash_salt="s")
        result = await guardrail.check_response("john@example.com", context)
        assert result.action == GuardrailAction.MODIFY
        assert "[EMAIL:" in result.modified_content

    @pytest.mark.asyncio()
    async def test_response_no_pii(self, context: GuardrailContext) -> None:
        guardrail = PIIDetectionGuardrail(mode="redact", check_response_content=True)
        result = await guardrail.check_response("Normal response", context)
        assert result.action == GuardrailAction.ALLOW


# ===================================================================
# Integration with GuardrailManager Tests
# ===================================================================


class TestIntegrationWithManager:
    """Test PII detection within the guardrail pipeline."""

    @pytest.mark.asyncio()
    async def test_redact_in_pipeline(self, context: GuardrailContext) -> None:
        from routerbot.proxy.guardrails.manager import GuardrailManager

        manager = GuardrailManager()
        manager.register(PIIDetectionGuardrail(mode="redact", name="pii", priority=1))

        messages = [{"role": "user", "content": "Email: john@example.com"}]
        result = await manager.run_request_guardrails(messages, context)
        assert result.modified
        assert result.modified_messages is not None
        assert "[EMAIL]" in result.modified_messages[0]["content"]

    @pytest.mark.asyncio()
    async def test_block_in_pipeline(self, context: GuardrailContext) -> None:
        from routerbot.proxy.guardrails.manager import GuardrailManager

        manager = GuardrailManager()
        manager.register(PIIDetectionGuardrail(mode="block", name="pii", priority=1))

        messages = [{"role": "user", "content": "john@example.com"}]
        result = await manager.run_request_guardrails(messages, context)
        assert result.blocked


# ===================================================================
# Properties and Configuration Tests
# ===================================================================


class TestGuardrailProperties:
    """Tests for guardrail configuration."""

    def test_mode_property(self) -> None:
        g = PIIDetectionGuardrail(mode="hash")
        assert g.mode == "hash"

    def test_name_default(self) -> None:
        g = PIIDetectionGuardrail()
        assert g.name == "PIIDetectionGuardrail"

    def test_custom_name(self) -> None:
        g = PIIDetectionGuardrail(name="my_pii")
        assert g.name == "my_pii"

    def test_enabled_default(self) -> None:
        g = PIIDetectionGuardrail()
        assert g.enabled is True

    def test_priority(self) -> None:
        g = PIIDetectionGuardrail(priority=3)
        assert g.priority == 3
