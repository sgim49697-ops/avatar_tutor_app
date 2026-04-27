# repository.py - in-memory and Postgres persistence for the POC core tables
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

import asyncpg

from app.schemas import ChunkRecord, InferenceTrace, RetrievedContext


class Repository(Protocol):
    async def create_guest_user(self) -> dict[str, Any]:
        ...

    async def create_document(
        self,
        *,
        user_id: UUID,
        file_name: str,
        file_type: str,
        doc_type: str,
        object_key: str,
        mime_type: str | None,
    ) -> dict[str, Any]:
        ...

    async def add_document_chunks(self, chunks: list[ChunkRecord]) -> None:
        ...

    async def list_document_ids_for_user(self, user_id: UUID) -> list[UUID]:
        ...

    async def search_chunks(
        self,
        *,
        user_id: UUID,
        query_embedding: list[float],
        document_ids: list[UUID],
        limit: int,
    ) -> list[RetrievedContext]:
        ...

    async def create_session(
        self,
        *,
        user_id: UUID,
        mode: str,
        target_role: str | None,
        target_company: str | None,
        question_text: str,
    ) -> dict[str, Any]:
        ...

    async def get_session(self, session_id: UUID) -> dict[str, Any] | None:
        ...

    async def create_turn(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        question_text: str,
        transcript_final: str | None = None,
    ) -> dict[str, Any]:
        ...

    async def update_turn_transcript(self, turn_id: UUID, transcript_final: str) -> None:
        ...

    async def save_feedback(
        self,
        *,
        session_id: UUID,
        turn_id: UUID,
        user_id: UUID,
        feedback_text: str,
        evidence_json: list[dict[str, Any]],
        rewrite_example: str | None,
        rubric_scores: dict[str, float],
        model_name: str | None,
    ) -> UUID:
        ...

    async def save_trace(self, trace: InferenceTrace) -> UUID:
        ...


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


class MemoryRepository:
    def __init__(self) -> None:
        self.users: dict[UUID, dict[str, Any]] = {}
        self.documents: dict[UUID, dict[str, Any]] = {}
        self.chunks: dict[UUID, ChunkRecord] = {}
        self.sessions: dict[UUID, dict[str, Any]] = {}
        self.turns: dict[UUID, dict[str, Any]] = {}
        self.feedback: dict[UUID, dict[str, Any]] = {}
        self.traces: dict[UUID, InferenceTrace] = {}

    async def create_guest_user(self) -> dict[str, Any]:
        user_id = uuid4()
        user = {"id": user_id, "display_name": "Guest Coach User", "email": None}
        self.users[user_id] = user
        return user

    async def create_document(
        self,
        *,
        user_id: UUID,
        file_name: str,
        file_type: str,
        doc_type: str,
        object_key: str,
        mime_type: str | None,
    ) -> dict[str, Any]:
        document_id = uuid4()
        document = {
            "id": document_id,
            "user_id": user_id,
            "file_name": file_name,
            "file_type": file_type,
            "doc_type": doc_type,
            "object_key": object_key,
            "mime_type": mime_type,
        }
        self.documents[document_id] = document
        return document

    async def add_document_chunks(self, chunks: list[ChunkRecord]) -> None:
        for chunk in chunks:
            self.chunks[chunk.id] = chunk

    async def list_document_ids_for_user(self, user_id: UUID) -> list[UUID]:
        return [doc_id for doc_id, doc in self.documents.items() if doc["user_id"] == user_id]

    async def search_chunks(
        self,
        *,
        user_id: UUID,
        query_embedding: list[float],
        document_ids: list[UUID],
        limit: int,
    ) -> list[RetrievedContext]:
        allowed_docs = set(document_ids)
        candidates = [
            chunk
            for chunk in self.chunks.values()
            if chunk.user_id == user_id and (not allowed_docs or chunk.document_id in allowed_docs)
        ]
        ranked = sorted(
            candidates,
            key=lambda chunk: cosine_similarity(query_embedding, chunk.embedding),
            reverse=True,
        )
        return [
            RetrievedContext(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                text=chunk.chunk_text,
                score=cosine_similarity(query_embedding, chunk.embedding),
                metadata=chunk.metadata_json,
            )
            for chunk in ranked[:limit]
        ]

    async def create_session(
        self,
        *,
        user_id: UUID,
        mode: str,
        target_role: str | None,
        target_company: str | None,
        question_text: str,
    ) -> dict[str, Any]:
        session_id = uuid4()
        session = {
            "id": session_id,
            "user_id": user_id,
            "mode": mode,
            "target_role": target_role,
            "target_company": target_company,
            "question_text": question_text,
            "status": "created",
        }
        self.sessions[session_id] = session
        return session

    async def get_session(self, session_id: UUID) -> dict[str, Any] | None:
        return self.sessions.get(session_id)

    async def create_turn(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        question_text: str,
        transcript_final: str | None = None,
    ) -> dict[str, Any]:
        turn_id = uuid4()
        turn_index = sum(1 for turn in self.turns.values() if turn["session_id"] == session_id) + 1
        turn = {
            "id": turn_id,
            "session_id": session_id,
            "user_id": user_id,
            "turn_index": turn_index,
            "question_text": question_text,
            "transcript_final": transcript_final,
        }
        self.turns[turn_id] = turn
        return turn

    async def update_turn_transcript(self, turn_id: UUID, transcript_final: str) -> None:
        if turn_id in self.turns:
            self.turns[turn_id]["transcript_final"] = transcript_final

    async def save_feedback(
        self,
        *,
        session_id: UUID,
        turn_id: UUID,
        user_id: UUID,
        feedback_text: str,
        evidence_json: list[dict[str, Any]],
        rewrite_example: str | None,
        rubric_scores: dict[str, float],
        model_name: str | None,
    ) -> UUID:
        feedback_id = uuid4()
        self.feedback[feedback_id] = {
            "id": feedback_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "user_id": user_id,
            "feedback_text": feedback_text,
            "evidence_json": evidence_json,
            "rewrite_example": rewrite_example,
            "rubric_scores": rubric_scores,
            "model_name": model_name,
        }
        return feedback_id

    async def save_trace(self, trace: InferenceTrace) -> UUID:
        self.traces[trace.id] = trace
        return trace.id


class PostgresRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.pool: asyncpg.Pool | None = None

    async def connect(self, auto_migrate: bool = False) -> None:
        self.pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=5)
        if auto_migrate:
            migration_path = Path(__file__).resolve().parents[3] / "infra" / "migrations" / "001_initial_schema.sql"
            if migration_path.exists():
                async with self.pool.acquire() as conn:
                    await conn.execute(migration_path.read_text(encoding="utf-8"))

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    def _pool(self) -> asyncpg.Pool:
        if self.pool is None:
            raise RuntimeError("PostgresRepository.connect() must be called before use")
        return self.pool

    async def create_guest_user(self) -> dict[str, Any]:
        async with self._pool().acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO users (display_name) VALUES ($1) RETURNING id, display_name, email",
                "Guest Coach User",
            )
        return dict(row)

    async def create_document(
        self,
        *,
        user_id: UUID,
        file_name: str,
        file_type: str,
        doc_type: str,
        object_key: str,
        mime_type: str | None,
    ) -> dict[str, Any]:
        async with self._pool().acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO uploaded_documents
                    (user_id, file_name, file_type, doc_type, object_key, mime_type)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id, user_id, file_name, file_type, doc_type, object_key, mime_type
                """,
                user_id,
                file_name,
                file_type,
                doc_type,
                object_key,
                mime_type,
            )
        return dict(row)

    async def add_document_chunks(self, chunks: list[ChunkRecord]) -> None:
        if not chunks:
            return
        async with self._pool().acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO document_chunks
                    (id, document_id, user_id, chunk_index, chunk_text, metadata_json, embedding)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::vector)
                """,
                [
                    (
                        chunk.id,
                        chunk.document_id,
                        chunk.user_id,
                        chunk.chunk_index,
                        chunk.chunk_text,
                        json.dumps(chunk.metadata_json),
                        "[" + ",".join(str(value) for value in chunk.embedding) + "]",
                    )
                    for chunk in chunks
                ],
            )

    async def list_document_ids_for_user(self, user_id: UUID) -> list[UUID]:
        async with self._pool().acquire() as conn:
            rows = await conn.fetch(
                "SELECT id FROM uploaded_documents WHERE user_id = $1 AND is_deleted = false",
                user_id,
            )
        return [row["id"] for row in rows]

    async def search_chunks(
        self,
        *,
        user_id: UUID,
        query_embedding: list[float],
        document_ids: list[UUID],
        limit: int,
    ) -> list[RetrievedContext]:
        vector_literal = "[" + ",".join(str(value) for value in query_embedding) + "]"
        async with self._pool().acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, document_id, chunk_text, metadata_json,
                       1 - (embedding <=> $2::vector) AS score
                FROM document_chunks
                WHERE user_id = $1
                  AND ($3::uuid[] IS NULL OR document_id = ANY($3::uuid[]))
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> $2::vector
                LIMIT $4
                """,
                user_id,
                vector_literal,
                document_ids or None,
                limit,
            )
        return [
            RetrievedContext(
                chunk_id=row["id"],
                document_id=row["document_id"],
                text=row["chunk_text"],
                score=float(row["score"] or 0),
                metadata=dict(row["metadata_json"] or {}),
            )
            for row in rows
        ]

    async def create_session(
        self,
        *,
        user_id: UUID,
        mode: str,
        target_role: str | None,
        target_company: str | None,
        question_text: str,
    ) -> dict[str, Any]:
        async with self._pool().acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO session_runs
                    (user_id, mode, target_role, target_company, scenario_config, status, started_at)
                VALUES ($1, $2, $3, $4, $5::jsonb, 'running', NOW())
                RETURNING id, user_id, mode, target_role, target_company, status
                """,
                user_id,
                mode,
                target_role,
                target_company,
                json.dumps({"question_text": question_text}),
            )
        session = dict(row)
        session["question_text"] = question_text
        return session

    async def get_session(self, session_id: UUID) -> dict[str, Any] | None:
        async with self._pool().acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, user_id, mode, target_role, target_company, status, scenario_config
                FROM session_runs
                WHERE id = $1
                """,
                session_id,
            )
        if not row:
            return None
        session = dict(row)
        scenario_config = dict(session.pop("scenario_config") or {})
        session["question_text"] = scenario_config.get("question_text") or "자기소개를 해주세요."
        return session

    async def create_turn(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        question_text: str,
        transcript_final: str | None = None,
    ) -> dict[str, Any]:
        async with self._pool().acquire() as conn:
            turn_index = await conn.fetchval(
                "SELECT COALESCE(MAX(turn_index), 0) + 1 FROM session_turns WHERE session_id = $1",
                session_id,
            )
            row = await conn.fetchrow(
                """
                INSERT INTO session_turns
                    (session_id, user_id, turn_index, question_text, transcript_final, turn_started_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
                RETURNING id, session_id, user_id, turn_index, question_text, transcript_final
                """,
                session_id,
                user_id,
                turn_index,
                question_text,
                transcript_final,
            )
        return dict(row)

    async def update_turn_transcript(self, turn_id: UUID, transcript_final: str) -> None:
        async with self._pool().acquire() as conn:
            await conn.execute(
                """
                UPDATE session_turns
                SET transcript_final = $2,
                    transcript_word_count = cardinality(regexp_split_to_array(trim($2), '\\s+')),
                    turn_ended_at = NOW()
                WHERE id = $1
                """,
                turn_id,
                transcript_final,
            )

    async def save_feedback(
        self,
        *,
        session_id: UUID,
        turn_id: UUID,
        user_id: UUID,
        feedback_text: str,
        evidence_json: list[dict[str, Any]],
        rewrite_example: str | None,
        rubric_scores: dict[str, float],
        model_name: str | None,
    ) -> UUID:
        async with self._pool().acquire() as conn:
            feedback_id = await conn.fetchval(
                """
                INSERT INTO coach_feedback
                    (session_id, turn_id, user_id, feedback_text, evidence_json,
                     rewrite_example, rubric_scores, model_name, prompt_version)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7::jsonb, $8, 'poc-v1')
                RETURNING id
                """,
                session_id,
                turn_id,
                user_id,
                feedback_text,
                json.dumps(evidence_json),
                rewrite_example,
                json.dumps(rubric_scores),
                model_name,
            )
        return feedback_id

    async def save_trace(self, trace: InferenceTrace) -> UUID:
        async with self._pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO inference_traces
                    (id, session_id, turn_id, component, model_name, input_tokens,
                     output_tokens, latency_ms, status, trace_json, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11)
                """,
                trace.id,
                trace.session_id,
                trace.turn_id,
                trace.component,
                trace.model_name,
                trace.input_tokens,
                trace.output_tokens,
                trace.latency_ms,
                trace.status,
                json.dumps(trace.trace_json),
                trace.created_at,
            )
        return trace.id


async def build_repository(database_url: str | None, auto_migrate: bool) -> Repository:
    if database_url:
        repository = PostgresRepository(database_url)
        await repository.connect(auto_migrate=auto_migrate)
        return repository
    return MemoryRepository()

