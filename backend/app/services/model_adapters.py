# model_adapters.py - local OSS model adapters with explicit POC fallbacks
from __future__ import annotations

import hashlib
import json
import math
import tempfile
import time
import wave
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import numpy as np

from app.core.config import Settings


class ModelResult(dict):
    @property
    def fallback(self) -> bool:
        return bool(self.get("fallback"))


class ModelUnavailable(RuntimeError):
    pass


def _allow_fallback(settings: Settings, component: str, error: Exception) -> None:
    if not settings.model_fallback_enabled:
        raise ModelUnavailable(f"{component} local model is unavailable: {error}") from error


def _hash_embedding(text: str, dimensions: int = 1024) -> list[float]:
    values = np.zeros(dimensions, dtype=np.float32)
    words = text.split() or [text]
    for index, word in enumerate(words):
        digest = hashlib.sha256(f"{index}:{word}".encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        values[bucket] += sign
    norm = float(np.linalg.norm(values))
    if norm > 0:
        values = values / norm
    return values.tolist()


class EmbeddingService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: Any | None = None

    def embed(self, text: str) -> ModelResult:
        start = time.perf_counter()
        if self.settings.model_mode == "mock":
            return ModelResult(
                embedding=_hash_embedding(text),
                model_name="mock-bge-m3",
                latency_ms=int((time.perf_counter() - start) * 1000),
                fallback=True,
            )
        try:
            if self._model is None:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(
                    self.settings.embedding_model_name,
                    device=self.settings.model_device,
                )
            embedding = self._model.encode([text], normalize_embeddings=True)[0].tolist()
            return ModelResult(
                embedding=embedding,
                model_name=self.settings.embedding_model_name,
                latency_ms=int((time.perf_counter() - start) * 1000),
                fallback=False,
            )
        except Exception as exc:  # pragma: no cover - depends on local model installation
            _allow_fallback(self.settings, "embedding", exc)
            return ModelResult(
                embedding=_hash_embedding(text),
                model_name=f"{self.settings.embedding_model_name}:fallback",
                latency_ms=int((time.perf_counter() - start) * 1000),
                fallback=True,
                error=str(exc),
            )


class STTService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: Any | None = None

    def transcribe(self, audio_path: str | None) -> ModelResult:
        start = time.perf_counter()
        if self.settings.model_mode == "mock":
            return ModelResult(
                transcript="저는 백엔드 개발 경험을 바탕으로 문제를 구조화하고, 팀과 협업해 안정적으로 개선한 사례가 있습니다.",
                model_name="mock-faster-whisper",
                latency_ms=int((time.perf_counter() - start) * 1000),
                fallback=True,
            )
        if not audio_path:
            return ModelResult(
                transcript="",
                model_name=self.settings.stt_model_name,
                latency_ms=int((time.perf_counter() - start) * 1000),
                fallback=True,
                error="no audio path provided",
            )
        try:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(
                    self.settings.stt_model_name,
                    device=self.settings.model_device,
                    compute_type="float16" if self.settings.model_device == "cuda" else "int8",
                )
            segments, _info = self._model.transcribe(audio_path, vad_filter=True)
            transcript = " ".join(segment.text.strip() for segment in segments).strip()
            return ModelResult(
                transcript=transcript,
                model_name=self.settings.stt_model_name,
                latency_ms=int((time.perf_counter() - start) * 1000),
                fallback=False,
            )
        except Exception as exc:  # pragma: no cover - depends on local model installation
            _allow_fallback(self.settings, "stt", exc)
            return ModelResult(
                transcript="[STT fallback] 음성 인식 모델을 사용할 수 없어 데모용 답변으로 처리했습니다.",
                model_name=f"{self.settings.stt_model_name}:fallback",
                latency_ms=int((time.perf_counter() - start) * 1000),
                fallback=True,
                error=str(exc),
            )


class LLMService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def compose_feedback(
        self,
        *,
        question_text: str,
        transcript: str,
        retrieved_context: list[dict[str, Any]],
        audio_metrics: dict[str, Any],
        vision_metrics: dict[str, Any],
    ) -> ModelResult:
        start = time.perf_counter()
        if self.settings.model_mode == "mock":
            return self._fallback_feedback(
                question_text=question_text,
                transcript=transcript,
                retrieved_context=retrieved_context,
                start=start,
                reason="mock mode",
            )

        context_text = "\n".join(
            f"- {item.get('text', '')[:700]}" for item in retrieved_context[:5]
        )
        prompt = f"""
당신은 면접/발표 코칭 AI입니다. 진단성 표현은 금지하고 관찰 가능한 행동과 답변 구조만 코칭하세요.

질문:
{question_text}

사용자 답변:
{transcript}

검색된 사용자 문서 근거:
{context_text or "없음"}

오디오 지표:
{json.dumps(audio_metrics, ensure_ascii=False)}

비전 지표:
{json.dumps(vision_metrics, ensure_ascii=False)}

다음 JSON만 반환하세요:
{{
  "feedback_text": "2~4문장 한국어 피드백",
  "rewrite_example": "더 나은 답변 예시 2~3문장",
  "rubric_scores": {{
    "structure": 0.0,
    "specificity": 0.0,
    "relevance": 0.0,
    "delivery": 0.0
  }}
}}
""".strip()
        try:
            payload: dict[str, Any] = {
                "model": self.settings.llm_model_name,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a concise Korean interview and presentation coach.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "response_format": {"type": "json_object"},
            }
            response = self._post_chat_completion(payload)
            if response.status_code in {400, 422}:
                payload.pop("response_format", None)
                response = self._post_chat_completion(payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = _parse_json_object(content)
            return ModelResult(
                feedback_text=str(parsed.get("feedback_text", "")).strip(),
                rewrite_example=str(parsed.get("rewrite_example", "")).strip() or None,
                rubric_scores=_normalize_scores(parsed.get("rubric_scores") or {}),
                model_name=self.settings.llm_model_name,
                latency_ms=int((time.perf_counter() - start) * 1000),
                fallback=False,
                input_tokens=max(1, math.ceil(len(prompt) / 4)),
                output_tokens=max(1, math.ceil(len(content) / 4)),
            )
        except Exception as exc:  # pragma: no cover - depends on local model server
            _allow_fallback(self.settings, "llm", exc)
            return self._fallback_feedback(
                question_text=question_text,
                transcript=transcript,
                retrieved_context=retrieved_context,
                start=start,
                reason=str(exc),
            )

    def _post_chat_completion(self, payload: dict[str, Any]) -> httpx.Response:
        return httpx.post(
            f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
            json=payload,
            timeout=self.settings.llm_timeout_sec,
        )

    def _fallback_feedback(
        self,
        *,
        question_text: str,
        transcript: str,
        retrieved_context: list[dict[str, Any]],
        start: float,
        reason: str,
    ) -> ModelResult:
        has_context = bool(retrieved_context)
        word_count = len(transcript.split())
        specificity = 0.72 if has_context else 0.55
        structure = 0.65 if word_count >= 20 else 0.42
        feedback = (
            "답변의 핵심 경험은 전달됐지만, 결론을 먼저 말한 뒤 근거를 붙이면 더 명확합니다. "
            "업로드 문서의 프로젝트/성과 표현을 한 문장 근거로 연결하면 설득력이 좋아집니다."
            if has_context
            else "답변은 시작됐지만 구체적인 상황, 행동, 결과가 더 필요합니다. "
            "첫 문장에 결론을 놓고 이후에 수치나 사례를 붙이면 면접관이 이해하기 쉽습니다."
        )
        rewrite = (
            f"{question_text}에 대해 먼저 한 문장 결론을 제시합니다. "
            "이후 상황, 내가 한 행동, 결과를 순서대로 말하고 마지막에 배운 점을 짧게 연결합니다."
        )
        return ModelResult(
            feedback_text=feedback,
            rewrite_example=rewrite,
            rubric_scores={
                "structure": structure,
                "specificity": specificity,
                "relevance": 0.68,
                "delivery": 0.60,
            },
            model_name=f"{self.settings.llm_model_name}:fallback",
            latency_ms=int((time.perf_counter() - start) * 1000),
            fallback=True,
            error=reason,
            input_tokens=max(1, math.ceil(len(transcript) / 4)),
            output_tokens=max(1, math.ceil(len(feedback + rewrite) / 4)),
        )


class TTSService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: Any | None = None
        self._speaker_id: int | str | None = None

    def synthesize(self, text: str) -> ModelResult:
        start = time.perf_counter()
        output_dir = self.settings.tts_output_dir
        if not output_dir.is_absolute():
            backend_root = Path(__file__).resolve().parents[2]
            output_dir = backend_root / output_dir.relative_to("backend") if str(output_dir).startswith("backend/") else Path.cwd() / output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{uuid4()}.wav"

        if self.settings.model_mode == "mock":
            _write_placeholder_wav(output_path)
            return ModelResult(
                audio_path=str(output_path),
                audio_url=f"/static/tts/{output_path.name}",
                model_name="mock-melotts",
                latency_ms=int((time.perf_counter() - start) * 1000),
                fallback=True,
            )
        try:
            if self._model is None:
                from melo.api import TTS

                self._model = TTS(language=self.settings.tts_language, device=self.settings.model_device)
                if self.settings.tts_speaker_id:
                    self._speaker_id = self.settings.tts_speaker_id
                else:
                    speaker_ids = getattr(getattr(self._model, "hps", None), "data", None)
                    speaker_map = getattr(speaker_ids, "spk2id", {}) if speaker_ids else {}
                    self._speaker_id = next(iter(speaker_map.values()), 0)
            self._model.tts_to_file(text, self._speaker_id, str(output_path), speed=1.0)
            return ModelResult(
                audio_path=str(output_path),
                audio_url=f"/static/tts/{output_path.name}",
                model_name="MeloTTS",
                latency_ms=int((time.perf_counter() - start) * 1000),
                fallback=False,
            )
        except Exception as exc:  # pragma: no cover - depends on local model installation
            _allow_fallback(self.settings, "tts", exc)
            _write_placeholder_wav(output_path)
            return ModelResult(
                audio_path=str(output_path),
                audio_url=f"/static/tts/{output_path.name}",
                model_name="MeloTTS:fallback",
                latency_ms=int((time.perf_counter() - start) * 1000),
                fallback=True,
                error=str(exc),
            )


def write_audio_temp_file(audio_bytes: bytes, suffix: str = ".webm") -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as audio_file:
        audio_file.write(audio_bytes)
        return audio_file.name


def _write_placeholder_wav(output_path: Path, seconds: float = 0.35, sample_rate: int = 16000) -> None:
    frame_count = int(seconds * sample_rate)
    amplitude = 1200
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for idx in range(frame_count):
            sample = int(amplitude * math.sin(2 * math.pi * 440 * idx / sample_rate))
            frames.extend(sample.to_bytes(2, "little", signed=True))
        wav_file.writeframes(bytes(frames))


def _normalize_scores(scores: dict[str, Any]) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for key in ("structure", "specificity", "relevance", "delivery"):
        try:
            value = float(scores.get(key, 0.0))
        except (TypeError, ValueError):
            value = 0.0
        normalized[key] = min(1.0, max(0.0, value))
    return normalized


def _parse_json_object(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            return json.loads(content[start : end + 1])
        raise
