# test_workflow.py - backend smoke tests for the POC model pipeline
from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.config import Settings
from app.db.repository import MemoryRepository
from app.schemas import WorkflowInput
from app.services.coach_graph import CoachWorkflow
from app.services.model_adapters import EmbeddingService, LLMService, STTService, TTSService
from app.services.rag import RAGService


@pytest.mark.asyncio
async def test_document_rag_and_coach_workflow_returns_avatar_speak_payload(tmp_path):
    settings = Settings(
        model_mode="mock",
        tts_output_dir=tmp_path,
        database_url=None,
    )
    repository = MemoryRepository()
    embeddings = EmbeddingService(settings)
    rag = RAGService(repository, embeddings)
    coach = CoachWorkflow(
        repository=repository,
        rag=rag,
        stt=STTService(settings),
        llm=LLMService(settings),
        tts=TTSService(settings),
    )

    user = await repository.create_guest_user()
    document = await repository.create_document(
        user_id=user["id"],
        file_name="resume.txt",
        file_type="txt",
        doc_type="resume",
        object_key="poc://resume.txt",
        mime_type="text/plain",
    )
    chunks = await rag.ingest_document(
        user_id=user["id"],
        document_id=document["id"],
        text="백엔드 개발자로 결제 시스템 장애를 분석하고 재발 방지 자동화를 구현했습니다.",
        file_name="resume.txt",
        doc_type="resume",
    )
    session = await repository.create_session(
        user_id=user["id"],
        mode="interview",
        target_role="백엔드 개발자",
        target_company=None,
        question_text="가장 의미 있었던 문제 해결 경험을 말해 주세요.",
    )
    turn = await repository.create_turn(
        session_id=session["id"],
        user_id=user["id"],
        question_text=session["question_text"],
    )

    output = await coach.run(
        WorkflowInput(
            session_id=session["id"],
            turn_id=turn["id"],
            user_id=user["id"],
            mode="interview",
            question_text=session["question_text"],
            transcript_final="결제 장애를 분석하고 자동화로 재발률을 낮춘 경험이 있습니다.",
            uploaded_doc_ids=[document["id"]],
        )
    )

    assert chunks
    assert output.feedback_text
    assert output.rewrite_example
    assert output.retrieved_context
    assert output.tts_audio_url
    assert "tts" in output.fallback_components


@pytest.mark.asyncio
async def test_workflow_without_documents_still_generates_feedback(tmp_path):
    settings = Settings(model_mode="mock", tts_output_dir=tmp_path, database_url=None)
    repository = MemoryRepository()
    embeddings = EmbeddingService(settings)
    rag = RAGService(repository, embeddings)
    coach = CoachWorkflow(
        repository=repository,
        rag=rag,
        stt=STTService(settings),
        llm=LLMService(settings),
        tts=TTSService(settings),
    )
    user = await repository.create_guest_user()
    session_id = uuid4()
    turn_id = uuid4()

    output = await coach.run(
        WorkflowInput(
            session_id=session_id,
            turn_id=turn_id,
            user_id=user["id"],
            mode="presentation",
            question_text="발표 핵심 메시지를 설명해 주세요.",
            transcript_final="저희 서비스는 반복 업무를 줄이고 응답 속도를 개선합니다.",
        )
    )

    assert output.feedback_text
    assert output.retrieved_context == []
    assert output.rubric_scores["structure"] >= 0

