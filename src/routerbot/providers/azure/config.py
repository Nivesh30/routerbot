"""Azure OpenAI configuration constants."""

from __future__ import annotations

# Azure OpenAI API version — can be overridden per-provider instance
DEFAULT_API_VERSION = "2024-10-21"

# All supported Azure API versions (for validation)
SUPPORTED_API_VERSIONS: frozenset[str] = frozenset(
    {
        "2024-10-21",
        "2024-09-01-preview",
        "2024-08-01-preview",
        "2024-07-01-preview",
        "2024-06-01",
        "2024-05-01-preview",
        "2024-04-01-preview",
        "2024-02-01",
        "2023-12-01-preview",
        "2023-09-01-preview",
        "2023-07-01-preview",
        "2023-06-01-preview",
        "2023-05-15",
    }
)


def build_azure_base_url(
    resource_name: str,
    deployment_name: str,
) -> str:
    """Build the Azure OpenAI base URL for a specific deployment.

    Parameters
    ----------
    resource_name:
        Azure OpenAI resource name (subdomain of openai.azure.com).
    deployment_name:
        The deployment name (set when deploying a model in Azure OpenAI Studio).

    Returns
    -------
    str
        Full base URL for the deployment, e.g.
        ``https://myresource.openai.azure.com/openai/deployments/my-gpt4o``.
    """
    resource = resource_name.rstrip("/")
    deployment = deployment_name.strip("/")
    return f"https://{resource}.openai.azure.com/openai/deployments/{deployment}"
