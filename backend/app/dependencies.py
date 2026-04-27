# dependencies.py - application service wiring for FastAPI routes and WebSockets
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.db.repository import Repository, build_repository
from app.services.coach_graph import CoachWorkflow
from app.services.model_adapters import EmbeddingService, LLMService, STTService, TTSService
from app.services.rag import RAGService


@dataclass
class AppServices:
    settings: Settings
    repository: Repository
    embeddings: EmbeddingService
    stt: STTService
    llm: LLMService
    tts: TTSService
    rag: RAGService
    coach: CoachWorkflow


async def build_services(settings: Settings) -> AppServices:
    repository = await build_repository(settings.database_url, settings.auto_migrate)
    embeddings = EmbeddingService(settings)
    stt = STTService(settings)
    llm = LLMService(settings)
    tts = TTSService(settings)
    rag = RAGService(repository, embeddings)
    coach = CoachWorkflow(repository=repository, rag=rag, stt=stt, llm=llm, tts=tts)
    return AppServices(
        settings=settings,
        repository=repository,
        embeddings=embeddings,
        stt=stt,
        llm=llm,
        tts=tts,
        rag=rag,
        coach=coach,
    )

