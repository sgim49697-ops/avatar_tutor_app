// events.ts - shared client-side event types for the POC WebSocket gateway
export type PracticeMode = "interview" | "presentation";

export type ServerEvent =
  | {
      type: "session.ready";
      payload: { session_id?: string; mode?: PracticeMode; question_text?: string };
    }
  | { type: "question.generated"; payload: { question_text: string } }
  | { type: "transcript.final"; payload: { text: string } }
  | {
      type: "feedback.generated";
      payload: {
        feedback_text: string;
        rewrite_example?: string | null;
        rubric_scores?: Record<string, number>;
        retrieved_context?: Array<{ text: string; score: number }>;
        latency_ms?: number;
        fallback_components?: string[];
      };
    }
  | { type: "avatar.speak"; payload: { text: string; audio_url?: string | null } }
  | { type: "report.ready"; payload: { message: string } }
  | { type: "error"; payload: { message: string } };

export type ClientEvent =
  | { type: "session.init"; payload: { uploaded_doc_ids: string[] } }
  | { type: "audio.chunk"; payload: { mime_type: string; data_base64: string } }
  | {
      type: "feature.frame";
      payload: {
        audio_metrics?: Record<string, number | null>;
        vision_metrics?: Record<string, number | null>;
      };
    }
  | {
      type: "turn.end";
      payload: { transcript_final?: string; question_text?: string };
    }
  | { type: "session.end"; payload: Record<string, never> };

