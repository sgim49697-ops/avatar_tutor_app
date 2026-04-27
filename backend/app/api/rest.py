# rest.py - POC REST endpoints for users, documents, and sessions
from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.dependencies import AppServices
from app.schemas import CreateSessionRequest, DocumentResponse, GuestAuthResponse, SessionResponse
from app.services.text import decode_document_bytes

router = APIRouter()


def services_from(request: Request) -> AppServices:
    return request.app.state.services


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    services = services_from(request)
    return {"status": "ok", "model_mode": services.settings.model_mode}


@router.post("/api/auth/guest", response_model=GuestAuthResponse)
async def create_guest_user(request: Request) -> GuestAuthResponse:
    services = services_from(request)
    user = await services.repository.create_guest_user()
    return GuestAuthResponse(user_id=user["id"], display_name=user["display_name"])


@router.post("/api/documents", response_model=DocumentResponse)
async def upload_document(
    request: Request,
    user_id: UUID = Form(...),
    doc_type: str = Form("resume"),
    file: UploadFile = File(...),
) -> DocumentResponse:
    services = services_from(request)
    content = await file.read()
    text = decode_document_bytes(content, file.content_type)
    if not text:
        raise HTTPException(status_code=400, detail="Uploaded document did not contain readable text")

    document = await services.repository.create_document(
        user_id=user_id,
        file_name=file.filename or "uploaded-document.txt",
        file_type=Path(file.filename or "txt").suffix.lstrip(".") or "txt",
        doc_type=doc_type,
        object_key=f"poc://documents/{user_id}/{file.filename or 'uploaded-document.txt'}",
        mime_type=file.content_type,
    )
    chunks = await services.rag.ingest_document(
        user_id=user_id,
        document_id=document["id"],
        text=text,
        file_name=document["file_name"],
        doc_type=doc_type,
    )
    return DocumentResponse(
        document_id=document["id"],
        file_name=document["file_name"],
        doc_type=doc_type,
        chunk_count=len(chunks),
    )


@router.post("/api/sessions", response_model=SessionResponse)
async def create_session(
    request: Request,
    payload: CreateSessionRequest,
) -> SessionResponse:
    services = services_from(request)
    question_text = payload.question_text or _default_question(payload.mode, payload.target_role)
    session = await services.repository.create_session(
        user_id=payload.user_id,
        mode=payload.mode,
        target_role=payload.target_role,
        target_company=payload.target_company,
        question_text=question_text,
    )
    return SessionResponse(
        session_id=session["id"],
        user_id=session["user_id"],
        mode=session["mode"],
        question_text=question_text,
        status=session.get("status", "created"),
    )


@router.get("/api/sessions/{session_id}", response_model=SessionResponse)
async def get_session(request: Request, session_id: UUID) -> SessionResponse:
    services = services_from(request)
    session = await services.repository.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionResponse(
        session_id=session["id"],
        user_id=session["user_id"],
        mode=session["mode"],
        question_text=session["question_text"],
        status=session.get("status", "created"),
    )


def _default_question(mode: str, target_role: str | None) -> str:
    if mode == "presentation":
        return "발표의 핵심 메시지와 청중이 기억해야 할 한 가지를 1분 안에 설명해 주세요."
    if target_role:
        return f"{target_role} 포지션에 지원한 이유와 가장 관련 있는 경험을 소개해 주세요."
    return "자기소개와 함께 오늘 연습에서 개선하고 싶은 답변 포인트를 말해 주세요."

