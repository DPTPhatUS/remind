from fastapi import APIRouter

from api.deps import PatientDep, SessionDep, to_http_error
from core.errors import AppError
from schemas.review import ReviewDecision, ReviewItemResponse
from services.review_service import ReviewService

router = APIRouter()


@router.get("", response_model=list[ReviewItemResponse])
async def list_review_items(patient: PatientDep, session: SessionDep) -> list[ReviewItemResponse]:
    items = await ReviewService(session).list_pending(patient.id)
    return [ReviewItemResponse.model_validate(item) for item in items]


@router.patch("/{item_id}", response_model=ReviewItemResponse)
async def decide_review_item(
    item_id: str,
    request: ReviewDecision,
    session: SessionDep,
) -> ReviewItemResponse:
    try:
        item = await ReviewService(session).decide(item_id, request)
    except AppError as error:
        raise to_http_error(error) from error
    return ReviewItemResponse.model_validate(item)
