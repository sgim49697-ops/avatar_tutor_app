# schemas.py - typed REST, WebSocket, and workflow payloads
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


PracticeMode = Literal["interview", "presentation"]


class GuestAuthResponse(BaseModel):
    user_id: UUID
    display_name: str


class DocumentResponse(BaseModel):
    document_id: UUID
    file_name: str
    doc_type: str
    chunk_count: int


class CreateSessionRequest(BaseModel):
    user_id: UUID
    mode: PracticeMode = "interview"
    target_role: str | None = None
    target_company: str | None = None
    question_text: str | None = None


class SessionResponse(BaseModel):
    session_id: UUID
    user_id: UUID
    mode: PracticeMode
    question_text: str
    status: str = "created"


class ChunkRecord(BaseModel):
    id: UUID
    document_id: UUID
    user_id: UUID
    chunk_index: int
    chunk_text: str
    embedding: list[float] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class RetrievedContext(BaseModel):
    chunk_id: UUID
    document_id: UUID
    text: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowInput(BaseModel):
    session_id: UUID
    turn_id: UUID
    user_id: UUID
    mode: PracticeMode
    question_text: str
    audio_blob_ref: str | None = None
    transcript_final: str | None = None
    audio_metrics: dict[str, Any] = Field(default_factory=dict)
    vision_metrics: dict[str, Any] = Field(default_factory=dict)
    uploaded_doc_ids: list[UUID] = Field(default_factory=list)


class WorkflowOutput(BaseModel):
    transcript_final: str
    retrieved_context: list[RetrievedContext] = Field(default_factory=list)
    feedback_text: str
    rewrite_example: str | None = None
    rubric_scores: dict[str, float] = Field(default_factory=dict)
    tts_audio_url: str | None = None
    latency_ms: int
    trace_ids: list[UUID] = Field(default_factory=list)
    fallback_components: list[str] = Field(default_factory=list)


class WebSocketEvent(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class InferenceTrace(BaseModel):
    id: UUID
    session_id: UUID | None = None
    turn_id: UUID | None = None
    component: str
    model_name: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None
    status: str
    trace_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
