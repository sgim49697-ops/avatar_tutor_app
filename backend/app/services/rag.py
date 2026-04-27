# rag.py - minimal document ingestion and retrieval service for the POC
from __future__ import annotations

from uuid import UUID, uuid4

from app.db.repository import Repository
from app.schemas import ChunkRecord, RetrievedContext
from app.services.model_adapters import EmbeddingService
from app.services.text import chunk_text


class RAGService:
    def __init__(self, repository: Repository, embeddings: EmbeddingService) -> None:
        self.repository = repository
        self.embeddings = embeddings

    async def ingest_document(
        self,
        *,
        user_id: UUID,
        document_id: UUID,
        text: str,
        file_name: str,
        doc_type: str,
    ) -> list[ChunkRecord]:
        chunks: list[ChunkRecord] = []
        for index, chunk in enumerate(chunk_text(text)):
            embedding_result = self.embeddings.embed(chunk)
            chunks.append(
                ChunkRecord(
                    id=uuid4(),
                    document_id=document_id,
                    user_id=user_id,
                    chunk_index=index,
                    chunk_text=chunk,
                    embedding=embedding_result["embedding"],
                    metadata_json={
                        "file_name": file_name,
                        "doc_type": doc_type,
                        "embedding_model": embedding_result["model_name"],
                        "embedding_fallback": embedding_result.fallback,
                    },
                )
            )
        await self.repository.add_document_chunks(chunks)
        return chunks

    async def retrieve(
        self,
        *,
        user_id: UUID,
        query: str,
        document_ids: list[UUID],
        limit: int = 5,
    ) -> list[RetrievedContext]:
        if not query.strip():
            return []
        embedding_result = self.embeddings.embed(query)
        return await self.repository.search_chunks(
            user_id=user_id,
            query_embedding=embedding_result["embedding"],
            document_ids=document_ids,
            limit=limit,
        )

