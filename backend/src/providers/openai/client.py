import asyncio
import json
from pathlib import Path

from openai import OpenAI

from schemas.extraction import MemoryExtraction


class OpenAITranscriptionProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model

    async def transcribe_file(self, audio_path: Path) -> str:
        def call() -> str:
            with audio_path.open("rb") as audio_file:
                result = self.client.audio.transcriptions.create(
                    model=self.model,
                    file=audio_file,
                    response_format="text",
                )
            return str(result)

        return await asyncio.to_thread(call)


class OpenAIExtractionProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model

    async def extract_memory(self, transcript: str) -> MemoryExtraction:
        def call() -> MemoryExtraction:
            response = self.client.responses.create(
                model=self.model,
                instructions=(
                    "Extract only memory-assistant facts explicitly stated in the transcript. "
                    "Return JSON with introduced_person, events, claims, and "
                    "needs_caregiver_review. "
                    "Do not invent facts."
                ),
                input=transcript,
            )
            text = response.output_text
            return MemoryExtraction.model_validate_json(text)

        try:
            return await asyncio.to_thread(call)
        except (json.JSONDecodeError, ValueError):
            return MemoryExtraction(claims=[transcript], needs_caregiver_review=True)


class OpenAIEmbeddingProvider:
    def __init__(self, *, api_key: str, model: str, dimensions: int = 1536) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.dimensions = dimensions

    async def embed_text(self, text: str) -> list[float]:
        def call() -> list[float]:
            response = self.client.embeddings.create(
                model=self.model,
                input=text,
                dimensions=self.dimensions,
            )
            return list(response.data[0].embedding)

        return await asyncio.to_thread(call)
