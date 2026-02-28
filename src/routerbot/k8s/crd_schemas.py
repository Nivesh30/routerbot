"""CRD schema generator for Kubernetes Custom Resource Definitions.

Generates OpenAPI v3 schemas from the Pydantic models, suitable for
inclusion in Kubernetes CRD YAML manifests.
"""

from __future__ import annotations

from typing import Any

from routerbot.k8s.models import (
    AutoscalingSpec,
    GatewaySpec,
    GatewayStatus,
    HealthCheckSpec,
    K8sOperatorConfig,
    KeySpec,
    KeyStatus,
    LLMGateway,
    LLMKey,
    LLMModel,
    LLMTeam,
    ModelSpec,
    ModelStatus,
    ResourceRequirements,
    TeamSpec,
    TeamStatus,
)

# ---------------------------------------------------------------------------
# Schema registry
# ---------------------------------------------------------------------------

_CRD_REGISTRY: dict[str, dict[str, Any]] = {}


def _register_crd(
    kind: str,
    *,
    group: str = "routerbot.io",
    version: str = "v1alpha1",
    plural: str,
    scope: str = "Namespaced",
    spec_model: type,
    status_model: type,
) -> dict[str, Any]:
    """Build and register a CRD schema definition."""
    spec_schema = _pydantic_to_openapi(spec_model)
    status_schema = _pydantic_to_openapi(status_model)

    crd: dict[str, Any] = {
        "apiVersion": "apiextensions.k8s.io/v1",
        "kind": "CustomResourceDefinition",
        "metadata": {
            "name": f"{plural}.{group}",
        },
        "spec": {
            "group": group,
            "names": {
                "kind": kind,
                "listKind": f"{kind}List",
                "plural": plural,
                "singular": kind.lower(),
                "shortNames": [kind[:3].lower()],
            },
            "scope": scope,
            "versions": [
                {
                    "name": version,
                    "served": True,
                    "storage": True,
                    "schema": {
                        "openAPIV3Schema": {
                            "type": "object",
                            "properties": {
                                "apiVersion": {"type": "string"},
                                "kind": {"type": "string"},
                                "metadata": {"type": "object"},
                                "spec": spec_schema,
                                "status": status_schema,
                            },
                        },
                    },
                    "subresources": {"status": {}},
                    "additionalPrinterColumns": [
                        {
                            "name": "Phase",
                            "type": "string",
                            "jsonPath": ".status.phase",
                        },
                        {
                            "name": "Age",
                            "type": "date",
                            "jsonPath": ".metadata.creationTimestamp",
                        },
                    ],
                },
            ],
        },
    }
    _CRD_REGISTRY[kind] = crd
    return crd


def _pydantic_to_openapi(model: type) -> dict[str, Any]:
    """Convert a Pydantic model to a simplified OpenAPI v3 schema."""
    schema = model.model_json_schema()
    return _convert_schema(schema)


def _convert_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively convert a JSON Schema to K8s-compatible OpenAPI subset."""
    result: dict[str, Any] = {}

    defs = schema.get("$defs", {})

    if "$ref" in schema:
        ref_name = schema["$ref"].split("/")[-1]
        if ref_name in defs:
            return _convert_schema({**defs[ref_name], "$defs": defs})
        return {"type": "object"}

    schema_type = schema.get("type")

    if schema_type == "object":
        result["type"] = "object"
        props = schema.get("properties", {})
        if props:
            converted_props: dict[str, Any] = {}
            for name, prop_schema in props.items():
                converted_props[name] = _convert_schema({**prop_schema, "$defs": defs})
            result["properties"] = converted_props
    elif schema_type == "array":
        result["type"] = "array"
        items = schema.get("items", {})
        result["items"] = _convert_schema({**items, "$defs": defs})
    elif schema_type == "string":
        result["type"] = "string"
        if "enum" in schema:
            result["enum"] = schema["enum"]
    elif schema_type == "integer":
        result["type"] = "integer"
    elif schema_type == "number":
        result["type"] = "number"
    elif schema_type == "boolean":
        result["type"] = "boolean"
    elif "anyOf" in schema:
        # Handle Optional types (anyOf with null)
        types = [s for s in schema["anyOf"] if s.get("type") != "null"]
        if len(types) == 1:
            result = _convert_schema({**types[0], "$defs": defs})
        else:
            result["type"] = "object"
    else:
        result["type"] = "object"

    if "description" in schema:
        result["description"] = schema["description"]

    return result


# ---------------------------------------------------------------------------
# Register all CRDs
# ---------------------------------------------------------------------------


def register_all_crds() -> dict[str, dict[str, Any]]:
    """Register all RouterBot CRDs and return the registry."""
    _CRD_REGISTRY.clear()

    _register_crd(
        "LLMGateway",
        plural="llmgateways",
        spec_model=GatewaySpec,
        status_model=GatewayStatus,
    )
    _register_crd(
        "LLMModel",
        plural="llmmodels",
        spec_model=ModelSpec,
        status_model=ModelStatus,
    )
    _register_crd(
        "LLMKey",
        plural="llmkeys",
        spec_model=KeySpec,
        status_model=KeyStatus,
    )
    _register_crd(
        "LLMTeam",
        plural="llmteams",
        spec_model=TeamSpec,
        status_model=TeamStatus,
    )
    return dict(_CRD_REGISTRY)


def get_crd(kind: str) -> dict[str, Any] | None:
    """Get a registered CRD by kind name."""
    if not _CRD_REGISTRY:
        register_all_crds()
    return _CRD_REGISTRY.get(kind)


def list_crds() -> list[str]:
    """List all registered CRD kinds."""
    if not _CRD_REGISTRY:
        register_all_crds()
    return list(_CRD_REGISTRY.keys())


# Suppress unused-import warnings for models used only in _register_crd calls
__all__ = [
    "AutoscalingSpec",
    "GatewaySpec",
    "GatewayStatus",
    "HealthCheckSpec",
    "K8sOperatorConfig",
    "KeySpec",
    "KeyStatus",
    "LLMGateway",
    "LLMKey",
    "LLMModel",
    "LLMTeam",
    "ModelSpec",
    "ModelStatus",
    "ResourceRequirements",
    "TeamSpec",
    "TeamStatus",
    "get_crd",
    "list_crds",
    "register_all_crds",
]
