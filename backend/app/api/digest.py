from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DbSession, http_for_ai
from app.ai.errors import AIProviderError
from app.ai.interactive_models import UnsupportedAIModelError
from app.enums import Platform
from app.schemas.digest import (
    DigestAIRequest,
    DigestAIResponse,
    DigestQAExportRequest,
    DigestQARequest,
    DigestQAResponse,
    DigestResponse,
)
from app.services.context_export import export_digest_qa, export_digest_review
from app.services.digest import DigestPeriodError, build_digest
from app.services.digest_ai import generate_ai_digest
from app.services.digest_qa import answer_digest_question

router = APIRouter(prefix="/digest", tags=["digest"])


def _platform(value: str | None) -> Platform | None:
    if not value:
        return None
    try:
        return Platform(value)
    except ValueError:
        raise HTTPException(status_code=400, detail={"code": "invalid_platform", "message": "Unknown platform."}) from None


def _unsupported_model() -> HTTPException:
    return HTTPException(status_code=400, detail={"code": "unsupported_ai_model", "message": "Unknown AI model."})


def _export_format(value: str | None) -> str:
    raw = (value or "md").strip().lower()
    if raw in {"md", "markdown"}:
        return "md"
    if raw == "json":
        return "json"
    raise HTTPException(status_code=400, detail={"code": "invalid_export_format", "message": "Unknown export format."})


@router.get("", response_model=DigestResponse)
def get_digest(
    db: DbSession,
    period: str | None = Query(default="24h"),
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    platform: str | None = Query(default=None),
    model: str | None = Query(default=None),
) -> DigestResponse:
    try:
        return build_digest(
            db,
            period=period,
            start=start,
            end=end,
            platform=_platform(platform),
            review_model=model,
        )
    except DigestPeriodError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)}) from None
    except UnsupportedAIModelError:
        raise _unsupported_model() from None


@router.get("/export")
def get_digest_export(
    db: DbSession,
    period: str | None = Query(default="24h"),
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    platform: str | None = Query(default=None),
    model: str | None = Query(default=None),
    export_format: str | None = Query(default="md", alias="format"),
):
    try:
        return export_digest_review(
            db,
            period=period,
            start=start,
            end=end,
            platform=_platform(platform),
            model=model,
            fmt=_export_format(export_format),  # type: ignore[arg-type]
        )
    except DigestPeriodError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)}) from None
    except UnsupportedAIModelError:
        raise _unsupported_model() from None


@router.post("/ai", response_model=DigestAIResponse)
async def post_digest_ai(db: DbSession, body: DigestAIRequest) -> DigestAIResponse:
    try:
        result = await generate_ai_digest(
            db,
            period=body.period,
            start=body.start,
            end=body.end,
            platform=body.platform,
            force=body.force,
            model=body.model,
        )
        db.commit()
        return result
    except DigestPeriodError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)}) from None
    except UnsupportedAIModelError:
        db.rollback()
        raise _unsupported_model() from None
    except AIProviderError as exc:
        db.rollback()
        raise http_for_ai(exc) from None
    except Exception:
        db.rollback()
        raise


@router.post("/qa", response_model=DigestQAResponse)
async def post_digest_qa(db: DbSession, body: DigestQARequest) -> DigestQAResponse:
    try:
        result = await answer_digest_question(
            db,
            question=body.question,
            period=body.period,
            start=body.start,
            end=body.end,
            model=body.model,
            history=body.history,
        )
        return result
    except DigestPeriodError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)}) from None
    except UnsupportedAIModelError:
        raise _unsupported_model() from None
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_question", "message": "Question is required."},
        ) from None
    except AIProviderError as exc:
        raise http_for_ai(exc) from None


@router.post("/qa/export")
def post_digest_qa_export(db: DbSession, body: DigestQAExportRequest):
    try:
        return export_digest_qa(
            db,
            question=body.question,
            period=body.period,
            start=body.start,
            end=body.end,
            model=body.model,
            history=body.history,
            snapshot=body.snapshot,
            fmt=_export_format(body.format),  # type: ignore[arg-type]
        )
    except DigestPeriodError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)}) from None
    except UnsupportedAIModelError:
        raise _unsupported_model() from None

