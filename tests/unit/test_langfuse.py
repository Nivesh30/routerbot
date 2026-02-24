"""Tests for the Langfuse observability callback.

Covers:
- LangfuseCredentials auth header generation
- LangfuseClient enqueue / flush / periodic flush / shutdown
- LangfuseCallback on_request_start / end / error
- Per-team credential routing
- Error isolation (network failures don't propagate)
- Batch ingestion payload format
- _epoch_to_iso helper
"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from routerbot.observability.callbacks import (
    RequestEndData,
    RequestErrorData,
    RequestStartData,
)
from routerbot.observability.langfuse import (
    LangfuseCallback,
    LangfuseClient,
    LangfuseCredentials,
    _epoch_to_iso,
    _IngestionEvent,
    create_langfuse_callback,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def credentials() -> LangfuseCredentials:
    return LangfuseCredentials(
        public_key="pk-test-123",
        secret_key="sk-test-456",
        host="https://langfuse.example.com",
    )


@pytest.fixture()
def team_credentials() -> dict[str, LangfuseCredentials]:
    return {
        "team-alpha": LangfuseCredentials(
            public_key="pk-alpha",
            secret_key="sk-alpha",
            host="https://langfuse.example.com",
        ),
        "team-beta": LangfuseCredentials(
            public_key="pk-beta",
            secret_key="sk-beta",
            host="https://beta.langfuse.example.com",
        ),
    }


@pytest.fixture()
def mock_http_client() -> AsyncMock:
    """Return a mock httpx.AsyncClient that returns 207 (multi-status success)."""
    client = AsyncMock(spec=httpx.AsyncClient)
    response = MagicMock(spec=httpx.Response)
    response.status_code = 207
    response.text = '{"successes":[],"errors":[]}'
    client.post = AsyncMock(return_value=response)
    client.aclose = AsyncMock()
    return client


@pytest.fixture()
def start_data() -> RequestStartData:
    return RequestStartData(
        request_id="req-001",
        model="gpt-4o",
        messages=[{"role": "user", "content": "hello"}],
        user_id="user-42",
        team_id="team-alpha",
        key_id="key-99",
        timestamp=1700000000.0,
    )


@pytest.fixture()
def end_data() -> RequestEndData:
    return RequestEndData(
        request_id="req-001",
        model="gpt-4o",
        provider="openai",
        messages=[{"role": "user", "content": "hello"}],
        response={"choices": [{"message": {"content": "hi"}}]},
        tokens_prompt=10,
        tokens_completion=5,
        cost=0.0015,
        latency_ms=250.0,
        user_id="user-42",
        team_id="team-alpha",
        key_id="key-99",
        timestamp=1700000000.25,
    )


@pytest.fixture()
def error_data() -> RequestErrorData:
    return RequestErrorData(
        request_id="req-002",
        model="gpt-4o",
        error="Rate limit exceeded",
        error_type="RateLimitError",
        provider="openai",
        messages=[{"role": "user", "content": "hello"}],
        user_id="user-42",
        team_id="team-beta",
        key_id="key-99",
        timestamp=1700000001.0,
    )


# ===================================================================
# LangfuseCredentials tests
# ===================================================================


class TestLangfuseCredentials:

    def test_auth_header(self, credentials: LangfuseCredentials) -> None:
        expected = base64.b64encode(b"pk-test-123:sk-test-456").decode()
        assert credentials.auth_header == f"Basic {expected}"

    def test_default_host(self) -> None:
        creds = LangfuseCredentials(public_key="pk", secret_key="sk")
        assert creds.host == "https://cloud.langfuse.com"


# ===================================================================
# LangfuseClient tests
# ===================================================================


class TestLangfuseClient:

    @pytest.mark.asyncio()
    async def test_enqueue_adds_to_queue(
        self, credentials: LangfuseCredentials, mock_http_client: AsyncMock,
    ) -> None:
        client = LangfuseClient(credentials, http_client=mock_http_client, flush_interval=999)
        await client.start()
        try:
            event = _IngestionEvent(body={"test": True}, event_type="trace-create")
            await client.enqueue(event)
            assert len(client._queue) == 1
        finally:
            await client.shutdown()

    @pytest.mark.asyncio()
    async def test_flush_sends_batch(
        self, credentials: LangfuseCredentials, mock_http_client: AsyncMock,
    ) -> None:
        client = LangfuseClient(credentials, http_client=mock_http_client, flush_interval=999)
        await client.start()
        try:
            event1 = _IngestionEvent(body={"a": 1}, event_type="trace-create")
            event2 = _IngestionEvent(body={"b": 2}, event_type="generation-create")
            await client.enqueue(event1)
            await client.enqueue(event2)

            await client.flush()

            mock_http_client.post.assert_called_once()
            call_args = mock_http_client.post.call_args
            payload = call_args.kwargs.get("json") or call_args[1].get("json")
            assert len(payload["batch"]) == 2
            assert payload["batch"][0]["body"] == {"a": 1}
            assert payload["batch"][1]["type"] == "generation-create"
        finally:
            await client.shutdown()

    @pytest.mark.asyncio()
    async def test_flush_clears_queue(
        self, credentials: LangfuseCredentials, mock_http_client: AsyncMock,
    ) -> None:
        client = LangfuseClient(credentials, http_client=mock_http_client, flush_interval=999)
        await client.start()
        try:
            await client.enqueue(_IngestionEvent(body={}, event_type="trace-create"))
            await client.flush()
            assert len(client._queue) == 0
        finally:
            await client.shutdown()

    @pytest.mark.asyncio()
    async def test_auto_flush_on_max_batch_size(
        self, credentials: LangfuseCredentials, mock_http_client: AsyncMock,
    ) -> None:
        client = LangfuseClient(
            credentials, http_client=mock_http_client, max_batch_size=3, flush_interval=999,
        )
        await client.start()
        try:
            for i in range(3):
                await client.enqueue(_IngestionEvent(body={"i": i}, event_type="trace-create"))

            # Should have auto-flushed
            mock_http_client.post.assert_called_once()
            assert len(client._queue) == 0
        finally:
            await client.shutdown()

    @pytest.mark.asyncio()
    async def test_flush_empty_queue_noop(
        self, credentials: LangfuseCredentials, mock_http_client: AsyncMock,
    ) -> None:
        client = LangfuseClient(credentials, http_client=mock_http_client, flush_interval=999)
        await client.start()
        try:
            await client.flush()
            mock_http_client.post.assert_not_called()
        finally:
            await client.shutdown()

    @pytest.mark.asyncio()
    async def test_send_retry_on_failure(
        self, credentials: LangfuseCredentials,
    ) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        # First call raises, second succeeds
        success_resp = MagicMock(spec=httpx.Response)
        success_resp.status_code = 207
        mock_client.post = AsyncMock(
            side_effect=[httpx.HTTPError("connection error"), success_resp],
        )
        mock_client.aclose = AsyncMock()

        client = LangfuseClient(credentials, http_client=mock_client, flush_interval=999)
        await client.start()
        try:
            await client.enqueue(_IngestionEvent(body={"x": 1}, event_type="trace-create"))
            await client.flush()
            assert mock_client.post.call_count == 2
        finally:
            await client.shutdown()

    @pytest.mark.asyncio()
    async def test_send_drops_after_two_failures(
        self, credentials: LangfuseCredentials,
    ) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(side_effect=httpx.HTTPError("down"))
        mock_client.aclose = AsyncMock()

        client = LangfuseClient(credentials, http_client=mock_client, flush_interval=999)
        await client.start()
        try:
            await client.enqueue(_IngestionEvent(body={"x": 1}, event_type="trace-create"))
            await client.flush()
            # 2 attempts then drops
            assert mock_client.post.call_count == 2
            assert len(client._queue) == 0
        finally:
            await client.shutdown()

    @pytest.mark.asyncio()
    async def test_send_retries_on_server_error(
        self, credentials: LangfuseCredentials,
    ) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        err_resp = MagicMock(spec=httpx.Response)
        err_resp.status_code = 500
        err_resp.text = "Internal Server Error"
        ok_resp = MagicMock(spec=httpx.Response)
        ok_resp.status_code = 207
        mock_client.post = AsyncMock(side_effect=[err_resp, ok_resp])
        mock_client.aclose = AsyncMock()

        client = LangfuseClient(credentials, http_client=mock_client, flush_interval=999)
        await client.start()
        try:
            await client.enqueue(_IngestionEvent(body={}, event_type="trace-create"))
            await client.flush()
            assert mock_client.post.call_count == 2
        finally:
            await client.shutdown()

    @pytest.mark.asyncio()
    async def test_shutdown_flushes(
        self, credentials: LangfuseCredentials, mock_http_client: AsyncMock,
    ) -> None:
        client = LangfuseClient(credentials, http_client=mock_http_client, flush_interval=999)
        await client.start()
        await client.enqueue(_IngestionEvent(body={"fin": True}, event_type="trace-create"))
        await client.shutdown()

        mock_http_client.post.assert_called_once()

    @pytest.mark.asyncio()
    async def test_no_http_client_logs_warning(
        self, credentials: LangfuseCredentials,
    ) -> None:
        """If _http is None (shouldn't happen normally), flush logs a warning."""
        client = LangfuseClient(credentials, flush_interval=999)
        client._http = None
        await client.enqueue(_IngestionEvent(body={}, event_type="trace-create"))
        # Should not raise
        await client.flush()
        assert len(client._queue) == 0


# ===================================================================
# LangfuseCallback tests
# ===================================================================


class TestLangfuseCallback:

    @pytest.mark.asyncio()
    async def test_on_request_start_creates_trace(
        self,
        credentials: LangfuseCredentials,
        mock_http_client: AsyncMock,
        start_data: RequestStartData,
    ) -> None:
        cb = LangfuseCallback(credentials, http_client=mock_http_client)
        await cb.on_request_start(start_data)
        await cb.shutdown()

        call_args = mock_http_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        batch = payload["batch"]
        assert len(batch) == 1
        assert batch[0]["type"] == "trace-create"
        assert batch[0]["body"]["id"] == "req-001"
        assert batch[0]["body"]["name"] == "routerbot-gpt-4o"
        assert batch[0]["body"]["userId"] == "user-42"

    @pytest.mark.asyncio()
    async def test_on_request_end_creates_generation_and_trace_update(
        self,
        credentials: LangfuseCredentials,
        mock_http_client: AsyncMock,
        end_data: RequestEndData,
    ) -> None:
        cb = LangfuseCallback(credentials, http_client=mock_http_client)
        await cb.on_request_end(end_data)
        await cb.shutdown()

        call_args = mock_http_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        batch = payload["batch"]
        # Should have generation-create + trace-create (update)
        assert len(batch) == 2
        gen = next(e for e in batch if e["type"] == "generation-create")
        trace = next(e for e in batch if e["type"] == "trace-create")

        # Generation checks
        assert gen["body"]["traceId"] == "req-001"
        assert gen["body"]["model"] == "gpt-4o"
        assert gen["body"]["usage"]["input"] == 10
        assert gen["body"]["usage"]["output"] == 5
        assert gen["body"]["usage"]["total"] == 15
        assert gen["body"]["usage"]["totalCost"] == 0.0015
        assert gen["body"]["level"] == "DEFAULT"

        # Trace update checks
        assert trace["body"]["id"] == "req-001"
        assert trace["body"]["metadata"]["cost"] == 0.0015

    @pytest.mark.asyncio()
    async def test_on_request_error_creates_error_generation(
        self,
        credentials: LangfuseCredentials,
        mock_http_client: AsyncMock,
        error_data: RequestErrorData,
    ) -> None:
        cb = LangfuseCallback(credentials, http_client=mock_http_client)
        await cb.on_request_error(error_data)
        await cb.shutdown()

        call_args = mock_http_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        batch = payload["batch"]
        assert len(batch) == 2

        gen = next(e for e in batch if e["type"] == "generation-create")
        assert gen["body"]["level"] == "ERROR"
        assert gen["body"]["statusMessage"] == "Rate limit exceeded"
        assert gen["body"]["traceId"] == "req-002"

    @pytest.mark.asyncio()
    async def test_per_team_credential_routing(
        self,
        credentials: LangfuseCredentials,
        team_credentials: dict[str, LangfuseCredentials],
        start_data: RequestStartData,
    ) -> None:
        """Team-alpha requests should use team-alpha credentials."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        response = MagicMock(spec=httpx.Response)
        response.status_code = 207
        mock_client.post = AsyncMock(return_value=response)
        mock_client.aclose = AsyncMock()

        cb = LangfuseCallback(
            credentials,
            team_credentials=team_credentials,
            http_client=mock_client,
        )
        # start_data has team_id="team-alpha"
        await cb.on_request_start(start_data)
        await cb.shutdown()

        # The auth header should use team-alpha credentials
        call_args = mock_client.post.call_args
        headers = call_args.kwargs.get("headers") or call_args[1].get("headers")
        expected_auth = team_credentials["team-alpha"].auth_header
        assert headers["Authorization"] == expected_auth

    @pytest.mark.asyncio()
    async def test_default_credentials_for_unknown_team(
        self,
        credentials: LangfuseCredentials,
        team_credentials: dict[str, LangfuseCredentials],
    ) -> None:
        """Requests from unknown teams fall back to default credentials."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        response = MagicMock(spec=httpx.Response)
        response.status_code = 207
        mock_client.post = AsyncMock(return_value=response)
        mock_client.aclose = AsyncMock()

        cb = LangfuseCallback(
            credentials,
            team_credentials=team_credentials,
            http_client=mock_client,
        )
        data = RequestStartData(request_id="req-99", model="gpt-4o", team_id="team-unknown")
        await cb.on_request_start(data)
        await cb.shutdown()

        call_args = mock_client.post.call_args
        headers = call_args.kwargs.get("headers") or call_args[1].get("headers")
        assert headers["Authorization"] == credentials.auth_header

    @pytest.mark.asyncio()
    async def test_no_team_uses_default(
        self,
        credentials: LangfuseCredentials,
        mock_http_client: AsyncMock,
    ) -> None:
        """Requests without a team_id use default credentials."""
        cb = LangfuseCallback(credentials, http_client=mock_http_client)
        data = RequestStartData(request_id="req-100", model="gpt-4o")
        await cb.on_request_start(data)
        await cb.shutdown()

        mock_http_client.post.assert_called_once()
        call_args = mock_http_client.post.call_args
        headers = call_args.kwargs.get("headers") or call_args[1].get("headers")
        assert headers["Authorization"] == credentials.auth_header

    @pytest.mark.asyncio()
    async def test_separate_clients_per_credential_host(
        self,
        credentials: LangfuseCredentials,
        team_credentials: dict[str, LangfuseCredentials],
        mock_http_client: AsyncMock,
    ) -> None:
        """Team-beta has a different host, so should create a separate client."""
        cb = LangfuseCallback(
            credentials,
            team_credentials=team_credentials,
            http_client=mock_http_client,
        )

        # Get two clients for different teams/hosts
        client_alpha = await cb._get_client("team-alpha")
        client_beta = await cb._get_client("team-beta")

        assert client_alpha is not client_beta
        assert len(cb._clients) == 2

        await cb.shutdown()

    @pytest.mark.asyncio()
    async def test_same_creds_share_client(
        self,
        credentials: LangfuseCredentials,
        mock_http_client: AsyncMock,
    ) -> None:
        """Two teams with same creds+host should share a client."""
        same_creds = {
            "team-x": credentials,
            "team-y": credentials,
        }
        cb = LangfuseCallback(
            credentials,
            team_credentials=same_creds,
            http_client=mock_http_client,
        )

        client_x = await cb._get_client("team-x")
        client_y = await cb._get_client("team-y")

        assert client_x is client_y
        assert len(cb._clients) == 1

        await cb.shutdown()

    @pytest.mark.asyncio()
    async def test_callback_name(self, credentials: LangfuseCredentials) -> None:
        cb = LangfuseCallback(credentials)
        assert cb.name == "LangfuseCallback"

    @pytest.mark.asyncio()
    async def test_end_data_zero_tokens(
        self,
        credentials: LangfuseCredentials,
        mock_http_client: AsyncMock,
    ) -> None:
        """Cost breakdown handles 0 total tokens without division by zero."""
        cb = LangfuseCallback(credentials, http_client=mock_http_client)
        data = RequestEndData(
            request_id="req-z",
            model="gpt-4o",
            tokens_prompt=0,
            tokens_completion=0,
            cost=0.0,
        )
        await cb.on_request_end(data)
        await cb.shutdown()

        call_args = mock_http_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        gen = next(e for e in payload["batch"] if e["type"] == "generation-create")
        assert gen["body"]["usage"]["total"] == 0
        assert gen["body"]["usage"]["unit"] == "TOKENS"

    @pytest.mark.asyncio()
    async def test_shutdown_idempotent(
        self,
        credentials: LangfuseCredentials,
        mock_http_client: AsyncMock,
    ) -> None:
        cb = LangfuseCallback(credentials, http_client=mock_http_client)
        data = RequestStartData(request_id="req-s", model="gpt-4o")
        await cb.on_request_start(data)
        await cb.shutdown()
        # Second shutdown should not raise
        await cb.shutdown()


# ===================================================================
# Helper tests
# ===================================================================


class TestHelpers:

    def test_epoch_to_iso(self) -> None:
        result = _epoch_to_iso(1700000000.123)
        assert result == "2023-11-14T22:13:20.123Z"

    def test_epoch_to_iso_zero_millis(self) -> None:
        result = _epoch_to_iso(1700000000.0)
        assert result == "2023-11-14T22:13:20.000Z"


# ===================================================================
# Factory function tests
# ===================================================================


class TestCreateLangfuseCallback:

    def test_creates_callback(self) -> None:
        cb = create_langfuse_callback(
            public_key="pk-123",
            secret_key="sk-456",
            host="https://my-langfuse.com",
        )
        assert isinstance(cb, LangfuseCallback)
        assert cb._default_creds.public_key == "pk-123"
        assert cb._default_creds.host == "https://my-langfuse.com"

    def test_default_host(self) -> None:
        cb = create_langfuse_callback(public_key="pk", secret_key="sk")
        assert cb._default_creds.host == "https://cloud.langfuse.com"

    def test_with_team_credentials(self, team_credentials: dict[str, LangfuseCredentials]) -> None:
        cb = create_langfuse_callback(
            public_key="pk",
            secret_key="sk",
            team_credentials=team_credentials,
        )
        assert len(cb._team_creds) == 2
        assert "team-alpha" in cb._team_creds
