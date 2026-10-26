"""Virtual German Tutor — Modal GPU service.

This file is deployed to the *user's own* Modal account by the local backend
(`modal deploy modal_app/german_tutor_modal.py`). It exposes an OpenAI-compatible
`/v1/chat/completions` endpoint that Tavus calls directly as its "custom LLM",
plus a `/feedback` endpoint the local app polls to show the learner their mistakes.

Everything (the open LLM, the embedding model, and the FAISS index built from the
German corpus in `content/`) runs here on the user's GPU — nothing touches the
repo owner's accounts.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

import modal

# --- Configuration -----------------------------------------------------------

# Ungated, strong multilingual instruct model (good German). Swap for a smaller
# one (e.g. "Qwen/Qwen2.5-3B-Instruct") if you want a cheaper GPU, or a larger one.
MODEL_NAME = os.environ.get("TUTOR_MODEL_NAME", "Qwen/Qwen2.5-7B-Instruct")
EMBED_MODEL_NAME = "intfloat/multilingual-e5-small"
GPU_TYPE = os.environ.get("TUTOR_GPU", "A10G")
APP_NAME = "german-tutor"
SECRET_NAME = "german-tutor-secret"  # holds MODEL_API_KEY (+ optional HF_TOKEN)

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"

# --- Modal image -------------------------------------------------------------

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch==2.6.0",
        "transformers==4.57.0",
        "accelerate==1.1.1",
        "sentence-transformers==3.3.1",
        "faiss-cpu==1.9.0",
        "fastapi==0.115.2",
        "huggingface-hub==0.26.2",
    )
    # Bake the German corpus into the image so the RAG index can be built offline.
    .add_local_dir(str(CONTENT_DIR), "/content", copy=True)
)

app = modal.App(APP_NAME, image=image)

# Persist the Hugging Face cache so model weights download only once.
hf_cache = modal.Volume.from_name("german-tutor-hf-cache", create_if_missing=True)

# The MODEL_API_KEY secret is created by the backend before deploy. Fall back to an
# empty secret so a manual `modal deploy` (without the backend) still works.
try:
    tutor_secret = modal.Secret.from_name(SECRET_NAME)
except Exception:  # pragma: no cover - manual-deploy convenience (secret not created yet)
    tutor_secret = modal.Secret.from_dict({})


# --- Prompt helpers ----------------------------------------------------------

SCENARIO_CONTEXT = {
    "free": "Free conversation. Chat about everyday topics the learner raises.",
    "interview": (
        "Role-play a friendly job interview. You are the recruiter. Ask typical "
        "interview questions one at a time and keep the conversation going."
    ),
    "shopping": (
        "Role-play shopping in a shop. You are the shop assistant. Help the learner "
        "find items, sizes and prices, and handle paying."
    ),
    "doctor": (
        "Role-play a visit to the doctor's practice. You are the doctor/receptionist. "
        "This is language practice only — never give real medical advice."
    ),
}


def build_system_prompt(level: str, scenario: str, context_snippets: str) -> str:
    level = (level or "A2").upper()
    scenario_text = SCENARIO_CONTEXT.get(scenario, SCENARIO_CONTEXT["free"])
    return (
        "Du bist ein geduldiger, freundlicher Deutschlehrer (a patient, friendly German "
        f"tutor). The learner's level is {level}. "
        f"Scenario: {scenario_text}\n\n"
        "Rules:\n"
        f"- Speak mostly in German, adapted to level {level} (short, clear sentences at A1/A2).\n"
        "- Keep replies short and conversational (1–3 sentences) — this is a spoken video chat.\n"
        "- If the learner makes a clear mistake, gently restate the correct version, then continue.\n"
        "- Ask a follow-up question to keep the learner talking.\n"
        "- If the learner is stuck, offer the English translation briefly in parentheses.\n\n"
        "Reference material (use it to give accurate corrections; do not read it aloud):\n"
        f"{context_snippets}\n"
    )


ANALYSIS_SYSTEM = (
    "You are a meticulous German teacher. Analyse ONLY the learner's latest German "
    "utterance for mistakes (grammar, case, word order, verb form, vocabulary, or an "
    "obvious pronunciation-spelling issue). Return a compact JSON array; each item is "
    '{"error": "...", "correction": "...", "rule": "short rule name", '
    '"explanation": "one short sentence in English"}. '
    "Return [] if there are no meaningful mistakes. Output JSON only, no prose."
)


# --- Service -----------------------------------------------------------------


@app.cls(
    gpu=GPU_TYPE,
    image=image,
    volumes={"/root/.cache/huggingface": hf_cache},
    secrets=[tutor_secret],
    scaledown_window=300,
    max_containers=1,  # keep feedback state consistent in one container
    timeout=600,
)
@modal.concurrent(max_inputs=8)
class GermanTutor:
    @modal.enter()
    def load(self) -> None:
        import faiss  # noqa: F401
        import torch
        from sentence_transformers import SentenceTransformer
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.api_key = os.environ.get("MODEL_API_KEY", "")
        self._feedback: dict[str, list[dict]] = {}
        self._lock = threading.Lock()

        print(f"Loading tokenizer/model: {MODEL_NAME}")
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        self.model = AutoModelForCausalLM.from_pretrained(
            MODEL_NAME, torch_dtype=torch.bfloat16, device_map="cuda"
        )
        self.model.eval()

        print(f"Loading embedder: {EMBED_MODEL_NAME}")
        self.embedder = SentenceTransformer(EMBED_MODEL_NAME, device="cuda")
        self._build_index()
        print("German tutor ready.")

    # -- RAG index -----------------------------------------------------------

    def _build_index(self) -> None:
        import faiss
        import numpy as np

        chunks: list[str] = []
        for path in sorted(Path("/content").rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            section = f"[{path.parent.name}/{path.stem}]"
            # Split on blank lines into reasonably sized chunks.
            for block in text.split("\n\n"):
                block = block.strip()
                if len(block) < 30:
                    continue
                chunks.append(f"{section} {block}")

        self.chunks = chunks
        passages = [f"passage: {c}" for c in chunks]
        emb = self.embedder.encode(
            passages, normalize_embeddings=True, convert_to_numpy=True
        ).astype(np.float32)
        self.index = faiss.IndexFlatIP(emb.shape[1])
        self.index.add(emb)
        print(f"RAG index built: {len(chunks)} chunks.")

    def _retrieve(self, query: str, k: int = 4) -> list[str]:
        import numpy as np

        if not query.strip() or not self.chunks:
            return []
        q = self.embedder.encode(
            [f"query: {query}"], normalize_embeddings=True, convert_to_numpy=True
        ).astype(np.float32)
        _, idx = self.index.search(q, min(k, len(self.chunks)))
        return [self.chunks[i] for i in idx[0] if 0 <= i < len(self.chunks)]

    # -- Generation helpers --------------------------------------------------

    def _generate(self, messages: list[dict], max_new_tokens: int = 256) -> str:
        import torch

        prompt = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.tokenizer(prompt, return_tensors="pt").to("cuda")
        with torch.no_grad():
            out = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=True,
                temperature=0.6,
                top_p=0.9,
                pad_token_id=self.tokenizer.eos_token_id,
            )
        text = self.tokenizer.decode(
            out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True
        )
        return text.strip()

    def _stream(self, messages: list[dict], max_new_tokens: int = 256):
        import torch
        from transformers import TextIteratorStreamer

        prompt = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.tokenizer(prompt, return_tensors="pt").to("cuda")
        streamer = TextIteratorStreamer(
            self.tokenizer, skip_prompt=True, skip_special_tokens=True
        )
        kwargs = dict(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=True,
            temperature=0.6,
            top_p=0.9,
            pad_token_id=self.tokenizer.eos_token_id,
            streamer=streamer,
        )
        thread = threading.Thread(target=self.model.generate, kwargs=kwargs)
        thread.start()
        for token in streamer:
            yield token
        thread.join()

    def _analyse_async(self, conversation_id: str, user_text: str) -> None:
        """Run mistake analysis in the background and store it for polling."""

        def worker() -> None:
            try:
                reference = self._retrieve(user_text, k=1)
                ref_snippet = reference[0] if reference else ""
                raw = self._generate(
                    [
                        {"role": "system", "content": ANALYSIS_SYSTEM},
                        {"role": "user", "content": f"Learner said: {user_text}"},
                    ],
                    max_new_tokens=300,
                )
                items = _safe_json_array(raw)
                if not items:
                    return
                enriched = []
                for it in items:
                    if not isinstance(it, dict) or not it.get("error"):
                        continue
                    it["reference"] = ref_snippet
                    it["utterance"] = user_text
                    it["ts"] = time.time()
                    enriched.append(it)
                if enriched:
                    with self._lock:
                        self._feedback.setdefault(conversation_id, []).extend(enriched)
                        self._feedback.setdefault("latest", []).extend(enriched)
            except Exception as exc:  # pragma: no cover - best-effort analysis
                print(f"analysis failed: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def get_feedback(self, conversation_id: str) -> list[dict]:
        with self._lock:
            return list(self._feedback.get(conversation_id, []))

    # -- ASGI app ------------------------------------------------------------

    @modal.asgi_app()
    def web(self):
        from fastapi import FastAPI, Header, HTTPException, Request
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import JSONResponse, StreamingResponse

        api = FastAPI(title="Virtual German Tutor Model Service")
        api.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        def check_auth(authorization: str | None) -> None:
            if not self.api_key:
                return
            if authorization != f"Bearer {self.api_key}":
                raise HTTPException(status_code=401, detail="Unauthorized")

        @api.get("/health")
        def health() -> dict:
            return {"status": "ok", "model": MODEL_NAME, "chunks": len(self.chunks)}

        @api.get("/feedback/{conversation_id}")
        def feedback(conversation_id: str) -> dict:
            return {"conversation_id": conversation_id, "items": self.get_feedback(conversation_id)}

        @api.get("/feedback")
        def feedback_latest() -> dict:
            return {"conversation_id": "latest", "items": self.get_feedback("latest")}

        @api.post("/v1/chat/completions")
        async def chat_completions(
            request: Request, authorization: str | None = Header(default=None)
        ):
            check_auth(authorization)
            body = await request.json()
            messages = body.get("messages", [])
            conversation_id = _extract_conversation_id(body)
            level = _extract_meta(body, "level", "A2")
            scenario = _extract_meta(body, "scenario", "free")

            latest_user = _latest_user_text(messages)
            if latest_user:
                self._analyse_async(conversation_id, latest_user)

            context = "\n".join(self._retrieve(latest_user, k=4))
            system_prompt = build_system_prompt(level, scenario, context)
            convo = [{"role": "system", "content": system_prompt}]
            convo += [
                {"role": m.get("role", "user"), "content": _as_text(m.get("content"))}
                for m in messages
                if m.get("role") in ("user", "assistant")
            ]

            created = int(time.time())
            completion_id = f"chatcmpl-{uuid.uuid4().hex}"

            def event_stream():
                for chunk in self._stream(convo):
                    payload = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": MODEL_NAME,
                        "choices": [
                            {"index": 0, "delta": {"content": chunk}, "finish_reason": None}
                        ],
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                final = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": MODEL_NAME,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
                yield f"data: {json.dumps(final)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(event_stream(), media_type="text/event-stream")

        @api.exception_handler(HTTPException)
        async def _handler(_: Request, exc: HTTPException):
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

        return api


# --- Module-level utilities --------------------------------------------------


def _as_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return str(content or "")


def _latest_user_text(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return _as_text(m.get("content"))
    return ""


def _extract_conversation_id(body: dict) -> str:
    for key in ("conversation_id", "conversationId"):
        if body.get(key):
            return str(body[key])
    meta = body.get("metadata") or {}
    if isinstance(meta, dict):
        for key in ("conversation_id", "conversationId"):
            if meta.get(key):
                return str(meta[key])
    return "latest"


def _extract_meta(body: dict, key: str, default: str) -> str:
    meta = body.get("metadata") or {}
    if isinstance(meta, dict) and meta.get(key):
        return str(meta[key])
    if body.get(key):
        return str(body[key])
    return default


def _safe_json_array(raw: str) -> list:
    raw = raw.strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        data = json.loads(raw[start : end + 1])
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []
