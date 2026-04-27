# Real-time AI Coach Avatar POC 기본구성 계획

## 1. 목표

이 POC는 제품 완성도가 아니라 `입력 -> STT/문서검색 -> LangGraph 1.0 코칭 워크플로우 -> LLM 피드백 -> TTS 출력` 왕복을 검증한다.

프론트엔드와 백엔드는 “모양과 연결점”만 갖춘다. 정교한 리포트, 고급 아바타, 실시간 MediaPipe 분석, 모바일 최적화는 MVP 이후로 미룬다.

## 2. 구현 범위

- Frontend: Next.js 단일 화면에서 guest 시작, 문서 업로드, 세션 생성, 녹음/종료, transcript, feedback, TTS 재생, avatar speaking placeholder를 제공한다.
- Backend: FastAPI 단일 앱에서 `/api/auth/guest`, `/api/documents`, `/api/sessions`, `/ws/sessions/{session_id}`를 제공한다.
- DB: `infra/migrations/001_initial_schema.sql`은 제공 schema를 그대로 초기 migration으로 사용한다. POC 기본 실행은 인메모리 저장소를 허용하고, `DATABASE_URL` 설정 시 Postgres/pgvector로 전환한다.
- Model adapters:
  - STT: `faster-whisper`
  - Embedding: Ollama `embeddinggemma:300m-qat-q4_0` (`768` dimensions)
  - LLM: Ollama `hf.co/LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct-GGUF:Q5_K_M`
  - TTS: MeloTTS
- LangGraph: 1.0 Functional API의 `@entrypoint`/`@task`만 사용한다.

## 3. 이벤트와 데이터 흐름

Client to Server:

- `session.init`
- `audio.chunk`
- `feature.frame`
- `turn.end`
- `session.end`

Server to Client:

- `session.ready`
- `question.generated`
- `transcript.final`
- `feedback.generated`
- `avatar.speak`
- `report.ready`
- `error`

Workflow input:

- `session_id`, `turn_id`, `user_id`, `mode`, `question_text`
- `audio_blob_ref`, `transcript_final`
- `audio_metrics`, `vision_metrics`
- `uploaded_doc_ids`

Workflow output:

- `transcript_final`
- `retrieved_context`
- `feedback_text`
- `rewrite_example`
- `rubric_scores`
- `tts_audio_url`
- `latency_ms`
- `trace_ids`

## 4. 검증 기준

- Backend smoke: guest user 생성, session 생성, document chunking, vector retrieval, workflow 실행이 통과한다.
- Model smoke: `MODEL_MODE=local`에서 로컬 모델/서버가 있으면 실제 STT, Ollama embedding, EXAONE, MeloTTS를 호출한다.
- Fallback smoke: 로컬 모델이 없어도 `MODEL_FALLBACK_ENABLED=true`이면 텍스트 피드백과 placeholder audio를 반환한다.
- WebSocket smoke: 브라우저에서 `turn.end` 후 `transcript.final`, `feedback.generated`, `avatar.speak` 순서로 이벤트를 받는다.
- RAG smoke: 업로드 문서가 있으면 feedback payload의 `retrieved_context`에 최소 1개 chunk가 포함된다.

## 5. 기본 실행 정책

- raw video는 저장하지 않는다.
- audio chunk는 STT 처리를 위한 임시 파일로만 사용한다.
- 진단성 표현은 금지하고 관찰 가능한 답변 구조/전달 지표만 피드백한다.
- 무거운 모델 의존성은 기본 dev 설치에서 제외하고, PyTorch 설치 시 CUDA 12.8 index URL을 명시한다.
