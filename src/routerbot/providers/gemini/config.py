"""Google Gemini / Vertex AI configuration constants."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Google AI Studio (Gemini API)
# ---------------------------------------------------------------------------

GEMINI_DEFAULT_BASE = "https://generativelanguage.googleapis.com"
GEMINI_API_VERSION = "v1beta"

# ---------------------------------------------------------------------------
# Google Vertex AI
# ---------------------------------------------------------------------------

VERTEX_DEFAULT_REGION = "us-central1"
VERTEX_API_VERSION = "v1"


def build_vertex_base_url(project: str, region: str = VERTEX_DEFAULT_REGION) -> str:
    """Return the Vertex AI base URL for a project + region."""
    return (
        f"https://{region}-aiplatform.googleapis.com/{VERTEX_API_VERSION}"
        f"/projects/{project}/locations/{region}/publishers/google"
    )


# ---------------------------------------------------------------------------
# Model catalogs
# ---------------------------------------------------------------------------

GEMINI_MODELS: frozenset[str] = frozenset(
    {
        "gemini-2.5-pro-preview-05-06",
        "gemini-2.5-flash-preview-04-17",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.0-pro-exp",
        "gemini-1.5-pro",
        "gemini-1.5-pro-002",
        "gemini-1.5-flash",
        "gemini-1.5-flash-002",
        "gemini-1.5-flash-8b",
        "gemini-1.0-pro",
        "gemini-pro",
    }
)

EMBEDDING_MODELS: frozenset[str] = frozenset(
    {
        "text-embedding-004",
        "text-embedding-005",
        "embedding-001",
    }
)

# ---------------------------------------------------------------------------
# Finish reason mapping (Gemini → OpenAI)
# ---------------------------------------------------------------------------

FINISH_REASON_MAP: dict[str, str] = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
    "LANGUAGE": "stop",
    "OTHER": "stop",
    "BLOCKLIST": "content_filter",
    "PROHIBITED_CONTENT": "content_filter",
    "SPII": "content_filter",
    "MALFORMED_FUNCTION_CALL": "stop",
    "TOOL_CALLS": "tool_calls",
    "FINISH_REASON_UNSPECIFIED": "stop",
}
