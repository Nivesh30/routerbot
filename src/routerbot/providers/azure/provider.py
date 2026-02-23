"""Azure OpenAI provider implementation.

Azure OpenAI uses the same API format as OpenAI but with:
- A deployment-specific URL structure
- ``api-key`` header instead of ``Authorization: Bearer``
- A required ``api-version`` query parameter on every request
- Optional Azure AD authentication
"""

from __future__ import annotations

from typing import Any

import httpx

from routerbot.providers.azure.config import DEFAULT_API_VERSION, build_azure_base_url
from routerbot.providers.openai.provider import OpenAIProvider
from routerbot.providers.registry import register_provider


class AzureOpenAIProvider(OpenAIProvider):
    """Provider for Azure OpenAI deployments.

    Azure OpenAI exposes the same models as OpenAI but routes requests
    through your own Azure resource, with deployment-based URL routing
    and ``api-key`` / Azure AD authentication.

    Parameters
    ----------
    resource_name:
        The Azure OpenAI resource name (the subdomain of
        ``.openai.azure.com``), e.g. ``"my-resource"``.
    deployment_name:
        The deployment name configured in Azure OpenAI Studio, e.g.
        ``"gpt-4o"`` or ``"my-gpt4o-deployment"``.
    api_key:
        Azure API key.  Mutually exclusive with ``azure_ad_token``.
    azure_ad_token:
        Pre-obtained Azure AD bearer token.  When provided, ``api_key``
        is ignored and ``Authorization: Bearer …`` is used instead of
        the ``api-key`` header.
    api_version:
        The Azure OpenAI API version string, e.g. ``"2024-10-21"``.
        Defaults to :data:`~routerbot.providers.azure.config.DEFAULT_API_VERSION`.
    api_base:
        Override the generated base URL entirely (useful for testing or
        self-hosted Azure Stack endpoints).
    """

    provider_name: str = "azure"

    def __init__(
        self,
        resource_name: str,
        deployment_name: str,
        *,
        api_key: str | None = None,
        azure_ad_token: str | None = None,
        api_version: str = DEFAULT_API_VERSION,
        api_base: str | None = None,
        **kwargs: Any,
    ) -> None:
        if api_key is None and azure_ad_token is None:
            msg = "Either api_key or azure_ad_token must be provided for AzureOpenAIProvider"
            raise ValueError(msg)

        self.resource_name = resource_name
        self.deployment_name = deployment_name
        self.api_version = api_version
        self.azure_ad_token = azure_ad_token

        computed_base = api_base or build_azure_base_url(resource_name, deployment_name)

        super().__init__(
            api_key=api_key,
            api_base=computed_base,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Auth header override
    # ------------------------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        """Build Azure-specific headers.

        Azure uses ``api-key`` for API-key auth and
        ``Authorization: Bearer <token>`` for Azure AD auth.
        The parent class ``Authorization: Bearer`` header is replaced.
        """
        # Start from base without the default Authorization header
        headers: dict[str, str] = {
            "User-Agent": "RouterBot/0.1",
            "Accept": "application/json",
        }

        if self.azure_ad_token:
            headers["Authorization"] = f"Bearer {self.azure_ad_token}"
        elif self.api_key:
            headers["api-key"] = self.api_key

        headers.update(self.custom_headers)
        return headers

    # ------------------------------------------------------------------
    # HTTP client with api-version default param
    # ------------------------------------------------------------------

    @property
    def client(self) -> httpx.AsyncClient:
        """Return (or lazily create) an httpx client with api-version param."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.api_base,
                headers=self._build_headers(),
                params={"api-version": self.api_version},
                timeout=self._timeout,
                follow_redirects=True,
            )
        return self._client

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Check if the Azure OpenAI deployment is reachable.

        Uses a non-streaming chat completion with a minimal prompt.
        Azure doesn't expose a /models list at the deployment level.
        """
        try:
            resp = await self.client.get("")  # GET base URL is harmless
            # 200, 404, or 405 all indicate the service is up
            return resp.status_code < 500
        except httpx.HTTPError:
            return False


register_provider("azure", AzureOpenAIProvider)
