"""Unit tests for model management CRUD endpoints (Task 7.4).

Covers:
- GET  /model/list
- GET  /model/info
- POST /model/new
- POST /model/update
- POST /model/delete
- POST /model/test_connection
- Master key authorization
- Duplicate / not-found error handling
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from routerbot.core.config_models import (
    GeneralSettings,
    ModelEntry,
    ModelParams,
    RouterBotConfig,
)
from routerbot.proxy.app import create_app

MASTER_KEY = "test-master-key-12345"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    models: list[tuple[str, str]] | None = None,
    *,
    master_key: str = MASTER_KEY,
) -> RouterBotConfig:
    config = RouterBotConfig(
        general_settings=GeneralSettings(master_key=master_key),
    )
    if models:
        config.model_list = [
            ModelEntry(
                model_name=name,
                provider_params=ModelParams(model=provider_model),
            )
            for name, provider_model in models
        ]
    return config


def _auth_headers(key: str = MASTER_KEY) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def client() -> AsyncClient:
    config = _make_config([
        ("gpt-4o", "openai/gpt-4o"),
        ("claude-3", "anthropic/claude-3-opus-20240229"),
    ])
    test_app = create_app(config=config)
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


@pytest_asyncio.fixture()
async def empty_client() -> AsyncClient:
    config = _make_config(models=[])
    test_app = create_app(config=config)
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


# ===================================================================
# Authorization Tests
# ===================================================================


class TestAuthorization:
    """Master key is required for all model management endpoints."""

    @pytest.mark.asyncio()
    async def test_list_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/model/list")
        assert resp.status_code == 401

    @pytest.mark.asyncio()
    async def test_info_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/model/info", params={"model_name": "gpt-4o"})
        assert resp.status_code == 401

    @pytest.mark.asyncio()
    async def test_new_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.post("/model/new", json={"model_name": "x", "model": "y"})
        assert resp.status_code == 401

    @pytest.mark.asyncio()
    async def test_update_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.post("/model/update", json={"model_name": "gpt-4o"})
        assert resp.status_code == 401

    @pytest.mark.asyncio()
    async def test_delete_requires_auth(self, client: AsyncClient) -> None:
        resp = await client.post("/model/delete", json={"model_name": "gpt-4o"})
        assert resp.status_code == 401

    @pytest.mark.asyncio()
    async def test_wrong_key_rejected(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/model/list",
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio()
    async def test_x_master_key_header(self, client: AsyncClient) -> None:
        resp = await client.get("/model/list", headers={"X-Master-Key": MASTER_KEY})
        assert resp.status_code == 200


# ===================================================================
# List Models Tests
# ===================================================================


class TestListModels:
    """GET /model/list tests."""

    @pytest.mark.asyncio()
    async def test_list_populated(self, client: AsyncClient) -> None:
        resp = await client.get("/model/list", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        names = {m["model_name"] for m in data["data"]}
        assert names == {"gpt-4o", "claude-3"}

    @pytest.mark.asyncio()
    async def test_list_empty(self, empty_client: AsyncClient) -> None:
        resp = await empty_client.get("/model/list", headers=_auth_headers())
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        assert resp.json()["data"] == []

    @pytest.mark.asyncio()
    async def test_list_masks_api_key(self, client: AsyncClient) -> None:
        """API keys should not be exposed."""
        resp = await client.get("/model/list", headers=_auth_headers())
        for m in resp.json()["data"]:
            assert "api_key" not in m
            assert "api_key_set" in m

    @pytest.mark.asyncio()
    async def test_list_shows_provider(self, client: AsyncClient) -> None:
        resp = await client.get("/model/list", headers=_auth_headers())
        providers = {m["provider"] for m in resp.json()["data"]}
        assert "openai" in providers
        assert "anthropic" in providers


# ===================================================================
# Get Model Info Tests
# ===================================================================


class TestGetModelInfo:
    """GET /model/info tests."""

    @pytest.mark.asyncio()
    async def test_info_found(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/model/info",
            params={"model_name": "gpt-4o"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["model_name"] == "gpt-4o"
        assert resp.json()["model"] == "openai/gpt-4o"

    @pytest.mark.asyncio()
    async def test_info_not_found(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/model/info",
            params={"model_name": "nonexistent"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 404


# ===================================================================
# Add Model Tests
# ===================================================================


class TestAddModel:
    """POST /model/new tests."""

    @pytest.mark.asyncio()
    async def test_add_basic(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/model/new",
            json={
                "model_name": "gemini-2.0-flash",
                "model": "google/gemini-2.0-flash",
            },
            headers=_auth_headers(),
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "created"
        assert resp.json()["model"]["model_name"] == "gemini-2.0-flash"

    @pytest.mark.asyncio()
    async def test_add_with_all_fields(self, empty_client: AsyncClient) -> None:
        resp = await empty_client.post(
            "/model/new",
            json={
                "model_name": "gpt-4o-mini",
                "model": "openai/gpt-4o-mini",
                "api_base": "https://api.openai.com/v1",
                "max_tokens": 4096,
                "rpm": 500,
                "tpm": 80000,
                "timeout": 120,
                "input_cost_per_token": 0.00015,
                "output_cost_per_token": 0.0006,
                "supports_streaming": True,
                "supports_function_calling": True,
                "supports_vision": True,
            },
            headers=_auth_headers(),
        )
        assert resp.status_code == 201
        model = resp.json()["model"]
        assert model["model_name"] == "gpt-4o-mini"
        assert model["model_info"]["supports_vision"] is True

    @pytest.mark.asyncio()
    async def test_add_duplicate_rejected(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/model/new",
            json={"model_name": "gpt-4o", "model": "openai/gpt-4o"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio()
    async def test_add_appears_in_list(self, client: AsyncClient) -> None:
        await client.post(
            "/model/new",
            json={"model_name": "new-model", "model": "openai/gpt-3.5"},
            headers=_auth_headers(),
        )
        resp = await client.get("/model/list", headers=_auth_headers())
        names = {m["model_name"] for m in resp.json()["data"]}
        assert "new-model" in names

    @pytest.mark.asyncio()
    async def test_add_also_visible_in_v1_models(self, client: AsyncClient) -> None:
        await client.post(
            "/model/new",
            json={"model_name": "visible-model", "model": "openai/gpt-3.5"},
            headers=_auth_headers(),
        )
        resp = await client.get("/v1/models")
        ids = {m["id"] for m in resp.json()["data"]}
        assert "visible-model" in ids


# ===================================================================
# Update Model Tests
# ===================================================================


class TestUpdateModel:
    """POST /model/update tests."""

    @pytest.mark.asyncio()
    async def test_update_rpm(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/model/update",
            json={"model_name": "gpt-4o", "rpm": 1000},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["model"]["rpm"] == 1000

    @pytest.mark.asyncio()
    async def test_update_model_string(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/model/update",
            json={"model_name": "gpt-4o", "model": "openai/gpt-4o-2024-08-06"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["model"]["model"] == "openai/gpt-4o-2024-08-06"

    @pytest.mark.asyncio()
    async def test_update_model_info(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/model/update",
            json={
                "model_name": "gpt-4o",
                "supports_vision": True,
                "input_cost_per_token": 0.005,
            },
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["model"]["model_info"]["supports_vision"] is True

    @pytest.mark.asyncio()
    async def test_update_not_found(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/model/update",
            json={"model_name": "nonexistent", "rpm": 100},
            headers=_auth_headers(),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio()
    async def test_update_persists(self, client: AsyncClient) -> None:
        """Updated value should be visible in subsequent info calls."""
        await client.post(
            "/model/update",
            json={"model_name": "gpt-4o", "max_tokens": 8192},
            headers=_auth_headers(),
        )
        resp = await client.get(
            "/model/info",
            params={"model_name": "gpt-4o"},
            headers=_auth_headers(),
        )
        assert resp.json()["max_tokens"] == 8192


# ===================================================================
# Delete Model Tests
# ===================================================================


class TestDeleteModel:
    """POST /model/delete tests."""

    @pytest.mark.asyncio()
    async def test_delete_existing(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/model/delete",
            json={"model_name": "claude-3"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    @pytest.mark.asyncio()
    async def test_delete_removes_from_list(self, client: AsyncClient) -> None:
        await client.post(
            "/model/delete",
            json={"model_name": "claude-3"},
            headers=_auth_headers(),
        )
        resp = await client.get("/model/list", headers=_auth_headers())
        names = {m["model_name"] for m in resp.json()["data"]}
        assert "claude-3" not in names

    @pytest.mark.asyncio()
    async def test_delete_not_found(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/model/delete",
            json={"model_name": "nonexistent"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio()
    async def test_delete_removes_from_v1_models(self, client: AsyncClient) -> None:
        await client.post(
            "/model/delete",
            json={"model_name": "claude-3"},
            headers=_auth_headers(),
        )
        resp = await client.get("/v1/models")
        ids = {m["id"] for m in resp.json()["data"]}
        assert "claude-3" not in ids


# ===================================================================
# Test Connection Tests
# ===================================================================


class TestConnectionTest:
    """POST /model/test_connection tests."""

    @pytest.mark.asyncio()
    async def test_connection_model_not_found(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/model/test_connection",
            json={"model_name": "nonexistent"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio()
    async def test_connection_no_router(self, empty_client: AsyncClient) -> None:
        """When router isn't initialized, returns error status."""
        # Add a model first
        await empty_client.post(
            "/model/new",
            json={"model_name": "test-model", "model": "openai/gpt-4o"},
            headers=_auth_headers(),
        )
        resp = await empty_client.post(
            "/model/test_connection",
            json={"model_name": "test-model"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        # Router not initialized, so should return error status
        data = resp.json()
        assert data["model_name"] == "test-model"
        assert "status" in data


# ===================================================================
# Edge Cases
# ===================================================================


class TestEdgeCases:
    """Misc edge cases."""

    @pytest.mark.asyncio()
    async def test_full_crud_cycle(self, empty_client: AsyncClient) -> None:
        """Add → List → Update → Info → Delete end-to-end."""
        headers = _auth_headers()

        # Add
        resp = await empty_client.post(
            "/model/new",
            json={"model_name": "test", "model": "openai/gpt-4o"},
            headers=headers,
        )
        assert resp.status_code == 201

        # List
        resp = await empty_client.get("/model/list", headers=headers)
        assert resp.json()["total"] == 1

        # Update
        resp = await empty_client.post(
            "/model/update",
            json={"model_name": "test", "rpm": 500},
            headers=headers,
        )
        assert resp.status_code == 200

        # Info
        resp = await empty_client.get(
            "/model/info", params={"model_name": "test"}, headers=headers,
        )
        assert resp.json()["rpm"] == 500

        # Delete
        resp = await empty_client.post(
            "/model/delete",
            json={"model_name": "test"},
            headers=headers,
        )
        assert resp.status_code == 200

        # Verify gone
        resp = await empty_client.get("/model/list", headers=headers)
        assert resp.json()["total"] == 0

    @pytest.mark.asyncio()
    async def test_model_entry_serialization(self, client: AsyncClient) -> None:
        """Verify all expected fields in the response."""
        resp = await client.get(
            "/model/info",
            params={"model_name": "gpt-4o"},
            headers=_auth_headers(),
        )
        data = resp.json()
        assert "model_name" in data
        assert "model" in data
        assert "provider" in data
        assert "api_key_set" in data
        assert "api_base" in data
        assert "created" in data
