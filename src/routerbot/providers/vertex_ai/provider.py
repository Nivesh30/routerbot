"""Google Vertex AI provider implementation.

Subclasses :class:`GeminiProvider` and overrides URL construction and
authentication to work with the Vertex AI endpoint (OAuth2 Bearer token),
rather than Gemini AI Studio (API key query parameter).

Authentication
--------------
Vertex AI requires a valid OAuth2 access token.  You can obtain one via:

  1. A pre-generated token:  ``access_token="ya29...."``
  2. gcloud CLI:             ``gcloud auth print-access-token``
  3. Environment variable:   ``GOOGLE_ACCESS_TOKEN=...``

Full service-account authentication (JSON key → JWT → token exchange) is
not built in to avoid adding heavyweight dependencies.  If you need that,
generate the token externally and pass it in, or use the
``google-auth`` package before creating the provider.
"""

from __future__ import annotations

from typing import Any

from routerbot.providers.gemini.config import (
    VERTEX_DEFAULT_REGION,
    build_vertex_base_url,
)
from routerbot.providers.gemini.provider import GeminiProvider
from routerbot.providers.registry import register_provider


class VertexAIProvider(GeminiProvider):
    """Provider for Google Vertex AI (Gemini on GCP).

    Uses the Vertex AI ``generateContent`` endpoint with Bearer token
    authentication instead of a Gemini API key query parameter.

    Parameters
    ----------
    project_id:
        Google Cloud project ID (e.g. ``"my-gcp-project"``).
    access_token:
        A valid OAuth2 access token.  Use ``gcloud auth print-access-token``
        or the ``google-auth`` library to obtain one.
    region:
        GCP region for the Vertex AI endpoint (default ``"us-central1"``).
    api_base:
        Override the Vertex AI base URL (useful for testing).
    """

    provider_name: str = "vertex_ai"

    def __init__(
        self,
        project_id: str,
        access_token: str,
        *,
        region: str = VERTEX_DEFAULT_REGION,
        api_base: str | None = None,
        **kwargs: Any,
    ) -> None:
        computed_base = api_base or build_vertex_base_url(project_id, region)
        super().__init__(
            api_key=access_token,  # stored as api_key in BaseProvider
            api_base=computed_base,
            **kwargs,
        )
        self.project_id = project_id
        self.region = region

    # ------------------------------------------------------------------
    # Override auth: Bearer token in header, no query param
    # ------------------------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        return {
            "User-Agent": "RouterBot/0.1",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def _base_params(self) -> dict[str, str]:
        """Vertex AI uses auth headers; no query parameters needed."""
        return {}

    # ------------------------------------------------------------------
    # Override URL construction for Vertex AI endpoint format
    # ------------------------------------------------------------------

    def _chat_path(self, model: str, streaming: bool = False) -> str:
        endpoint = "streamGenerateContent" if streaming else "generateContent"
        return f"/models/{model}:{endpoint}"

    def _embed_path(self, model: str) -> str:
        return f"/models/{model}:embedContent"

    # ------------------------------------------------------------------
    # Health check via Vertex AI model list
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Use Vertex AI model list endpoint as health probe."""
        try:
            client = self.client
            resp = await client.get(
                f"/models",  # noqa: F541
                timeout=5.0,
            )
            return resp.status_code < 500
        except Exception:
            return False


register_provider("vertex_ai", VertexAIProvider)
