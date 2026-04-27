# websocket.py - realtime session event gateway for the POC
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.dependencies import AppServices
from app.schemas import WebSocketEvent, WorkflowInput
from app.services.model_adapters import write_audio_temp_file

router = APIRouter()


@dataclass
class SessionSocketState:
    audio_chunks: list[bytes] = field(default_factory=list)
    audio_mime_type: str = "audio/webm"
    audio_metrics: dict[str, Any] = field(default_factory=lambda: {"wpm": None, "pause_count": 0})
    vision_metrics: dict[str, Any] = field(
        default_factory=lambda: {
            "eyeContactScore": None,
            "headStability": None,
            "postureStability": None,
            "facePresence": None,
        }
    )
    uploaded_doc_ids: list[UUID] = field(default_factory=list)


@router.websocket("/ws/sessions/{session_id}")
async def session_socket(websocket: WebSocket, session_id: UUID) -> None:
    await websocket.accept()
    services: AppServices = websocket.app.state.services
    session = await services.repository.get_session(session_id)
    if not session:
        await _send(websocket, "error", {"message": "Session not found"})
        await websocket.close(code=4404)
        return

    state = SessionSocketState()
    await _send(
        websocket,
        "session.ready",
        {
            "session_id": str(session_id),
            "mode": session["mode"],
            "question_text": session["question_text"],
        },
    )
    await _send(websocket, "question.generated", {"question_text": session["question_text"]})

    try:
        while True:
            raw_event = await websocket.receive_json()
            event = WebSocketEvent.model_validate(raw_event)
            if event.type == "session.init":
                state.uploaded_doc_ids = [
                    UUID(value) for value in event.payload.get("uploaded_doc_ids", []) if value
                ]
                if not state.uploaded_doc_ids:
                    state.uploaded_doc_ids = await services.repository.list_document_ids_for_user(
                        session["user_id"]
                    )
                await _send(websocket, "session.ready", {"session_id": str(session_id)})
            elif event.type == "audio.chunk":
                data_base64 = event.payload.get("data_base64", "")
                if data_base64:
                    state.audio_chunks.append(base64.b64decode(data_base64))
                state.audio_mime_type = event.payload.get("mime_type") or state.audio_mime_type
            elif event.type == "feature.frame":
                state.vision_metrics.update(event.payload.get("vision_metrics") or {})
                state.audio_metrics.update(event.payload.get("audio_metrics") or {})
            elif event.type == "turn.end":
                await _handle_turn_end(
                    websocket=websocket,
                    services=services,
                    session=session,
                    socket_state=state,
                    payload=event.payload,
                )
                state.audio_chunks.clear()
            elif event.type == "session.end":
                await _send(websocket, "report.ready", {"message": "POC report is not implemented yet"})
                await websocket.close(code=1000)
                return
            else:
                await _send(websocket, "error", {"message": f"Unsupported event type: {event.type}"})
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await _send(websocket, "error", {"message": str(exc)})
        await websocket.close(code=1011)


async def _handle_turn_end(
    *,
    websocket: WebSocket,
    services: AppServices,
    session: dict[str, Any],
    socket_state: SessionSocketState,
    payload: dict[str, Any],
) -> None:
    transcript_final = payload.get("transcript_final")
    question_text = payload.get("question_text") or session["question_text"]
    audio_path: str | None = None
    if socket_state.audio_chunks:
        suffix = ".webm" if "webm" in socket_state.audio_mime_type else ".wav"
        audio_path = write_audio_temp_file(b"".join(socket_state.audio_chunks), suffix=suffix)

    turn = await services.repository.create_turn(
        session_id=session["id"],
        user_id=session["user_id"],
        question_text=question_text,
        transcript_final=transcript_final,
    )
    workflow_output = await services.coach.run(
        WorkflowInput(
            session_id=session["id"],
            turn_id=turn["id"],
            user_id=session["user_id"],
            mode=session["mode"],
            question_text=question_text,
            audio_blob_ref=audio_path,
            transcript_final=transcript_final,
            audio_metrics=socket_state.audio_metrics,
            vision_metrics=socket_state.vision_metrics,
            uploaded_doc_ids=socket_state.uploaded_doc_ids,
        )
    )
    await _send(websocket, "transcript.final", {"text": workflow_output.transcript_final})
    await _send(
        websocket,
        "feedback.generated",
        {
            "feedback_text": workflow_output.feedback_text,
            "rewrite_example": workflow_output.rewrite_example,
            "rubric_scores": workflow_output.rubric_scores,
            "retrieved_context": [
                context.model_dump(mode="json") for context in workflow_output.retrieved_context
            ],
            "latency_ms": workflow_output.latency_ms,
            "fallback_components": workflow_output.fallback_components,
        },
    )
    await _send(
        websocket,
        "avatar.speak",
        {
            "text": workflow_output.feedback_text,
            "audio_url": workflow_output.tts_audio_url,
        },
    )


async def _send(websocket: WebSocket, event_type: str, payload: dict[str, Any]) -> None:
    await websocket.send_json({"type": event_type, "payload": payload})

