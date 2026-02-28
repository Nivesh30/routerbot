"""Tests for token counting, cost calculation, and model registry (Task 1.6)."""

from __future__ import annotations

import pytest

from routerbot.core.cost import calculate_cost, calculate_embedding_cost, calculate_image_cost
from routerbot.core.enums import Role
from routerbot.core.model_registry import (
    get_all_models,
    get_model_info,
    register_custom_model,
    reset_registry,
)
from routerbot.core.tokens import (
    _estimate_tokens,
    count_message_tokens,
    count_tokens,
)
from routerbot.core.types import Message, Usage

# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture(autouse=True)
def _reset_model_registry() -> None:
    """Reset model registry before each test."""
    reset_registry()


# ===================================================================
# Token counting
# ===================================================================


class TestCountTokens:
    """count_tokens function."""

    def test_simple_text_gpt4o(self) -> None:
        """Token count for simple text with gpt-4o tokenizer."""
        count = count_tokens("Hello, world!", "gpt-4o")
        assert isinstance(count, int)
        assert count > 0
        # tiktoken: "Hello, world!" ≈ 4 tokens with o200k_base
        assert count == 4

    def test_empty_string(self) -> None:
        count = count_tokens("", "gpt-4o")
        assert count == 0

    def test_longer_text(self) -> None:
        text = "The quick brown fox jumps over the lazy dog. " * 10
        count = count_tokens(text, "gpt-4o")
        assert count > 50

    def test_gpt35_turbo(self) -> None:
        count = count_tokens("Hello, world!", "gpt-3.5-turbo")
        assert isinstance(count, int)
        assert count > 0

    def test_versioned_model_name(self) -> None:
        """gpt-4o-2024-08-06 should resolve to the gpt-4o tokenizer."""
        count1 = count_tokens("Hello", "gpt-4o")
        count2 = count_tokens("Hello", "gpt-4o-2024-08-06")
        assert count1 == count2

    def test_unknown_model_uses_fallback(self) -> None:
        """Unknown models use character-based estimation."""
        count = count_tokens("Hello, this is a test string.", "unknown-model-xyz")
        assert count > 0
        # Fallback: ~4 chars per token → 30 chars ≈ 7 tokens
        assert count == _estimate_tokens("Hello, this is a test string.")

    def test_cl100k_encoding(self) -> None:
        count = count_tokens("Hello", "gpt-4-turbo")
        assert isinstance(count, int)
        assert count > 0


class TestCountMessageTokens:
    """count_message_tokens function."""

    def test_single_user_message(self) -> None:
        messages = [Message(role=Role.USER, content="Hello")]
        count = count_message_tokens(messages, "gpt-4o")
        assert count > 0
        # 1 message x 4 overhead + content tokens + role token + 3 reply priming
        assert count >= 8

    def test_multi_turn_conversation(self) -> None:
        messages = [
            Message(role=Role.SYSTEM, content="You are a helpful assistant."),
            Message(role=Role.USER, content="What is Python?"),
            Message(role=Role.ASSISTANT, content="Python is a programming language."),
        ]
        count = count_message_tokens(messages, "gpt-4o")
        assert count > 20

    def test_message_with_name(self) -> None:
        messages = [
            Message(role=Role.USER, content="Hello", name="Alice"),
        ]
        count = count_message_tokens(messages, "gpt-4o")
        assert count > 0

    def test_empty_messages(self) -> None:
        count = count_message_tokens([], "gpt-4o")
        assert count == 3  # just the reply priming

    def test_none_content(self) -> None:
        messages = [Message(role=Role.ASSISTANT, content=None)]
        count = count_message_tokens(messages, "gpt-4o")
        # Should still count role overhead + priming
        assert count >= 6


class TestEstimateTokens:
    """Fallback token estimation."""

    def test_basic_estimate(self) -> None:
        assert _estimate_tokens("Hello") == 1  # 5 chars / 4 = 1.25 → 1

    def test_longer_text(self) -> None:
        text = "a" * 100
        assert _estimate_tokens(text) == 25

    def test_empty_string(self) -> None:
        # max(1, 0) = 1
        assert _estimate_tokens("") == 1


# ===================================================================
# Model registry
# ===================================================================


class TestModelRegistry:
    """Model registry operations."""

    def test_get_known_model(self) -> None:
        info = get_model_info("gpt-4o")
        assert info is not None
        assert "input_cost_per_token" in info
        assert "max_input_tokens" in info
        assert info["max_input_tokens"] == 128000

    def test_get_unknown_model(self) -> None:
        info = get_model_info("nonexistent-model-xyz")
        assert info is None

    def test_prefix_matching(self) -> None:
        """gpt-4o-2024-08-06 should match gpt-4o entry."""
        info = get_model_info("gpt-4o-2024-08-06")
        assert info is not None
        assert info["max_input_tokens"] == 128000

    def test_provider_prefix_stripping(self) -> None:
        """openai/gpt-4o should strip the provider prefix."""
        info = get_model_info("openai/gpt-4o")
        assert info is not None

    def test_get_all_models(self) -> None:
        models = get_all_models()
        assert isinstance(models, dict)
        assert len(models) >= 40  # we defined ~45 models
        assert "gpt-4o" in models
        assert "claude-3-opus-20240229" in models

    def test_register_custom_model(self) -> None:
        register_custom_model(
            "my-custom-model",
            {
                "max_input_tokens": 4096,
                "input_cost_per_token": 1e-06,
                "output_cost_per_token": 2e-06,
            },
        )
        info = get_model_info("my-custom-model")
        assert info is not None
        assert info["max_input_tokens"] == 4096

    def test_register_overwrites(self) -> None:
        register_custom_model("gpt-4o", {"input_cost_per_token": 999.0})
        info = get_model_info("gpt-4o")
        assert info is not None
        assert info["input_cost_per_token"] == 999.0

    def test_comment_key_excluded(self) -> None:
        """Keys starting with _ should not appear in the registry."""
        models = get_all_models()
        assert "_comment" not in models

    def test_claude_models(self) -> None:
        info = get_model_info("claude-sonnet-4-20250514")
        assert info is not None
        assert info["max_input_tokens"] == 200000

    def test_gemini_models(self) -> None:
        info = get_model_info("gemini-2.5-pro")
        assert info is not None
        assert info["max_input_tokens"] == 1048576

    def test_embedding_model(self) -> None:
        info = get_model_info("text-embedding-3-small")
        assert info is not None
        assert info.get("mode") == "embedding"

    def test_image_model(self) -> None:
        info = get_model_info("dall-e-3")
        assert info is not None
        assert info.get("mode") == "image_generation"


# ===================================================================
# Cost calculation
# ===================================================================


class TestCalculateCost:
    """calculate_cost function."""

    def test_gpt4o_cost(self) -> None:
        """1000 prompt tokens + 500 completion tokens for gpt-4o."""
        usage = Usage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        cost = calculate_cost("gpt-4o", usage)
        # 1000 * 2.5e-6 + 500 * 10e-6 = 0.0025 + 0.005 = 0.0075
        assert abs(cost - 0.0075) < 1e-6

    def test_gpt4o_mini_cost(self) -> None:
        usage = Usage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        cost = calculate_cost("gpt-4o-mini", usage)
        # 1000 * 1.5e-7 + 500 * 6e-7 = 0.00015 + 0.0003 = 0.00045
        assert abs(cost - 0.00045) < 1e-8

    def test_claude_cost(self) -> None:
        usage = Usage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        cost = calculate_cost("claude-3-5-sonnet-20241022", usage)
        # 1000 * 3e-6 + 500 * 1.5e-5 = 0.003 + 0.0075 = 0.0105
        assert abs(cost - 0.0105) < 1e-6

    def test_unknown_model_returns_zero(self) -> None:
        usage = Usage(prompt_tokens=1000, completion_tokens=500)
        cost = calculate_cost("unknown-model-xyz", usage)
        assert cost == 0.0

    def test_zero_usage(self) -> None:
        usage = Usage()
        cost = calculate_cost("gpt-4o", usage)
        assert cost == 0.0

    def test_custom_cost_override(self) -> None:
        usage = Usage(prompt_tokens=100, completion_tokens=50)
        cost = calculate_cost(
            "whatever-model",
            usage,
            custom_input_cost=0.001,
            custom_output_cost=0.002,
        )
        # 100 * 0.001 + 50 * 0.002 = 0.1 + 0.1 = 0.2
        assert abs(cost - 0.2) < 1e-8

    def test_provider_prefixed_model(self) -> None:
        usage = Usage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        cost = calculate_cost("openai/gpt-4o", usage)
        assert cost > 0


class TestCalculateImageCost:
    """calculate_image_cost function."""

    def test_dalle3_standard(self) -> None:
        cost = calculate_image_cost("dall-e-3", "1024x1024", n=1)
        assert abs(cost - 0.04) < 1e-6

    def test_dalle3_large(self) -> None:
        cost = calculate_image_cost("dall-e-3", "1792x1024", n=2)
        assert abs(cost - 0.16) < 1e-6

    def test_unknown_model(self) -> None:
        cost = calculate_image_cost("unknown-image-model")
        assert cost == 0.0

    def test_unknown_size(self) -> None:
        cost = calculate_image_cost("dall-e-3", "999x999")
        assert cost == 0.0


class TestCalculateEmbeddingCost:
    """calculate_embedding_cost function."""

    def test_embedding_small(self) -> None:
        cost = calculate_embedding_cost("text-embedding-3-small", 1000)
        # 1000 * 2e-8 = 2e-5
        assert abs(cost - 2e-5) < 1e-10

    def test_embedding_large(self) -> None:
        cost = calculate_embedding_cost("text-embedding-3-large", 1000)
        # 1000 * 1.3e-7 = 1.3e-4
        assert abs(cost - 1.3e-4) < 1e-10

    def test_unknown_model(self) -> None:
        cost = calculate_embedding_cost("unknown-embedding", 1000)
        assert cost == 0.0
