# Real-time AI Coach Avatar POC

This repository contains the first POC skeleton for the real-time AI coach avatar:

`audio/document input -> STT/RAG -> LangGraph 1.0 workflow -> LLM feedback -> TTS/avatar output`

The UI and server are intentionally thin. The important part is that the model adapters and event boundaries are present, so local OSS models can be connected without redesigning the app.

## Structure

- `backend/`: FastAPI REST/WebSocket app and LangGraph Functional API workflow
- `frontend/`: Next.js single-screen POC client
- `infra/migrations/`: initial Postgres + pgvector schema
- `implementation/plans/`: blueprint, schema, and POC plan docs

## Backend

```bash
cd backend
uv pip install -e ".[dev]"
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

By default, the backend can run without Postgres by using the in-memory repository. To use Postgres:

```bash
docker compose up -d postgres redis
export DATABASE_URL=postgresql://avatar:avatar@localhost:5432/avatar_tutor
export AUTO_MIGRATE=true
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Local OSS model runtime

The app supports `MODEL_MODE=local` and attempts these integrations:

- STT: `faster-whisper`
- Embeddings: `BAAI/bge-m3` via `sentence-transformers`
- LLM: OpenAI-compatible local endpoint for Qwen3-8B
- TTS: MeloTTS via `melo.api.TTS`

Install heavy model dependencies separately so the lightweight smoke tests stay quick. When installing PyTorch, use the CUDA 12.8 index:

```bash
uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
uv pip install faster-whisper sentence-transformers melo-tts
```

Set `MODEL_FALLBACK_ENABLED=false` if you want missing local models to fail loudly instead of returning deterministic POC fallbacks.

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

## Smoke Tests

```bash
cd backend
uv run pytest
```

