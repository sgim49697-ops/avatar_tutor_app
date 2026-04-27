# coach_graph.py - LangGraph 1.0 Functional API workflow for one coaching turn
from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import UUID, uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.func import entrypoint, task

from app.db.repository import Repository
from app.schemas import InferenceTrace, WorkflowInput, WorkflowOutput
from app.services.model_adapters import LLMService, STTService, TTSService
from app.services.rag import RAGService


class CoachWorkflow:
    def __init__(
        self,
        *,
        repository: Repository,
        rag: RAGService,
        stt: STTService,
        llm: LLMService,
        tts: TTSService,
    ) -> None:
        self.repository = repository
        self.rag = rag
        self.stt = stt
        self.llm = llm
        self.tts = tts
        self._workflow = self._build_workflow()

    async def run(self, workflow_input: WorkflowInput) -> WorkflowOutput:
        return await asyncio.to_thread(self._invoke, workflow_input)

    def _invoke(self, workflow_input: WorkflowInput) -> WorkflowOutput:
        config = {"configurable": {"thread_id": str(workflow_input.session_id)}}
        result = self._workflow.invoke(workflow_input.model_dump(mode="json"), config=config)
        return WorkflowOutput.model_validate(result)

    def _build_workflow(self):
        repository = self.repository
        rag = self.rag
        stt = self.stt
        llm = self.llm
        tts = self.tts
        checkpointer = InMemorySaver()

        @task()
        def transcribe_audio(inputs: dict[str, Any]) -> dict[str, Any]:
            if inputs.get("transcript_final"):
                return {
                    "transcript": inputs["transcript_final"],
                    "trace": {
                        "component": "stt",
                        "model_name": "client-provided-transcript",
                        "latency_ms": 0,
                        "status": "skipped",
                        "fallback": False,
                    },
                }
            result = stt.transcribe(inputs.get("audio_blob_ref"))
            return {
                "transcript": result.get("transcript", ""),
                "trace": {
                    "component": "stt",
                    "model_name": result.get("model_name"),
                    "latency_ms": result.get("latency_ms"),
                    "status": "fallback" if result.fallback else "ok",
                    "fallback": result.fallback,
                    "error": result.get("error"),
                },
            }

        @task()
        def retrieve_context(inputs: dict[str, Any]) -> dict[str, Any]:
            query = f"{inputs['question_text']}\n{inputs['transcript']}"
            contexts = asyncio.run(
                rag.retrieve(
                    user_id=UUID(inputs["user_id"]),
                    query=query,
                    document_ids=[UUID(value) for value in inputs.get("uploaded_doc_ids", [])],
                    limit=5,
                )
            )
            return {"contexts": [context.model_dump(mode="json") for context in contexts]}

        @task()
        def compose_feedback(inputs: dict[str, Any]) -> dict[str, Any]:
            result = llm.compose_feedback(
                question_text=inputs["question_text"],
                transcript=inputs["transcript"],
                retrieved_context=inputs["contexts"],
                audio_metrics=inputs.get("audio_metrics", {}),
                vision_metrics=inputs.get("vision_metrics", {}),
            )
            return {
                "feedback_text": result.get("feedback_text", ""),
                "rewrite_example": result.get("rewrite_example"),
                "rubric_scores": result.get("rubric_scores", {}),
                "trace": {
                    "component": "llm",
                    "model_name": result.get("model_name"),
                    "input_tokens": result.get("input_tokens"),
                    "output_tokens": result.get("output_tokens"),
                    "latency_ms": result.get("latency_ms"),
                    "status": "fallback" if result.fallback else "ok",
                    "fallback": result.fallback,
                    "error": result.get("error"),
                },
            }

        @task()
        def synthesize_speech(inputs: dict[str, Any]) -> dict[str, Any]:
            result = tts.synthesize(inputs["feedback_text"])
            return {
                "tts_audio_url": result.get("audio_url"),
                "trace": {
                    "component": "tts",
                    "model_name": result.get("model_name"),
                    "latency_ms": result.get("latency_ms"),
                    "status": "fallback" if result.fallback else "ok",
                    "fallback": result.fallback,
                    "error": result.get("error"),
                },
            }

        @task()
        def persist_trace(inputs: dict[str, Any]) -> dict[str, Any]:
            session_id = UUID(inputs["session_id"])
            turn_id = UUID(inputs["turn_id"])
            user_id = UUID(inputs["user_id"])
            trace_ids: list[str] = []
            for trace_payload in inputs["traces"]:
                trace = InferenceTrace(
                    id=uuid4(),
                    session_id=session_id,
                    turn_id=turn_id,
                    component=trace_payload["component"],
                    model_name=trace_payload.get("model_name"),
                    input_tokens=trace_payload.get("input_tokens"),
                    output_tokens=trace_payload.get("output_tokens"),
                    latency_ms=trace_payload.get("latency_ms"),
                    status=trace_payload.get("status", "ok"),
                    trace_json={
                        key: value
                        for key, value in trace_payload.items()
                        if key not in {"component", "model_name", "latency_ms", "status"}
                        and value is not None
                    },
                )
                asyncio.run(repository.save_trace(trace))
                trace_ids.append(str(trace.id))

            asyncio.run(repository.update_turn_transcript(turn_id, inputs["transcript"]))
            feedback_id = asyncio.run(
                repository.save_feedback(
                    session_id=session_id,
                    turn_id=turn_id,
                    user_id=user_id,
                    feedback_text=inputs["feedback_text"],
                    evidence_json=inputs["contexts"],
                    rewrite_example=inputs.get("rewrite_example"),
                    rubric_scores=inputs.get("rubric_scores", {}),
                    model_name=inputs.get("llm_model_name"),
                )
            )
            trace_ids.append(str(feedback_id))
            return {"trace_ids": trace_ids}

        @entrypoint(checkpointer=checkpointer)
        def coach_turn(inputs: dict[str, Any]) -> dict[str, Any]:
            started_at = time.perf_counter()

            stt_result = transcribe_audio(inputs).result()
            transcript = stt_result["transcript"].strip()

            retrieval_result = retrieve_context({**inputs, "transcript": transcript}).result()
            contexts = retrieval_result["contexts"]

            feedback_result = compose_feedback(
                {
                    **inputs,
                    "transcript": transcript,
                    "contexts": contexts,
                }
            ).result()
            tts_result = synthesize_speech(feedback_result).result()

            traces = [
                stt_result["trace"],
                feedback_result["trace"],
                tts_result["trace"],
            ]
            trace_result = persist_trace(
                {
                    **inputs,
                    "transcript": transcript,
                    "contexts": contexts,
                    "feedback_text": feedback_result["feedback_text"],
                    "rewrite_example": feedback_result.get("rewrite_example"),
                    "rubric_scores": feedback_result.get("rubric_scores", {}),
                    "llm_model_name": feedback_result["trace"].get("model_name"),
                    "traces": traces,
                }
            ).result()

            fallback_components = [
                trace["component"] for trace in traces if trace.get("fallback")
            ]
            return {
                "transcript_final": transcript,
                "retrieved_context": contexts,
                "feedback_text": feedback_result["feedback_text"],
                "rewrite_example": feedback_result.get("rewrite_example"),
                "rubric_scores": feedback_result.get("rubric_scores", {}),
                "tts_audio_url": tts_result.get("tts_audio_url"),
                "latency_ms": int((time.perf_counter() - started_at) * 1000),
                "trace_ids": trace_result["trace_ids"],
                "fallback_components": fallback_components,
            }

        return coach_turn

