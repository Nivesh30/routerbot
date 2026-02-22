"""Enumerations used throughout RouterBot.

All enums live here to avoid circular imports. Enum members use lowercase
values to match provider API conventions.
"""

from __future__ import annotations

from enum import StrEnum


class Provider(StrEnum):
    """Supported LLM providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE = "azure"
    AWS_BEDROCK = "bedrock"
    VERTEX_AI = "vertex_ai"
    GOOGLE_AI = "google_ai"
    COHERE = "cohere"
    MISTRAL = "mistral"
    GROQ = "groq"
    TOGETHER = "together_ai"
    DEEPSEEK = "deepseek"
    FIREWORKS = "fireworks_ai"
    OLLAMA = "ollama"
    HUGGINGFACE = "huggingface"
    OPENROUTER = "openrouter"
    CUSTOM = "custom"


class Role(StrEnum):
    """Message roles in a conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    DEVELOPER = "developer"
    FUNCTION = "function"  # deprecated but still accepted


class FinishReason(StrEnum):
    """Reasons why the model stopped generating."""

    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    FUNCTION_CALL = "function_call"  # deprecated


class RoutingStrategy(StrEnum):
    """Load-balancing strategy for routing requests across deployments."""

    ROUND_ROBIN = "round-robin"
    WEIGHTED_ROUND_ROBIN = "weighted-round-robin"
    LEAST_LATENCY = "latency-based"
    COST_BASED = "cost-based"
    RANDOM = "random"
    LEAST_CONNECTIONS = "least-connections"


class CacheType(StrEnum):
    """Supported cache backends."""

    REDIS = "redis"
    MEMORY = "memory"
    NONE = "none"


class ImageSize(StrEnum):
    """Supported image generation sizes."""

    S_256 = "256x256"
    S_512 = "512x512"
    S_1024 = "1024x1024"
    S_1792_1024 = "1792x1024"
    S_1024_1792 = "1024x1792"


class ImageQuality(StrEnum):
    """Image generation quality levels."""

    STANDARD = "standard"
    HD = "hd"


class ImageStyle(StrEnum):
    """Image generation styles."""

    VIVID = "vivid"
    NATURAL = "natural"


class ImageResponseFormat(StrEnum):
    """Image response encoding format."""

    URL = "url"
    B64_JSON = "b64_json"


class AudioVoice(StrEnum):
    """Text-to-speech voice options."""

    ALLOY = "alloy"
    ECHO = "echo"
    FABLE = "fable"
    ONYX = "onyx"
    NOVA = "nova"
    SHIMMER = "shimmer"


class AudioResponseFormat(StrEnum):
    """Audio output format."""

    MP3 = "mp3"
    OPUS = "opus"
    AAC = "aac"
    FLAC = "flac"
    WAV = "wav"
    PCM = "pcm"


class EmbeddingEncodingFormat(StrEnum):
    """Embedding vector encoding format."""

    FLOAT = "float"
    BASE64 = "base64"
