// poc-coach-client.tsx - browser POC for session, audio, feedback, and avatar output
"use client";

import {
  Bot,
  FileText,
  Loader2,
  Mic,
  MicOff,
  Play,
  Radio,
  Send,
  Square,
  Upload,
  UserPlus,
} from "lucide-react";
import { ChangeEvent, useCallback, useEffect, useRef, useState } from "react";

import {
  API_BASE_URL,
  WS_BASE_URL,
  blobToBase64,
  makeAudioUrl,
  postForm,
  postJson,
  sendEvent,
} from "@/lib/api";
import type { PracticeMode, ServerEvent } from "@/types/events";

type GuestResponse = {
  user_id: string;
  display_name: string;
};

type DocumentResponse = {
  document_id: string;
  file_name: string;
  doc_type: string;
  chunk_count: number;
};

type SessionResponse = {
  session_id: string;
  user_id: string;
  mode: PracticeMode;
  question_text: string;
  status: string;
};

type FeedbackState = {
  feedbackText: string;
  rewriteExample?: string | null;
  rubricScores?: Record<string, number>;
  retrievedContext?: Array<{ text: string; score: number }>;
  latencyMs?: number;
  fallbackComponents?: string[];
};

export function PocCoachClient() {
  const [user, setUser] = useState<GuestResponse | null>(null);
  const [documents, setDocuments] = useState<DocumentResponse[]>([]);
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [mode, setMode] = useState<PracticeMode>("interview");
  const [targetRole, setTargetRole] = useState("백엔드 개발자");
  const [manualTranscript, setManualTranscript] = useState("");
  const [transcript, setTranscript] = useState("");
  const [feedback, setFeedback] = useState<FeedbackState | null>(null);
  const [status, setStatus] = useState("대기 중");
  const [isRecording, setIsRecording] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isBusy, setIsBusy] = useState(false);
  const [eventLog, setEventLog] = useState<string[]>([]);

  const socketRef = useRef<WebSocket | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const appendLog = useCallback((message: string) => {
    setEventLog((prev) => [message, ...prev].slice(0, 8));
  }, []);

  const ensureGuest = useCallback(async () => {
    if (user) {
      return user;
    }
    const guest = await postJson<GuestResponse, Record<string, never>>("/api/auth/guest", {});
    setUser(guest);
    appendLog(`guest ready: ${guest.user_id.slice(0, 8)}`);
    return guest;
  }, [appendLog, user]);

  const handleServerEvent = useCallback(
    (event: ServerEvent) => {
      appendLog(event.type);
      if (event.type === "question.generated") {
        setSession((prev) =>
          prev ? { ...prev, question_text: event.payload.question_text } : prev,
        );
      }
      if (event.type === "transcript.final") {
        setTranscript(event.payload.text);
        setStatus("피드백 생성 완료");
      }
      if (event.type === "feedback.generated") {
        setFeedback({
          feedbackText: event.payload.feedback_text,
          rewriteExample: event.payload.rewrite_example,
          rubricScores: event.payload.rubric_scores,
          retrievedContext: event.payload.retrieved_context,
          latencyMs: event.payload.latency_ms,
          fallbackComponents: event.payload.fallback_components,
        });
      }
      if (event.type === "avatar.speak") {
        setIsSpeaking(true);
        if (event.payload.audio_url) {
          const audio = new Audio(makeAudioUrl(event.payload.audio_url));
          audioRef.current = audio;
          audio.onended = () => setIsSpeaking(false);
          audio.onerror = () => setIsSpeaking(false);
          void audio.play().catch(() => {
            setTimeout(() => setIsSpeaking(false), 1200);
          });
        } else {
          setTimeout(() => setIsSpeaking(false), 1200);
        }
      }
      if (event.type === "error") {
        setStatus(event.payload.message);
        setIsBusy(false);
      }
    },
    [appendLog],
  );

  const connectSocket = useCallback(
    (nextSession: SessionResponse, uploadedDocIds: string[]) => {
      socketRef.current?.close();
      const socket = new WebSocket(`${WS_BASE_URL}/ws/sessions/${nextSession.session_id}`);
      socketRef.current = socket;
      socket.onopen = () => {
        appendLog("websocket open");
        sendEvent(socket, {
          type: "session.init",
          payload: { uploaded_doc_ids: uploadedDocIds },
        });
        sendEvent(socket, {
          type: "feature.frame",
          payload: {
            audio_metrics: { wpm: null, pause_count: 0 },
            vision_metrics: {
              eyeContactScore: null,
              headStability: null,
              postureStability: null,
              facePresence: null,
            },
          },
        });
      };
      socket.onmessage = (message) => {
        handleServerEvent(JSON.parse(message.data) as ServerEvent);
      };
      socket.onclose = () => appendLog("websocket closed");
      socket.onerror = () => setStatus("WebSocket 연결 오류");
    },
    [appendLog, handleServerEvent],
  );

  const uploadDocument = async (event: ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files?.[0];
    if (!selectedFile) {
      return;
    }
    setIsBusy(true);
    setStatus("문서 업로드 중");
    try {
      const guest = await ensureGuest();
      const formData = new FormData();
      formData.append("user_id", guest.user_id);
      formData.append("doc_type", "resume");
      formData.append("file", selectedFile);
      const response = await postForm<DocumentResponse>("/api/documents", formData);
      setDocuments((prev) => [...prev, response]);
      appendLog(`document chunks: ${response.chunk_count}`);
      setStatus("문서 준비 완료");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "문서 업로드 실패");
    } finally {
      setIsBusy(false);
      event.target.value = "";
    }
  };

  const createSession = async () => {
    setIsBusy(true);
    setStatus("세션 생성 중");
    try {
      const guest = await ensureGuest();
      const response = await postJson<
        SessionResponse,
        {
          user_id: string;
          mode: PracticeMode;
          target_role: string;
        }
      >("/api/sessions", {
        user_id: guest.user_id,
        mode,
        target_role: targetRole,
      });
      setSession(response);
      setTranscript("");
      setFeedback(null);
      connectSocket(
        response,
        documents.map((document) => document.document_id),
      );
      setStatus("질문 준비 완료");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "세션 생성 실패");
    } finally {
      setIsBusy(false);
    }
  };

  const startRecording = async () => {
    if (!session || !socketRef.current) {
      setStatus("먼저 세션을 시작해 주세요");
      return;
    }
    setTranscript("");
    setFeedback(null);
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    streamRef.current = stream;
    const recorder = new MediaRecorder(stream);
    recorderRef.current = recorder;
    recorder.ondataavailable = (event) => {
      if (event.data.size === 0) {
        return;
      }
      void blobToBase64(event.data).then((dataBase64) => {
        sendEvent(socketRef.current, {
          type: "audio.chunk",
          payload: { mime_type: event.data.type || "audio/webm", data_base64: dataBase64 },
        });
      });
    };
    recorder.start(1000);
    setIsRecording(true);
    setStatus("녹음 중");
  };

  const stopRecording = () => {
    recorderRef.current?.requestData();
    recorderRef.current?.stop();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    setIsRecording(false);
    setStatus("코칭 워크플로우 실행 중");
    setTimeout(() => {
      sendEvent(socketRef.current, {
        type: "turn.end",
        payload: {
          transcript_final: manualTranscript.trim() || undefined,
          question_text: session?.question_text,
        },
      });
    }, 250);
  };

  const submitManualTurn = () => {
    if (!session) {
      setStatus("먼저 세션을 시작해 주세요");
      return;
    }
    setFeedback(null);
    setTranscript("");
    setStatus("텍스트 답변으로 코칭 실행 중");
    sendEvent(socketRef.current, {
      type: "turn.end",
      payload: {
        transcript_final: manualTranscript.trim(),
        question_text: session.question_text,
      },
    });
  };

  useEffect(() => {
    return () => {
      socketRef.current?.close();
      audioRef.current?.pause();
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  return (
    <main className="appShell">
      <section className="topBand">
        <div>
          <p className="eyebrow">Real-time AI Coach Avatar POC</p>
          <h1>Coach Turn Console</h1>
        </div>
        <div className="statusRail">
          <Radio size={18} />
          <span>{status}</span>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="controlSurface">
          <div className="toolbarRow">
            <button className="iconButton" onClick={ensureGuest} disabled={isBusy} title="게스트 생성">
              <UserPlus size={18} />
              <span>Guest</span>
            </button>
            <label className="iconButton fileButton" title="문서 업로드">
              <Upload size={18} />
              <span>Upload</span>
              <input type="file" accept=".txt,.md,.csv,.json" onChange={uploadDocument} />
            </label>
            <button className="iconButton primary" onClick={createSession} disabled={isBusy}>
              {isBusy ? <Loader2 className="spin" size={18} /> : <Play size={18} />}
              <span>Session</span>
            </button>
          </div>

          <div className="fieldGrid">
            <label>
              Mode
              <select value={mode} onChange={(event) => setMode(event.target.value as PracticeMode)}>
                <option value="interview">Interview</option>
                <option value="presentation">Presentation</option>
              </select>
            </label>
            <label>
              Target
              <input value={targetRole} onChange={(event) => setTargetRole(event.target.value)} />
            </label>
          </div>

          <div className="questionPanel">
            <span>Question</span>
            <p>{session?.question_text || "질문 대기 중"}</p>
          </div>

          <label className="transcriptInput">
            Manual transcript fallback
            <textarea
              value={manualTranscript}
              onChange={(event) => setManualTranscript(event.target.value)}
              placeholder="답변 transcript"
            />
          </label>

          <div className="recordRow">
            <button
              className="roundAction record"
              onClick={startRecording}
              disabled={!session || isRecording}
              title="녹음 시작"
            >
              <Mic size={22} />
            </button>
            <button
              className="roundAction stop"
              onClick={stopRecording}
              disabled={!isRecording}
              title="녹음 종료"
            >
              <Square size={20} />
            </button>
            <button
              className="iconButton"
              onClick={submitManualTurn}
              disabled={!session || !manualTranscript.trim()}
            >
              <Send size={18} />
              <span>Send</span>
            </button>
            <span className={isRecording ? "recordingBadge active" : "recordingBadge"}>
              {isRecording ? "Recording" : "Idle"}
            </span>
          </div>

          <div className="documentList">
            <FileText size={18} />
            <span>
              {documents.length
                ? `${documents.length} document(s) indexed`
                : "No document indexed yet"}
            </span>
          </div>
        </div>

        <div className="avatarStage">
          <div className={isSpeaking ? "avatarHead speaking" : "avatarHead"}>
            <Bot size={62} />
            <div className="mouth" />
          </div>
          <div className="avatarStatus">
            {isSpeaking ? <Mic size={18} /> : <MicOff size={18} />}
            <span>{isSpeaking ? "Speaking feedback" : "Waiting for turn"}</span>
          </div>
        </div>

        <div className="resultSurface">
          <section>
            <h2>Transcript</h2>
            <p>{transcript || "Transcript pending"}</p>
          </section>
          <section>
            <h2>Coach Feedback</h2>
            <p>{feedback?.feedbackText || "Feedback pending"}</p>
            {feedback?.rewriteExample ? (
              <div className="rewriteBox">
                <span>Rewrite</span>
                <p>{feedback.rewriteExample}</p>
              </div>
            ) : null}
          </section>
          <section className="metricsStrip">
            {["structure", "specificity", "relevance", "delivery"].map((key) => (
              <div key={key}>
                <span>{key}</span>
                <strong>{Math.round((feedback?.rubricScores?.[key] ?? 0) * 100)}</strong>
              </div>
            ))}
          </section>
          <section>
            <h2>RAG Evidence</h2>
            <p>
              {feedback?.retrievedContext?.length
                ? feedback.retrievedContext[0].text
                : "Evidence pending"}
            </p>
          </section>
        </div>

        <aside className="eventSurface">
          <h2>Runtime</h2>
          <dl>
            <div>
              <dt>API</dt>
              <dd>{API_BASE_URL}</dd>
            </div>
            <div>
              <dt>User</dt>
              <dd>{user?.user_id.slice(0, 8) || "none"}</dd>
            </div>
            <div>
              <dt>Session</dt>
              <dd>{session?.session_id.slice(0, 8) || "none"}</dd>
            </div>
            <div>
              <dt>Latency</dt>
              <dd>{feedback?.latencyMs ? `${feedback.latencyMs} ms` : "pending"}</dd>
            </div>
            <div>
              <dt>Fallback</dt>
              <dd>{feedback?.fallbackComponents?.join(", ") || "none"}</dd>
            </div>
          </dl>
          <ol>
            {eventLog.map((event, index) => (
              <li key={`${event}-${index}`}>{event}</li>
            ))}
          </ol>
        </aside>
      </section>
    </main>
  );
}
