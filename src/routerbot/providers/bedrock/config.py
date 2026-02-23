"""AWS Bedrock configuration constants."""

from __future__ import annotations

# Default AWS region
DEFAULT_REGION = "us-east-1"

# Bedrock Runtime service name (used in SigV4 signing)
BEDROCK_SERVICE = "bedrock-runtime"

# Base URL pattern for Bedrock Runtime
BEDROCK_BASE_URL_TEMPLATE = "https://bedrock-runtime.{region}.amazonaws.com"


def build_bedrock_base_url(region: str = DEFAULT_REGION) -> str:
    """Build the Bedrock Runtime endpoint URL for a region."""
    return BEDROCK_BASE_URL_TEMPLATE.format(region=region)


# ── Model ID sets ─────────────────────────────────────────────────────────

# Claude models available on Bedrock (Anthropic)
ANTHROPIC_MODELS: frozenset[str] = frozenset(
    {
        "anthropic.claude-opus-4-20250514-v1:0",
        "anthropic.claude-sonnet-4-20250514-v1:0",
        "anthropic.claude-sonnet-4-5-20251029-v1:0",
        "anthropic.claude-3-5-sonnet-20241022-v2:0",
        "anthropic.claude-3-5-haiku-20241022-v1:0",
        "anthropic.claude-3-opus-20240229-v1:0",
        "anthropic.claude-3-haiku-20240307-v1:0",
        "anthropic.claude-3-sonnet-20240229-v1:0",
    }
)

# Meta Llama models
META_MODELS: frozenset[str] = frozenset(
    {
        "meta.llama3-8b-instruct-v1:0",
        "meta.llama3-70b-instruct-v1:0",
        "meta.llama3-1-8b-instruct-v1:0",
        "meta.llama3-1-70b-instruct-v1:0",
        "meta.llama3-1-405b-instruct-v1:0",
        "meta.llama3-2-1b-instruct-v1:0",
        "meta.llama3-2-3b-instruct-v1:0",
        "meta.llama3-2-11b-instruct-v1:0",
        "meta.llama3-2-90b-instruct-v1:0",
        "meta.llama3-3-70b-instruct-v1:0",
    }
)

# Amazon Titan models
AMAZON_MODELS: frozenset[str] = frozenset(
    {
        "amazon.titan-text-premier-v1:0",
        "amazon.titan-text-express-v1",
        "amazon.titan-text-lite-v1",
        "amazon.titan-embed-text-v2:0",
        "amazon.titan-embed-text-v1",
    }
)

# Amazon Nova models
NOVA_MODELS: frozenset[str] = frozenset(
    {
        "amazon.nova-pro-v1:0",
        "amazon.nova-lite-v1:0",
        "amazon.nova-micro-v1:0",
    }
)

# Mistral models on Bedrock
MISTRAL_MODELS: frozenset[str] = frozenset(
    {
        "mistral.mistral-7b-instruct-v0:2",
        "mistral.mixtral-8x7b-instruct-v0:1",
        "mistral.mistral-large-2402-v1:0",
        "mistral.mistral-large-2407-v1:0",
    }
)

# All Converse API supported models
CONVERSE_MODELS: frozenset[str] = ANTHROPIC_MODELS | META_MODELS | AMAZON_MODELS | NOVA_MODELS | MISTRAL_MODELS

# Embedding models (Titan)
EMBEDDING_MODELS: frozenset[str] = frozenset(
    {
        "amazon.titan-embed-text-v2:0",
        "amazon.titan-embed-text-v1",
    }
)

# Stop reason mapping: Bedrock → OpenAI finish_reason
FINISH_REASON_MAP: dict[str, str] = {
    "end_turn": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "stop_sequence": "stop",
    "guardrail_intervened": "content_filter",
    "content_filtered": "content_filter",
}
