"""Tests for the RouterBot router layer.

Covers:
- Load balancing strategies (RoundRobin, LeastConnections, LatencyBased,
  CostBased, Weighted)
- RetryPolicy and with_retry
- execute_with_fallbacks
- CooldownManager
- Router build registry, deployment selection, and routing
- HealthChecker lifecycle
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from routerbot.core.config_models import ModelEntry, ModelParams, RouterBotConfig
from routerbot.core.enums import Role
from routerbot.core.exceptions import (
    AuthenticationError,
    BadRequestError,
    ModelNotFoundError,
    ProviderError,
    RateLimitError,
    ServiceUnavailableError,
)
from routerbot.core.types import CompletionRequest, EmbeddingRequest, ImageRequest, Message
from routerbot.router.cooldown import CooldownManager
from routerbot.router.fallback import execute_with_fallbacks
from routerbot.router.health import HealthChecker
from routerbot.router.retry import RetryPolicy, with_retry
from routerbot.router.router import Deployment, Router
from routerbot.router.strategies import (
    CostBasedStrategy,
    LatencyBasedStrategy,
    LeastConnectionsStrategy,
    RoundRobinStrategy,
    WeightedStrategy,
    get_strategy,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _dep(
    name: str,
    active: int = 0,
    latency: float = 0.0,
    cost: float | None = None,
    weight: int = 1,
) -> Deployment:
    d = Deployment(
        name=name,
        provider_name="openai",
        provider_model=f"openai/{name}",
    )
    d.active_requests = active
    d.avg_latency_ms = latency
    d.cost_per_token = cost
    d.weight = weight
    return d


def _make_request(model: str = "gpt-4o") -> CompletionRequest:
    return CompletionRequest(
        model=model,
        messages=[Message(role=Role.USER, content="hello")],
    )


def _make_config(*model_names: str) -> RouterBotConfig:
    """Build a minimal RouterBotConfig with the given virtual model names."""
    return RouterBotConfig(
        model_list=[
            ModelEntry(
                model_name=name,
                provider_params=ModelParams(model=f"openai/{name}", api_key="sk-test"),
            )
            for name in model_names
        ]
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Strategies
# ═══════════════════════════════════════════════════════════════════════════════


class TestRoundRobinStrategy:
    def test_empty_returns_none(self) -> None:
        assert RoundRobinStrategy().select([]) is None

    def test_single_deployment_always_returned(self) -> None:
        dep = _dep("gpt-4o")
        strat = RoundRobinStrategy()
        for _ in range(5):
            assert strat.select([dep]) is dep

    def test_distributes_evenly(self) -> None:
        deps = [_dep("a"), _dep("b"), _dep("c")]
        strat = RoundRobinStrategy()
        selected = [strat.select(deps).name for _ in range(6)]  # type: ignore[union-attr]
        assert selected == ["a", "b", "c", "a", "b", "c"]

    def test_counter_wraps(self) -> None:
        deps = [_dep("x"), _dep("y")]
        strat = RoundRobinStrategy()
        # Advance counter to near-overflow: not feasible but check a large N
        for _ in range(100):
            strat.select(deps)
        # Should still work
        result = strat.select(deps)
        assert result is not None
        assert result.name in ("x", "y")


class TestLeastConnectionsStrategy:
    def test_empty_returns_none(self) -> None:
        assert LeastConnectionsStrategy().select([]) is None

    def test_picks_minimum_active(self) -> None:
        deps = [_dep("a", active=5), _dep("b", active=1), _dep("c", active=3)]
        result = LeastConnectionsStrategy().select(deps)
        assert result is not None
        assert result.name == "b"

    def test_ties_broken_deterministically(self) -> None:
        deps = [_dep("a", active=2), _dep("b", active=2)]
        result = LeastConnectionsStrategy().select(deps)
        assert result is not None
        assert result.name in ("a", "b")


class TestLatencyBasedStrategy:
    def test_empty_returns_none(self) -> None:
        assert LatencyBasedStrategy().select([]) is None

    def test_picks_lowest_latency(self) -> None:
        deps = [_dep("a", latency=200.0), _dep("b", latency=50.0), _dep("c", latency=150.0)]
        result = LatencyBasedStrategy().select(deps)
        assert result is not None
        assert result.name == "b"

    def test_zero_latency_treated_as_untested_deprioritized(self) -> None:
        """Deployments with 0 ms latency (untested) should be deprioritized vs tested."""
        deps = [_dep("a", latency=100.0), _dep("b", latency=0.0)]
        result = LatencyBasedStrategy().select(deps)
        assert result is not None
        # 100 ms tested < inf (untested) so 'a' wins
        assert result.name == "a"


class TestCostBasedStrategy:
    def test_empty_returns_none(self) -> None:
        assert CostBasedStrategy().select([]) is None

    def test_picks_cheapest(self) -> None:
        deps = [_dep("a", cost=0.01), _dep("b", cost=0.001), _dep("c", cost=0.005)]
        result = CostBasedStrategy().select(deps)
        assert result is not None
        assert result.name == "b"

    def test_all_no_cost_returns_random_deployment(self) -> None:
        deps = [_dep("a"), _dep("b"), _dep("c")]
        result = CostBasedStrategy().select(deps)
        assert result is not None
        assert result.name in ("a", "b", "c")


class TestWeightedStrategy:
    def test_empty_returns_none(self) -> None:
        assert WeightedStrategy().select([]) is None

    def test_respects_weights_statistically(self) -> None:
        # Weight 90:10 — a should win ~90% of the time over 1000 trials
        deps = [_dep("a", weight=90), _dep("b", weight=10)]
        strat = WeightedStrategy()
        counts: dict[str, int] = {"a": 0, "b": 0}
        for _ in range(1000):
            r = strat.select(deps)
            assert r is not None
            counts[r.name] += 1
        assert counts["a"] > 800  # very loose threshold for flakiness

    def test_single_deployment_with_any_weight(self) -> None:
        dep = _dep("only", weight=5)
        result = WeightedStrategy().select([dep])
        assert result is dep


class TestGetStrategy:
    def test_round_robin(self) -> None:
        assert isinstance(get_strategy("round-robin"), RoundRobinStrategy)

    def test_least_connections(self) -> None:
        assert isinstance(get_strategy("least-connections"), LeastConnectionsStrategy)

    def test_latency_based(self) -> None:
        assert isinstance(get_strategy("latency-based"), LatencyBasedStrategy)

    def test_cost_based(self) -> None:
        assert isinstance(get_strategy("cost-based"), CostBasedStrategy)

    def test_weighted(self) -> None:
        assert isinstance(get_strategy("weighted"), WeightedStrategy)

    def test_unknown_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown routing strategy"):
            get_strategy("magic-ai")


# ═══════════════════════════════════════════════════════════════════════════════
# RetryPolicy
# ═══════════════════════════════════════════════════════════════════════════════


class TestRetryPolicy:
    def test_default_max_retries(self) -> None:
        assert RetryPolicy().max_retries == 3

    def test_delay_increases_exponentially(self) -> None:
        policy = RetryPolicy(base_delay=1.0, max_delay=100.0, jitter=False)
        d0 = policy.delay_for(0)
        d1 = policy.delay_for(1)
        d2 = policy.delay_for(2)
        assert d1 > d0
        assert d2 > d1

    def test_delay_clamped_to_max(self) -> None:
        policy = RetryPolicy(base_delay=10.0, max_delay=15.0, jitter=False)
        assert policy.delay_for(10) <= 15.0

    def test_jitter_adds_randomness(self) -> None:
        policy = RetryPolicy(base_delay=1.0, jitter=True)
        delays = {policy.delay_for(1) for _ in range(20)}
        assert len(delays) > 1  # must not be constant

    def test_should_retry_auth_error_returns_false(self) -> None:
        policy = RetryPolicy()
        assert policy.should_retry(AuthenticationError("bad key")) is False

    def test_should_retry_bad_request_returns_false(self) -> None:
        policy = RetryPolicy()
        assert policy.should_retry(BadRequestError("bad")) is False

    def test_should_retry_model_not_found_returns_false(self) -> None:
        policy = RetryPolicy()
        assert policy.should_retry(ModelNotFoundError("m")) is False

    def test_should_retry_rate_limit_returns_true(self) -> None:
        policy = RetryPolicy()
        assert policy.should_retry(RateLimitError("limit")) is True

    def test_should_retry_service_unavailable_returns_true(self) -> None:
        policy = RetryPolicy()
        assert policy.should_retry(ServiceUnavailableError("down")) is True

    def test_should_retry_provider_error_retryable_status(self) -> None:
        policy = RetryPolicy()
        assert policy.should_retry(ProviderError("oops", status_code=503)) is True

    def test_should_retry_provider_error_non_retryable_status(self) -> None:
        policy = RetryPolicy()
        assert policy.should_retry(ProviderError("oops", status_code=400)) is False

    def test_should_retry_httpx_timeout(self) -> None:
        policy = RetryPolicy()
        exc = httpx.ReadTimeout("timeout", request=MagicMock())
        assert policy.should_retry(exc) is True

    def test_should_retry_httpx_network_error(self) -> None:
        policy = RetryPolicy()
        exc = httpx.ConnectError("refused")
        assert policy.should_retry(exc) is True

    def test_should_retry_generic_exception_false(self) -> None:
        policy = RetryPolicy()
        assert policy.should_retry(ValueError("nope")) is False


@pytest.mark.anyio
class TestWithRetry:
    async def test_succeeds_first_attempt(self) -> None:
        called = 0

        async def func() -> str:
            nonlocal called
            called += 1
            return "ok"

        result = await with_retry(func, RetryPolicy(max_retries=3))
        assert result == "ok"
        assert called == 1

    async def test_retries_on_transient_error(self) -> None:
        calls = 0

        async def func() -> str:
            nonlocal calls
            calls += 1
            if calls < 3:
                raise RateLimitError("too many")
            return "done"

        result = await with_retry(
            func,
            RetryPolicy(max_retries=5, base_delay=0.0, jitter=False),
        )
        assert result == "done"
        assert calls == 3

    async def test_raises_after_max_retries(self) -> None:
        async def func() -> str:
            raise ServiceUnavailableError("down")

        with pytest.raises(ServiceUnavailableError):
            await with_retry(
                func,
                RetryPolicy(max_retries=2, base_delay=0.0, jitter=False),
            )

    async def test_non_retryable_error_propagates_immediately(self) -> None:
        calls = 0

        async def func() -> str:
            nonlocal calls
            calls += 1
            raise AuthenticationError("bad key")

        with pytest.raises(AuthenticationError):
            await with_retry(func, RetryPolicy(max_retries=3, base_delay=0.0, jitter=False))

        assert calls == 1  # no retries


# ═══════════════════════════════════════════════════════════════════════════════
# execute_with_fallbacks
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
class TestExecuteWithFallbacks:
    async def test_returns_primary_result_on_success(self) -> None:
        async def fn(model: str) -> str:
            return f"result-{model}"

        result = await execute_with_fallbacks(
            primary_model="gpt-4o",
            fallback_models=["claude-3-sonnet"],
            provider_fn=fn,
        )
        assert result == "result-gpt-4o"

    async def test_uses_fallback_on_primary_failure(self) -> None:
        async def fn(model: str) -> str:
            if model == "gpt-4o":
                raise ServiceUnavailableError("down")
            return f"result-{model}"

        result = await execute_with_fallbacks(
            primary_model="gpt-4o",
            fallback_models=["claude-3-sonnet"],
            provider_fn=fn,
        )
        assert result == "result-claude-3-sonnet"

    async def test_bubbles_non_retryable_auth_error_immediately(self) -> None:
        called: list[str] = []

        async def fn(model: str) -> str:
            called.append(model)
            raise AuthenticationError("bad key")

        with pytest.raises(AuthenticationError):
            await execute_with_fallbacks(
                primary_model="gpt-4o",
                fallback_models=["claude-3-sonnet", "gemini-pro"],
                provider_fn=fn,
            )

        # Should stop at primary
        assert called == ["gpt-4o"]

    async def test_all_fail_raises_last_exception(self) -> None:
        async def fn(model: str) -> str:
            raise RateLimitError("limit")

        with pytest.raises(RateLimitError):
            await execute_with_fallbacks(
                primary_model="a",
                fallback_models=["b", "c"],
                provider_fn=fn,
            )

    async def test_empty_fallbacks_raises_on_primary_failure(self) -> None:
        async def fn(model: str) -> str:
            raise ServiceUnavailableError("down")

        with pytest.raises(ServiceUnavailableError):
            await execute_with_fallbacks(
                primary_model="a",
                fallback_models=[],
                provider_fn=fn,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# CooldownManager
# ═══════════════════════════════════════════════════════════════════════════════


class TestCooldownManager:
    def test_fresh_deployment_not_in_cooldown(self) -> None:
        mgr = CooldownManager(allowed_fails=3, cooldown_seconds=60)
        assert mgr.is_in_cooldown("gpt-4o") is False

    def test_enters_cooldown_at_threshold(self) -> None:
        mgr = CooldownManager(allowed_fails=3, cooldown_seconds=60)
        for _ in range(3):
            mgr.record_failure("gpt-4o")
        assert mgr.is_in_cooldown("gpt-4o") is True

    def test_not_in_cooldown_below_threshold(self) -> None:
        mgr = CooldownManager(allowed_fails=3, cooldown_seconds=60)
        mgr.record_failure("gpt-4o")
        mgr.record_failure("gpt-4o")
        assert mgr.is_in_cooldown("gpt-4o") is False

    def test_resets_failure_count_on_success(self) -> None:
        mgr = CooldownManager(allowed_fails=3, cooldown_seconds=60)
        mgr.record_failure("gpt-4o")
        mgr.record_failure("gpt-4o")
        mgr.record_success("gpt-4o")
        # 2 failures then success → counter reset
        mgr.record_failure("gpt-4o")
        assert mgr.is_in_cooldown("gpt-4o") is False

    def test_cooldown_expires_after_duration(self) -> None:
        import time

        mgr = CooldownManager(allowed_fails=1, cooldown_seconds=0)  # instant expire
        mgr.record_failure("x")
        time.sleep(0.01)
        assert mgr.is_in_cooldown("x") is False

    def test_explicit_reset_clears_state(self) -> None:
        mgr = CooldownManager(allowed_fails=2, cooldown_seconds=60)
        mgr.record_failure("y")
        mgr.record_failure("y")
        assert mgr.is_in_cooldown("y") is True
        mgr.reset("y")
        assert mgr.is_in_cooldown("y") is False

    def test_all_in_cooldown_false_when_some_healthy(self) -> None:
        mgr = CooldownManager(allowed_fails=1, cooldown_seconds=60)
        mgr.record_failure("a")  # enters cooldown
        cooling = mgr.all_in_cooldown()
        assert "a" in cooling
        assert "b" not in cooling

    def test_all_in_cooldown_true_when_all_cooling(self) -> None:
        mgr = CooldownManager(allowed_fails=1, cooldown_seconds=60)
        mgr.record_failure("a")
        mgr.record_failure("b")
        cooling = mgr.all_in_cooldown()
        assert set(cooling) == {"a", "b"}

    def test_unknown_deployment_not_in_cooldown(self) -> None:
        mgr = CooldownManager()
        assert mgr.is_in_cooldown("unknown-model") is False


# ═══════════════════════════════════════════════════════════════════════════════
# Deployment
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeployment:
    def test_record_latency_initialises_from_zero(self) -> None:
        dep = _dep("a")
        dep.avg_latency_ms = 0.0
        dep.record_latency(100.0)
        assert dep.avg_latency_ms == 100.0

    def test_record_latency_ema_update(self) -> None:
        dep = _dep("a")
        dep.avg_latency_ms = 100.0
        dep.record_latency(200.0)
        # EMA: 0.2*200 + 0.8*100 = 120
        assert dep.avg_latency_ms == pytest.approx(120.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Router
# ═══════════════════════════════════════════════════════════════════════════════


class TestRouterBuildRegistry:
    def test_builds_deployments_from_config(self) -> None:
        config = _make_config("gpt-4o", "claude-3-sonnet")
        router = Router(config=config)
        assert "gpt-4o" in router._deployments
        assert "claude-3-sonnet" in router._deployments

    def test_skips_entries_without_slash(self) -> None:
        config = RouterBotConfig(
            model_list=[
                ModelEntry(
                    model_name="bad-entry",
                    provider_params=ModelParams(model="noslash"),
                )
            ]
        )
        router = Router(config=config)
        assert "bad-entry" not in router._deployments

    def test_resolves_env_var_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_API_KEY", "sk-resolved")
        config = RouterBotConfig(
            model_list=[
                ModelEntry(
                    model_name="gpt-4o",
                    provider_params=ModelParams(
                        model="openai/gpt-4o",
                        api_key="os.environ/MY_API_KEY",
                    ),
                )
            ]
        )
        router = Router(config=config)
        deps = router._deployments["gpt-4o"]
        assert deps[0].api_key == "sk-resolved"

    def test_merges_fallbacks_from_router_settings(self) -> None:
        config = _make_config("gpt-4o", "claude-3-sonnet")
        config.router_settings.fallbacks = {"gpt-4o": ["claude-3-sonnet"]}
        router = Router(config=config)
        assert router._fallbacks.get("gpt-4o") == ["claude-3-sonnet"]

    def test_list_models_returns_all_names(self) -> None:
        config = _make_config("a", "b", "c")
        router = Router(config=config)
        assert set(router.list_models()) == {"a", "b", "c"}


class TestRouterSelectDeployment:
    def test_raises_if_model_unknown(self) -> None:
        router = Router()
        with pytest.raises(ModelNotFoundError):
            router._select_deployment("unknown-model")

    def test_raises_if_all_cooling_down(self) -> None:
        config = _make_config("gpt-4o")
        router = Router(config=config, allowed_fails=1, cooldown_seconds=60)
        router._cooldown.record_failure("gpt-4o")
        # Now cooling
        with pytest.raises(ModelNotFoundError):
            router._select_deployment("gpt-4o")

    def test_skips_cooling_deployments(self) -> None:
        # Two deployments for same virtual model name but different provider models
        config = RouterBotConfig(
            model_list=[
                ModelEntry(
                    model_name="gpt-4o",
                    provider_params=ModelParams(model="openai/gpt-4o"),
                ),
                ModelEntry(
                    model_name="gpt-4o",
                    provider_params=ModelParams(model="openai/gpt-4o-backup"),
                ),
            ]
        )
        router = Router(config=config, allowed_fails=1, cooldown_seconds=60)
        deps = router._deployments["gpt-4o"]
        # Both have the same deployment name ("gpt-4o") — mark the first as cooling
        # by directly setting the cooldown entry for the first dep name
        # We rename dep names to be unique first:
        deps[0].name = "gpt-4o-primary"
        deps[1].name = "gpt-4o-backup"
        router._cooldown.record_failure("gpt-4o-primary")
        # Should select the second (backup) deployment
        selected = router._select_deployment("gpt-4o")
        assert selected.name == "gpt-4o-backup"


@pytest.mark.anyio
class TestRouterChatCompletion:
    async def test_routes_to_provider(self) -> None:
        config = _make_config("gpt-4o")
        router = Router(config=config)

        mock_response = MagicMock()

        with patch.object(router, "_make_provider") as mock_make:
            mock_provider = AsyncMock()
            mock_provider.chat_completion.return_value = mock_response
            mock_make.return_value = mock_provider

            result = await router.chat_completion(_make_request("gpt-4o"))

        assert result is mock_response
        mock_provider.chat_completion.assert_called_once()

    async def test_uses_fallback_on_failure(self) -> None:
        config = _make_config("primary", "fallback")
        router = Router(
            config=config,
            fallbacks={"primary": ["fallback"]},
            max_retries=1,
        )

        call_counts: dict[str, int] = {}
        mock_fallback_response = MagicMock()

        async def fake_chat_completion(req: Any) -> Any:
            model = req.model
            call_counts[model] = call_counts.get(model, 0) + 1
            if model == "primary":
                raise ServiceUnavailableError("down")
            return mock_fallback_response

        with patch.object(router, "_make_provider") as mock_make:
            mock_provider = AsyncMock()
            mock_provider.chat_completion.side_effect = fake_chat_completion
            mock_make.return_value = mock_provider

            result = await router.chat_completion(_make_request("primary"))

        assert result is mock_fallback_response

    async def test_auth_error_propagates_without_fallback(self) -> None:
        config = _make_config("gpt-4o", "fallback")
        router = Router(
            config=config,
            fallbacks={"gpt-4o": ["fallback"]},
        )

        with patch.object(router, "_make_provider") as mock_make:
            mock_provider = AsyncMock()
            mock_provider.chat_completion.side_effect = AuthenticationError("bad key")
            mock_make.return_value = mock_provider

            with pytest.raises(AuthenticationError):
                await router.chat_completion(_make_request("gpt-4o"))

    async def test_decrements_active_requests_after_completion(self) -> None:
        config = _make_config("gpt-4o")
        router = Router(config=config)

        with patch.object(router, "_make_provider") as mock_make:
            mock_provider = AsyncMock()
            mock_provider.chat_completion.return_value = MagicMock()
            mock_make.return_value = mock_provider

            await router.chat_completion(_make_request("gpt-4o"))

        dep = router._deployments["gpt-4o"][0]
        assert dep.active_requests == 0


@pytest.mark.anyio
class TestRouterEmbeddings:
    async def test_routes_embedding_request(self) -> None:
        config = _make_config("text-embedding-3-small")
        router = Router(config=config)

        mock_response = MagicMock()

        with patch.object(router, "_make_provider") as mock_make:
            mock_provider = AsyncMock()
            mock_provider.embedding.return_value = mock_response
            mock_make.return_value = mock_provider

            req = EmbeddingRequest(model="text-embedding-3-small", input=["hello world"])
            result = await router.embeddings(req)

        assert result is mock_response


@pytest.mark.anyio
class TestRouterImageGeneration:
    async def test_routes_image_request(self) -> None:
        config = _make_config("dall-e-3")
        router = Router(config=config)

        mock_response = MagicMock()

        with patch.object(router, "_make_provider") as mock_make:
            mock_provider = AsyncMock()
            mock_provider.image_generation.return_value = mock_response
            mock_make.return_value = mock_provider

            req = ImageRequest(model="dall-e-3", prompt="a cat")
            result = await router.image_generation(req)

        assert result is mock_response


@pytest.mark.anyio
class TestRouterStreamCompletion:
    async def test_streams_chunks(self) -> None:
        config = _make_config("gpt-4o")
        router = Router(config=config)

        chunks = [MagicMock(), MagicMock(), MagicMock()]

        async def fake_stream(_req: Any) -> Any:
            for chunk in chunks:
                yield chunk

        with patch.object(router, "_make_provider") as mock_make:
            mock_provider = MagicMock()
            mock_provider.chat_completion_stream = fake_stream
            mock_make.return_value = mock_provider

            collected = []
            async for chunk in router.chat_completion_stream(_make_request("gpt-4o")):
                collected.append(chunk)

        assert collected == chunks


# ═══════════════════════════════════════════════════════════════════════════════
# HealthChecker
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
class TestHealthChecker:
    def _make_router_with_deps(self) -> Router:
        config = _make_config("gpt-4o")
        return Router(config=config)

    async def test_start_creates_task(self) -> None:
        router = self._make_router_with_deps()
        checker = HealthChecker(router, interval=9999)
        await checker.start()
        assert checker.is_running is True
        await checker.stop()

    async def test_stop_cancels_task(self) -> None:
        router = self._make_router_with_deps()
        checker = HealthChecker(router, interval=9999)
        await checker.start()
        await checker.stop()
        assert checker.is_running is False

    async def test_double_start_is_idempotent(self) -> None:
        router = self._make_router_with_deps()
        checker = HealthChecker(router, interval=9999)
        await checker.start()
        task1 = checker._task
        await checker.start()  # second call should not replace task
        assert checker._task is task1
        await checker.stop()

    async def test_check_deployment_records_success(self) -> None:
        router = self._make_router_with_deps()
        checker = HealthChecker(router)
        dep = router._deployments["gpt-4o"][0]

        with patch.object(router, "_make_provider") as mock_make:
            mock_provider = AsyncMock()
            mock_provider.chat_completion.return_value = MagicMock()
            mock_make.return_value = mock_provider

            result = await checker._check_deployment(dep)

        assert result is True
        assert router._cooldown.is_in_cooldown(dep.name) is False

    async def test_check_deployment_records_failure_on_error(self) -> None:
        router = self._make_router_with_deps()
        router._cooldown = CooldownManager(allowed_fails=1, cooldown_seconds=60)
        checker = HealthChecker(router)
        dep = router._deployments["gpt-4o"][0]

        with patch.object(router, "_make_provider") as mock_make:
            mock_provider = AsyncMock()
            mock_provider.chat_completion.side_effect = ServiceUnavailableError("down")
            mock_make.return_value = mock_provider

            result = await checker._check_deployment(dep)

        assert result is False
        assert router._cooldown.is_in_cooldown(dep.name) is True

    async def test_stop_when_not_started_is_safe(self) -> None:
        router = self._make_router_with_deps()
        checker = HealthChecker(router)
        await checker.stop()  # should not raise
        assert checker.is_running is False
