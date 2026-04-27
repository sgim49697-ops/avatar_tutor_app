# text.py - lightweight document text handling for the POC ingestion path
from __future__ import annotations

import re


def decode_document_bytes(content: bytes, mime_type: str | None = None) -> str:
    if not content:
        return ""
    for encoding in ("utf-8", "utf-16", "cp949", "latin-1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = content.decode("utf-8", errors="ignore")
    text = text.replace("\x00", " ")
    return normalize_text(text)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def chunk_text(text: str, max_chars: int = 1200, overlap_chars: int = 120) -> list[str]:
    text = normalize_text(text)
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = max(0, end - overlap_chars)
    return chunks


def rough_token_count(text: str) -> int:
    return max(1, len(text.split()))

