from fastapi import APIRouter

from api.deps import PatientDep, SessionDep, SettingsDep
from providers.openai import OpenAIEmbeddingProvider, OpenAIExtractionProvider
from schemas.interactions import (
    InteractionCreate,
    InteractionResponse,
    TranscriptCreate,
    TranscriptResponse,
)
from services.interaction_service import InteractionService

router = APIRouter()


@router.get("", response_model=list[InteractionResponse])
async def list_interactions(patient: PatientDep, session: SessionDep) -> list[InteractionResponse]:
    interactions = await InteractionService(session).list_interactions(patient.id)
    return [InteractionResponse.model_validate(item) for item in interactions]


@router.post("", response_model=InteractionResponse)
async def create_interaction(
    request: InteractionCreate,
    patient: PatientDep,
    session: SessionDep,
) -> InteractionResponse:
    interaction = await InteractionService(session).create_interaction(patient.id, request)
    return InteractionResponse.model_validate(interaction)


@router.post("/{interaction_id}/transcripts", response_model=TranscriptResponse)
async def add_transcript(
    interaction_id: str,
    request: TranscriptCreate,
    patient: PatientDep,
    session: SessionDep,
    settings: SettingsDep,
) -> TranscriptResponse:
    segment = await InteractionService(session).add_transcript(
        interaction_id=interaction_id,
        data=request,
    )
    if settings.openai_api_key:
        extraction_provider = OpenAIExtractionProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_text_model,
        )
        embedding_provider = OpenAIEmbeddingProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
            dimensions=settings.openai_embedding_dimensions,
        )
        extraction = await extraction_provider.extract_memory(request.text)
        await InteractionService(
            session,
            embedding_provider=embedding_provider,
        ).create_claims_from_extraction(
            patient_id=patient.id,
            interaction_id=interaction_id,
            extraction=extraction,
        )
    return TranscriptResponse.model_validate(segment)
