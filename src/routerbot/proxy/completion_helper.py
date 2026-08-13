"""Shared helper for subsystems that need to make a real LLM call.

AI Hub, Playground, LLM-judge evaluation, and batch processing all need to
turn "a model name from config + some messages" into a real provider call.
Each of those subsystems is designed around dependency-injected handler
callables (see their respective ``_default_handler`` stubs) — this module
supplies the *real* implementation of that handler, built on the same
provider-resolution logic used by ``proxy/routes/completions.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from routerbot.core.exceptions import BadRequestError, ModelNotFoundError, RouterBotError
from routerbot.core.types import CompletionRequest

if TYPE_CHECKING:
    from routerbot.core.config_models import RouterBotConfig
    from routerbot.providers.base import BaseProvider
    from routerbot.router.router import Router


def get_router(state: Any) -> Router:
    """Return ``state.router``, lazily building one from ``state.config`` if unset.

    ``state.router`` is normally built once at app startup (``proxy/app.py``),
    but some test fixtures construct the app without running the startup
    lifespan. Building lazily here — using the same
    ``routerbot.router.router.build_router`` factory startup uses — means
    routes work either way without every caller needing to know the
    difference.
    """
    router = getattr(state, "router", None)
    if router is None:
        from routerbot.router.router import build_router

        router = build_router(state.config if state else None)
        if state is not None:
            state.router = router
    return router


def get_provider_for_model(config: RouterBotConfig | None, model_name: str) -> BaseProvider:
    """Resolve a live provider instance for *model_name* from *config*.

    Mirrors ``proxy.routes.completions._get_provider_for_model`` but takes a
    config object directly, since callers here (Hub, Playground, batch/eval
    subsystems) hold a ``RouterBotConfig`` rather than a FastAPI ``Request``.

    Raises
    ------
    ModelNotFoundError
        If the model is not configured.
    BadRequestError
        If the configured ``provider/model`` string is malformed.
    """
    if config is None:
        raise ModelNotFoundError(model_name)

    entry = next((m for m in config.model_list if m.model_name == model_name), None)
    if entry is None:
        raise ModelNotFoundError(model_name)

    provider_model = entry.provider_params.model
    if "/" not in provider_model:
        raise BadRequestError(f"Invalid provider/model format: {provider_model!r}")

    provider_name, _ = provider_model.split("/", 1)

    from routerbot.providers.registry import get_provider_class

    provider_cls = get_provider_class(provider_name)

    api_key = entry.provider_params.api_key
    if api_key and api_key.startswith("os.environ/"):
        import os

        env_var = api_key.removeprefix("os.environ/")
        api_key = os.environ.get(env_var)

    return provider_cls(
        api_key=api_key,
        api_base=entry.provider_params.api_base,
        custom_headers=entry.provider_params.extra_headers,
    )


async def complete_via_config(
    config: RouterBotConfig | None,
    model_id: str,
    messages: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
) -> tuple[str, int, int]:
    """Run a real chat completion and return ``(text, prompt_tokens, completion_tokens)``.

    This is the ``(model, messages, params) -> (text, in_tokens, out_tokens)``
    handler shape expected by :class:`~routerbot.hub.model_hub.ModelHub` and
    :class:`~routerbot.hub.playground.Playground`.
    """
    provider = get_provider_for_model(config, model_id)
    request = CompletionRequest.model_validate({"model": model_id, "messages": messages, **(params or {})})
    response = await provider.chat_completion(request)

    text = ""
    if response.choices:
        text = response.choices[0].message.content or ""

    prompt_tokens = response.usage.prompt_tokens if response.usage else 0
    completion_tokens = response.usage.completion_tokens if response.usage else 0
    return text, prompt_tokens, completion_tokens


async def handle_batch_request(
    config: RouterBotConfig | None,
    method: str,
    url: str,
    body: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    """Execute one request from an OpenAI-compatible batch, for real.

    Handler shape expected by :class:`~routerbot.core.batch.batch_manager.BatchManager`:
    ``(method, url, body) -> (status_code, body)``. Only ``POST /v1/chat/completions``
    is supported today (the only endpoint OpenAI's batch API commonly targets in
    practice for this codebase); other combinations return a 400 in the same
    OpenAI-compatible error shape the synchronous routes use.
    """
    if method.upper() != "POST" or not url.rstrip("/").endswith("/chat/completions"):
        return 400, {
            "error": {
                "message": f"Unsupported batch request target: {method} {url}. "
                "Only POST /v1/chat/completions is supported.",
                "type": "invalid_request_error",
                "param": "url",
                "code": "unsupported_batch_endpoint",
            }
        }

    try:
        model_id = body.get("model", "")
        provider = get_provider_for_model(config, model_id)
        request = CompletionRequest.model_validate(body)
        response = await provider.chat_completion(request)
        return 200, response.model_dump(mode="json")
    except RouterBotError as exc:
        return exc.status_code, exc.to_openai_error()
    except Exception as exc:
        return 500, {
            "error": {
                "message": str(exc),
                "type": "internal_error",
                "param": None,
                "code": None,
            }
        }


async def handle_async_job(config: RouterBotConfig | None, job: Any) -> dict[str, Any]:
    """Execute an async job for real.

    Handler shape expected by :class:`~routerbot.core.batch.worker_pool.WorkerPool`:
    ``(job: AsyncJob) -> dict``. Raises on failure so the worker pool's existing
    retry/backoff logic (see ``WorkerPool._worker_loop``) applies unchanged.
    """
    text, prompt_tokens, completion_tokens = await complete_via_config(
        config, job.request.model, job.request.messages, job.request.parameters
    )
    return {
        "job_id": job.job_id,
        "model": job.request.model,
        "response": text,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


async def judge_complete_via_config(
    config: RouterBotConfig | None,
    model_id: str,
    messages: list[dict[str, Any]],
    **params: Any,
) -> str:
    """Handler shape expected by :class:`~routerbot.evaluation.llm_judge.LLMJudge`.

    ``(model, messages, **kwargs) -> response_text``.
    """
    text, _, _ = await complete_via_config(config, model_id, messages, params)
    return text
