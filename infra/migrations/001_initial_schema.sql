
-- Real-time Multimodal AI Coach Avatar
-- Suggested PostgreSQL schema for MVP
-- Assumes pgvector extension and UUID generation support

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =========================
-- USERS / PROFILE
-- =========================

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE,
    display_name TEXT,
    preferred_language TEXT DEFAULT 'ko',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS learner_profiles (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    target_role TEXT,
    target_company TEXT,
    practice_mode_default TEXT,
    difficulty_default TEXT,
    time_limit_sec INT DEFAULT 60,
    voice_style TEXT,
    avatar_id TEXT,
    privacy_recording_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
    personalization_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    profile_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================
-- DOCUMENTS / RAG
-- =========================

CREATE TABLE IF NOT EXISTS uploaded_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    file_type TEXT NOT NULL,
    doc_type TEXT NOT NULL,                -- resume, portfolio, slides, jd, etc.
    object_key TEXT NOT NULL,              -- S3/object storage key
    mime_type TEXT,
    language TEXT DEFAULT 'ko',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES uploaded_documents(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    chunk_text TEXT NOT NULL,
    heading TEXT,
    page_no INT,
    slide_no INT,
    section_name TEXT,
    token_count INT,
    source_type TEXT NOT NULL DEFAULT 'user_document',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding VECTOR(1024),                -- BGE-M3 default dimension
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_user_id
    ON document_chunks(user_id);

CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id
    ON document_chunks(document_id);

CREATE INDEX IF NOT EXISTS idx_document_chunks_hnsw_cos
    ON document_chunks USING hnsw (embedding vector_cosine_ops);

-- =========================
-- QUESTION / SCENARIO
-- =========================

CREATE TABLE IF NOT EXISTS scenario_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_type TEXT NOT NULL,           -- interview, presentation, self_intro, followup
    role_target TEXT,
    difficulty TEXT,
    title TEXT NOT NULL,
    prompt_template TEXT NOT NULL,
    rubric_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS generated_questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id UUID,
    turn_index INT,
    mode TEXT NOT NULL,
    question_text TEXT NOT NULL,
    source_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    difficulty TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================
-- SESSION / TURN
-- =========================

CREATE TABLE IF NOT EXISTS session_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mode TEXT NOT NULL,                    -- interview or presentation
    status TEXT NOT NULL DEFAULT 'created',
    target_role TEXT,
    target_company TEXT,
    scenario_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_session_runs_user_id_created_at
    ON session_runs(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS session_turns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES session_runs(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    turn_index INT NOT NULL,
    question_id UUID REFERENCES generated_questions(id) ON DELETE SET NULL,
    question_text TEXT,
    transcript_final TEXT,
    transcript_word_count INT,
    turn_started_at TIMESTAMPTZ,
    turn_ended_at TIMESTAMPTZ,
    latency_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(session_id, turn_index)
);

CREATE INDEX IF NOT EXISTS idx_session_turns_session_id
    ON session_turns(session_id);

-- Optional: sampled signal frames for debugging only
CREATE TABLE IF NOT EXISTS realtime_signal_frames (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES session_runs(id) ON DELETE CASCADE,
    turn_id UUID REFERENCES session_turns(id) ON DELETE CASCADE,
    ts_ms BIGINT NOT NULL,
    source TEXT NOT NULL,                  -- audio or vision
    metrics_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_signal_frames_session_turn
    ON realtime_signal_frames(session_id, turn_id);

CREATE TABLE IF NOT EXISTS turn_signal_summaries (
    turn_id UUID PRIMARY KEY REFERENCES session_turns(id) ON DELETE CASCADE,
    audio_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    vision_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================
-- FEEDBACK / REPORT
-- =========================

CREATE TABLE IF NOT EXISTS coach_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES session_runs(id) ON DELETE CASCADE,
    turn_id UUID REFERENCES session_turns(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    feedback_type TEXT NOT NULL DEFAULT 'turn_feedback',
    feedback_text TEXT NOT NULL,
    evidence_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    rewrite_example TEXT,
    rubric_scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    model_name TEXT,
    prompt_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coach_feedback_session_id
    ON coach_feedback(session_id);

CREATE TABLE IF NOT EXISTS feedback_votes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    feedback_id UUID NOT NULL REFERENCES coach_feedback(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    vote TEXT NOT NULL,                    -- helpful, not_helpful
    comment_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(feedback_id, user_id)
);

CREATE TABLE IF NOT EXISTS report_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL UNIQUE REFERENCES session_runs(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    overall_scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    trend_scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    strengths_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    weaknesses_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    next_actions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    report_markdown TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================
-- PERSONAL MEMORY
-- =========================

CREATE TABLE IF NOT EXISTS memory_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    memory_type TEXT NOT NULL,             -- preference, weakness, strength, exemplar, habit
    scope TEXT NOT NULL DEFAULT 'cross_session',
    content_text TEXT NOT NULL,
    confidence NUMERIC(4,3),
    source_session_id UUID REFERENCES session_runs(id) ON DELETE SET NULL,
    source_turn_id UUID REFERENCES session_turns(id) ON DELETE SET NULL,
    accepted_by_user BOOLEAN,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding VECTOR(1024),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memory_items_user_id
    ON memory_items(user_id);

CREATE INDEX IF NOT EXISTS idx_memory_items_user_type
    ON memory_items(user_id, memory_type);

CREATE INDEX IF NOT EXISTS idx_memory_items_hnsw_cos
    ON memory_items USING hnsw (embedding vector_cosine_ops);

-- =========================
-- OBSERVABILITY / VERSIONING
-- =========================

CREATE TABLE IF NOT EXISTS model_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    component TEXT NOT NULL,               -- stt, llm, embedding, reranker, tts
    model_name TEXT NOT NULL,
    version_tag TEXT,
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS prompt_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_name TEXT NOT NULL,
    version_tag TEXT NOT NULL,
    template_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(prompt_name, version_tag)
);

CREATE TABLE IF NOT EXISTS inference_traces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES session_runs(id) ON DELETE CASCADE,
    turn_id UUID REFERENCES session_turns(id) ON DELETE CASCADE,
    component TEXT NOT NULL,
    model_name TEXT,
    input_tokens INT,
    output_tokens INT,
    latency_ms INT,
    status TEXT NOT NULL,
    trace_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_inference_traces_session_turn
    ON inference_traces(session_id, turn_id);

-- =========================
-- Useful views
-- =========================

CREATE OR REPLACE VIEW v_latest_user_memories AS
SELECT DISTINCT ON (user_id, memory_type, content_text)
    id, user_id, memory_type, scope, content_text, confidence, accepted_by_user,
    source_session_id, source_turn_id, created_at, updated_at
FROM memory_items
ORDER BY user_id, memory_type, content_text, updated_at DESC;

