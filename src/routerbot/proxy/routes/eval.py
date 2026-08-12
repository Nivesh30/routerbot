"""Evaluation routes — /v1/eval/*.

Minimal route surface over ``state.llm_judge`` (wired up with a real
provider handler in ``proxy/app.py`` — see ``proxy/completion_helper.py``).
Opt-in via ``evaluation.enabled: true`` in config; returns 503 otherwise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from routerbot.evaluation.models import JudgeVerdict  # noqa: TC001 - needed at runtime for FastAPI response model

if TYPE_CHECKING:
    from routerbot.evaluation.llm_judge import LLMJudge

router = APIRouter(prefix="/eval", tags=["Evaluation"])


class JudgeRequest(BaseModel):
    """Request body for ``POST /v1/eval/judge``."""

    input_text: str
    candidate: str
    reference: str | None = None
    sample_id: str = ""
    model_id: str = ""


def _get_llm_judge(request: Request) -> LLMJudge:
    state = getattr(request.app.state, "routerbot", None)
    judge: LLMJudge | None = getattr(state, "llm_judge", None) if state else None
    if judge is None:
        raise HTTPException(
            status_code=503,
            detail="Evaluation is not enabled (set evaluation.enabled: true in config).",
        )
    return judge


@router.post("/judge", summary="Score a candidate response with the LLM judge")
async def judge_candidate(body: JudgeRequest, raw_request: Request) -> JudgeVerdict:
    judge = _get_llm_judge(raw_request)
    return await judge.evaluate(
        sample_id=body.sample_id,
        model_id=body.model_id,
        input_text=body.input_text,
        candidate=body.candidate,
        reference=body.reference,
    )
