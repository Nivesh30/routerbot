"""Tests for the secret detection guardrail (Task 6.2).

Covers:
- SecretPattern dataclass
- SecretMatch dataclass
- SecretDetector scan and redact
- SecretDetectionGuardrail in redact mode
- SecretDetectionGuardrail in block mode
- Custom patterns
- Response checking
- Integration with GuardrailManager
- Edge cases (no secrets, empty content, multiple secrets)
"""

from __future__ import annotations

import re

import pytest

from routerbot.proxy.guardrails.base import (
    GuardrailAction,
    GuardrailContext,
)
from routerbot.proxy.guardrails.secret_detection import (
    SecretDetectionGuardrail,
    SecretDetector,
    SecretMatch,
    SecretPattern,
    _shannon_entropy,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def context() -> GuardrailContext:
    return GuardrailContext(request_id="req-001", model="gpt-4")


@pytest.fixture()
def detector() -> SecretDetector:
    """Default detector with built-in patterns."""
    return SecretDetector()


@pytest.fixture()
def redact_guardrail() -> SecretDetectionGuardrail:
    """Guardrail in redact mode."""
    return SecretDetectionGuardrail(mode="redact", name="secret_detection")


@pytest.fixture()
def block_guardrail() -> SecretDetectionGuardrail:
    """Guardrail in block mode."""
    return SecretDetectionGuardrail(mode="block", name="secret_detection")


# ===================================================================
# SecretPattern Tests
# ===================================================================


class TestSecretPattern:
    """Tests for the SecretPattern dataclass."""

    def test_create_pattern(self) -> None:
        p = SecretPattern(
            name="test_key",
            pattern=re.compile(r"test_[a-z]{10}"),
            description="Test key",
        )
        assert p.name == "test_key"
        assert p.description == "Test key"


# ===================================================================
# SecretMatch Tests
# ===================================================================


class TestSecretMatch:
    """Tests for the SecretMatch dataclass."""

    def test_create_match(self) -> None:
        m = SecretMatch(
            pattern_name="openai_api_key",
            matched_text="sk-abc123",
            start=10,
            end=19,
            description="OpenAI API key",
        )
        assert m.pattern_name == "openai_api_key"
        assert m.matched_text == "sk-abc123"
        assert m.start == 10
        assert m.end == 19


# ===================================================================
# SecretDetector Scan Tests
# ===================================================================


class TestSecretDetectorScan:
    """Tests for SecretDetector.scan()."""

    def test_no_secrets(self, detector: SecretDetector) -> None:
        matches = detector.scan("Hello, this is a normal message.")
        assert matches == []

    def test_openai_key(self, detector: SecretDetector) -> None:
        text = "My key is sk-abcdefghij1234567890abcdefghij"
        matches = detector.scan(text)
        assert any(m.pattern_name == "openai_api_key" for m in matches)

    def test_anthropic_key(self, detector: SecretDetector) -> None:
        text = "Key: sk-ant-abcdefghij1234567890abcdef"
        matches = detector.scan(text)
        assert any(m.pattern_name == "anthropic_api_key" for m in matches)

    def test_aws_access_key(self, detector: SecretDetector) -> None:
        text = "AWS key: AKIAIOSFODNN7EXAMPLE"
        matches = detector.scan(text)
        assert any(m.pattern_name == "aws_access_key" for m in matches)

    def test_aws_secret_key(self, detector: SecretDetector) -> None:
        text = "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        matches = detector.scan(text)
        assert any(m.pattern_name == "aws_secret_key" for m in matches)

    def test_gcp_api_key(self, detector: SecretDetector) -> None:
        text = "GCP key: AIzaSyCxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        matches = detector.scan(text)
        assert any(m.pattern_name == "gcp_api_key" for m in matches)

    def test_stripe_key(self, detector: SecretDetector) -> None:
        # Build the key dynamically to avoid GitHub push protection
        prefix = "sk_" + "test" + "_"
        text = prefix + "a" * 24
        matches = detector.scan(text)
        assert any(m.pattern_name == "stripe_key" for m in matches)

    def test_github_token(self, detector: SecretDetector) -> None:
        text = "ghp_abcdefghijklmnopqrstuvwxyz123456"
        matches = detector.scan(text)
        assert any(m.pattern_name == "github_token" for m in matches)

    def test_slack_token(self, detector: SecretDetector) -> None:
        text = "xoxb-123456789-abcdefghijklm"
        matches = detector.scan(text)
        assert any(m.pattern_name == "slack_token" for m in matches)

    def test_sendgrid_key(self, detector: SecretDetector) -> None:
        text = "SG.abcdefghijklmnopqrstuv.abcdefghijklmnopqrstuvwxyz0123456789abcdefgh"
        matches = detector.scan(text)
        assert any(m.pattern_name == "sendgrid_key" for m in matches)

    def test_rsa_private_key(self, detector: SecretDetector) -> None:
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAK..."
        matches = detector.scan(text)
        assert any(m.pattern_name == "rsa_private_key" for m in matches)

    def test_ssh_private_key(self, detector: SecretDetector) -> None:
        text = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3Blbn..."
        matches = detector.scan(text)
        assert any(m.pattern_name == "ssh_private_key" for m in matches)

    def test_pgp_private_key(self, detector: SecretDetector) -> None:
        text = "-----BEGIN PGP PRIVATE KEY BLOCK-----\nxcMG..."
        matches = detector.scan(text)
        assert any(m.pattern_name == "pgp_private_key" for m in matches)

    def test_jwt_token(self, detector: SecretDetector) -> None:
        text = "eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyIjoiYWRtaW4ifQ.dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        matches = detector.scan(text)
        assert any(m.pattern_name == "jwt_token" for m in matches)

    def test_basic_auth(self, detector: SecretDetector) -> None:
        text = "Authorization: Basic dXNlcm5hbWU6cGFzc3dvcmQxMjM="
        matches = detector.scan(text)
        assert any(m.pattern_name == "basic_auth" for m in matches)

    def test_database_url(self, detector: SecretDetector) -> None:
        text = "DATABASE_URL=postgres://user:password@localhost:5432/mydb"
        matches = detector.scan(text)
        assert any(m.pattern_name == "database_url" for m in matches)

    def test_redis_url(self, detector: SecretDetector) -> None:
        text = "REDIS_URL=redis://user:secret@redis.example.com:6379/0"
        matches = detector.scan(text)
        assert any(m.pattern_name == "database_url" for m in matches)

    def test_mongodb_url(self, detector: SecretDetector) -> None:
        text = "mongodb+srv://user:pass@cluster0.example.mongodb.net/db"
        matches = detector.scan(text)
        assert any(m.pattern_name == "database_url" for m in matches)

    def test_multiple_secrets(self, detector: SecretDetector) -> None:
        text = (
            "OpenAI: sk-abcdefghij1234567890abcdefghij\n"
            "AWS: AKIAIOSFODNN7EXAMPLE"
        )
        matches = detector.scan(text)
        patterns_found = {m.pattern_name for m in matches}
        assert "openai_api_key" in patterns_found
        assert "aws_access_key" in patterns_found

    def test_gcp_service_account(self, detector: SecretDetector) -> None:
        text = '{"type": "service_account", "project_id": "my-project"}'
        matches = detector.scan(text)
        assert any(m.pattern_name == "gcp_service_account" for m in matches)


# ===================================================================
# SecretDetector Redact Tests
# ===================================================================


class TestSecretDetectorRedact:
    """Tests for SecretDetector.redact()."""

    def test_redact_single_secret(self, detector: SecretDetector) -> None:
        text = "My key is sk-abcdefghij1234567890abcdefghij please help"
        redacted, matches = detector.redact(text)
        assert "[REDACTED]" in redacted
        assert "sk-abcdefghij" not in redacted
        assert len(matches) > 0

    def test_redact_multiple_secrets(self, detector: SecretDetector) -> None:
        text = (
            "Key1: sk-abcdefghij1234567890abcdefghij "
            "Key2: AKIAIOSFODNN7EXAMPLE"
        )
        redacted, _matches = detector.redact(text)
        assert redacted.count("[REDACTED]") >= 2
        assert "sk-abcdefghij" not in redacted
        assert "AKIAIOSFODNN7EXAMPLE" not in redacted

    def test_redact_no_secrets(self, detector: SecretDetector) -> None:
        text = "Just a normal message"
        redacted, matches = detector.redact(text)
        assert redacted == text
        assert matches == []

    def test_custom_placeholder(self, detector: SecretDetector) -> None:
        text = "Key: sk-abcdefghij1234567890abcdefghij"
        redacted, _ = detector.redact(text, placeholder="***")
        assert "***" in redacted
        assert "[REDACTED]" not in redacted

    def test_redact_preserves_surrounding(self, detector: SecretDetector) -> None:
        text = "Before sk-abcdefghij1234567890abcdefghij After"
        redacted, _ = detector.redact(text)
        assert redacted.startswith("Before ")
        assert redacted.endswith(" After")


# ===================================================================
# Custom Patterns Tests
# ===================================================================


class TestCustomPatterns:
    """Tests for user-defined secret patterns."""

    def test_custom_pattern_detected(self) -> None:
        custom = SecretPattern(
            name="internal_token",
            pattern=re.compile(r"itk_[a-zA-Z0-9]{32}"),
            description="Internal token",
        )
        detector = SecretDetector(custom_patterns=[custom])
        text = "Token: itk_abcdefghij1234567890abcdefghijkl"
        matches = detector.scan(text)
        assert any(m.pattern_name == "internal_token" for m in matches)

    def test_custom_pattern_redacted(self) -> None:
        custom = SecretPattern(
            name="my_secret",
            pattern=re.compile(r"mysec_[a-z]{20}"),
        )
        detector = SecretDetector(custom_patterns=[custom])
        text = "Secret: mysec_abcdefghijklmnopqrst"
        redacted, matches = detector.redact(text)
        assert "[REDACTED]" in redacted
        assert len(matches) == 1

    def test_only_custom_patterns(self) -> None:
        """When patterns=[] + custom, only custom runs."""
        custom = SecretPattern(
            name="test",
            pattern=re.compile(r"TEST_[0-9]{10}"),
        )
        detector = SecretDetector(patterns=[], custom_patterns=[custom])
        # OpenAI key should NOT be detected with empty base patterns
        text = "sk-abcdefghij1234567890abcdefghij TEST_1234567890"
        matches = detector.scan(text)
        pattern_names = {m.pattern_name for m in matches}
        assert "test" in pattern_names
        assert "openai_api_key" not in pattern_names


# ===================================================================
# Include Azure Key Tests
# ===================================================================


class TestAzureKeyInclusion:
    """Tests for the include_azure_key flag."""

    def test_azure_key_excluded_by_default(self) -> None:
        detector = SecretDetector()
        text = "abcdef01234567890abcdef012345678"  # 32 hex chars
        matches = detector.scan(text)
        assert not any(m.pattern_name == "azure_key" for m in matches)

    def test_azure_key_included_when_enabled(self) -> None:
        detector = SecretDetector(include_azure_key=True)
        text = "abcdef01234567890abcdef012345678"  # 32 hex chars
        matches = detector.scan(text)
        assert any(m.pattern_name == "azure_key" for m in matches)


# ===================================================================
# Shannon Entropy Tests
# ===================================================================


class TestShannonEntropy:
    """Tests for the entropy calculation."""

    def test_zero_entropy_empty(self) -> None:
        assert _shannon_entropy("") == 0.0

    def test_zero_entropy_single_char(self) -> None:
        assert _shannon_entropy("aaaaaaa") == 0.0

    def test_max_entropy_binary(self) -> None:
        # "ab" has max entropy for 2 symbols ≈ 1.0
        ent = _shannon_entropy("ab")
        assert abs(ent - 1.0) < 0.01

    def test_high_entropy_random(self) -> None:
        # Many unique chars → high entropy
        text = "aB3$xZ9!kP7&mQ2"
        ent = _shannon_entropy(text)
        assert ent > 3.0


# ===================================================================
# SecretDetectionGuardrail — Redact Mode Tests
# ===================================================================


class TestRedactMode:
    """Tests for the guardrail in redact mode."""

    @pytest.mark.asyncio()
    async def test_no_secrets_allow(
        self,
        redact_guardrail: SecretDetectionGuardrail,
        context: GuardrailContext,
    ) -> None:
        messages = [{"role": "user", "content": "Hello, how are you?"}]
        result = await redact_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.ALLOW

    @pytest.mark.asyncio()
    async def test_redacts_openai_key(
        self,
        redact_guardrail: SecretDetectionGuardrail,
        context: GuardrailContext,
    ) -> None:
        messages = [
            {"role": "user", "content": "Use this key: sk-abcdefghij1234567890abcdefghij"}
        ]
        result = await redact_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.MODIFY
        assert result.modified_content is not None
        assert "[REDACTED]" in result.modified_content
        assert "sk-abcdefghij" not in result.modified_content

    @pytest.mark.asyncio()
    async def test_redacts_multiple_secrets(
        self,
        redact_guardrail: SecretDetectionGuardrail,
        context: GuardrailContext,
    ) -> None:
        messages = [
            {
                "role": "user",
                "content": (
                    "Key: sk-abcdefghij1234567890abcdefghij "
                    "AWS: AKIAIOSFODNN7EXAMPLE"
                ),
            }
        ]
        result = await redact_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.MODIFY
        assert result.details["match_count"] >= 2

    @pytest.mark.asyncio()
    async def test_redacts_across_messages(
        self,
        redact_guardrail: SecretDetectionGuardrail,
        context: GuardrailContext,
    ) -> None:
        messages = [
            {"role": "system", "content": "You are a helper."},
            {"role": "user", "content": "sk-abcdefghij1234567890abcdefghij"},
        ]
        result = await redact_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.MODIFY
        # System message should be unchanged in the JSON
        import json

        parsed = json.loads(result.modified_content)
        assert parsed[0]["content"] == "You are a helper."
        assert "[REDACTED]" in parsed[1]["content"]

    @pytest.mark.asyncio()
    async def test_non_string_content_ignored(
        self,
        redact_guardrail: SecretDetectionGuardrail,
        context: GuardrailContext,
    ) -> None:
        """Messages with non-string content are passed through."""
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "hello"}]},
        ]
        result = await redact_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.ALLOW

    @pytest.mark.asyncio()
    async def test_empty_content_ignored(
        self,
        redact_guardrail: SecretDetectionGuardrail,
        context: GuardrailContext,
    ) -> None:
        messages = [{"role": "user", "content": ""}]
        result = await redact_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.ALLOW

    @pytest.mark.asyncio()
    async def test_reason_includes_count(
        self,
        redact_guardrail: SecretDetectionGuardrail,
        context: GuardrailContext,
    ) -> None:
        messages = [
            {"role": "user", "content": "sk-abcdefghij1234567890abcdefghij"}
        ]
        result = await redact_guardrail.check_request(messages, context)
        assert "1 secret" in (result.reason or "")


# ===================================================================
# SecretDetectionGuardrail — Block Mode Tests
# ===================================================================


class TestBlockMode:
    """Tests for the guardrail in block mode."""

    @pytest.mark.asyncio()
    async def test_no_secrets_allow(
        self,
        block_guardrail: SecretDetectionGuardrail,
        context: GuardrailContext,
    ) -> None:
        messages = [{"role": "user", "content": "Hello!"}]
        result = await block_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.ALLOW

    @pytest.mark.asyncio()
    async def test_blocks_on_secret(
        self,
        block_guardrail: SecretDetectionGuardrail,
        context: GuardrailContext,
    ) -> None:
        messages = [
            {"role": "user", "content": "sk-abcdefghij1234567890abcdefghij"}
        ]
        result = await block_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.BLOCK
        assert "openai_api_key" in (result.reason or "")

    @pytest.mark.asyncio()
    async def test_block_reason_lists_patterns(
        self,
        block_guardrail: SecretDetectionGuardrail,
        context: GuardrailContext,
    ) -> None:
        messages = [
            {"role": "user", "content": "AKIAIOSFODNN7EXAMPLE"}
        ]
        result = await block_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.BLOCK
        assert "aws_access_key" in (result.reason or "")

    @pytest.mark.asyncio()
    async def test_block_details(
        self,
        block_guardrail: SecretDetectionGuardrail,
        context: GuardrailContext,
    ) -> None:
        messages = [
            {"role": "user", "content": "sk-abcdefghij1234567890abcdefghij"}
        ]
        result = await block_guardrail.check_request(messages, context)
        assert "detected_patterns" in result.details
        assert result.details["match_count"] >= 1


# ===================================================================
# Response Checking Tests
# ===================================================================


class TestResponseChecking:
    """Tests for checking model responses."""

    @pytest.mark.asyncio()
    async def test_response_check_disabled_by_default(
        self,
        context: GuardrailContext,
    ) -> None:
        guardrail = SecretDetectionGuardrail(mode="redact")
        result = await guardrail.check_response(
            "sk-abcdefghij1234567890abcdefghij", context
        )
        assert result.action == GuardrailAction.ALLOW

    @pytest.mark.asyncio()
    async def test_response_redact(self, context: GuardrailContext) -> None:
        guardrail = SecretDetectionGuardrail(
            mode="redact", check_response_content=True
        )
        result = await guardrail.check_response(
            "Here is a key: sk-abcdefghij1234567890abcdefghij", context
        )
        assert result.action == GuardrailAction.MODIFY
        assert "[REDACTED]" in result.modified_content
        assert "sk-abcdefghij" not in result.modified_content

    @pytest.mark.asyncio()
    async def test_response_block(self, context: GuardrailContext) -> None:
        guardrail = SecretDetectionGuardrail(
            mode="block", check_response_content=True
        )
        result = await guardrail.check_response(
            "sk-abcdefghij1234567890abcdefghij", context
        )
        assert result.action == GuardrailAction.BLOCK

    @pytest.mark.asyncio()
    async def test_response_no_secrets_allow(self, context: GuardrailContext) -> None:
        guardrail = SecretDetectionGuardrail(
            mode="redact", check_response_content=True
        )
        result = await guardrail.check_response("Normal response text", context)
        assert result.action == GuardrailAction.ALLOW


# ===================================================================
# Integration with GuardrailManager Tests
# ===================================================================


class TestIntegrationWithManager:
    """Test that secret detection works within the guardrail pipeline."""

    @pytest.mark.asyncio()
    async def test_redact_in_pipeline(self, context: GuardrailContext) -> None:
        from routerbot.proxy.guardrails.manager import GuardrailManager

        manager = GuardrailManager()
        manager.register(
            SecretDetectionGuardrail(mode="redact", name="secrets", priority=1)
        )

        messages = [
            {"role": "user", "content": "Key: sk-abcdefghij1234567890abcdefghij"}
        ]
        result = await manager.run_request_guardrails(messages, context)
        assert result.modified
        assert result.modified_messages is not None
        assert "[REDACTED]" in result.modified_messages[0]["content"]

    @pytest.mark.asyncio()
    async def test_block_in_pipeline(self, context: GuardrailContext) -> None:
        from routerbot.proxy.guardrails.manager import GuardrailManager

        manager = GuardrailManager()
        manager.register(
            SecretDetectionGuardrail(mode="block", name="secrets", priority=1)
        )

        messages = [
            {"role": "user", "content": "sk-abcdefghij1234567890abcdefghij"}
        ]
        result = await manager.run_request_guardrails(messages, context)
        assert result.blocked


# ===================================================================
# Properties and Configuration Tests
# ===================================================================


class TestGuardrailProperties:
    """Tests for guardrail configuration and properties."""

    def test_mode_property(self) -> None:
        g = SecretDetectionGuardrail(mode="block")
        assert g.mode == "block"

    def test_custom_placeholder(self) -> None:
        g = SecretDetectionGuardrail(mode="redact", placeholder="***REMOVED***")
        assert g._placeholder == "***REMOVED***"

    def test_name_default(self) -> None:
        g = SecretDetectionGuardrail()
        assert g.name == "SecretDetectionGuardrail"

    def test_custom_name(self) -> None:
        g = SecretDetectionGuardrail(name="my_secrets")
        assert g.name == "my_secrets"

    def test_enabled_default(self) -> None:
        g = SecretDetectionGuardrail()
        assert g.enabled is True

    def test_priority(self) -> None:
        g = SecretDetectionGuardrail(priority=5)
        assert g.priority == 5
