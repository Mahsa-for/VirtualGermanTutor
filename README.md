# Virtual German Tutor 🇩🇪

A self-hosted, **bring-your-own-keys** German conversation tutor. You talk to a
[Tavus](https://www.tavus.io/) video avatar that speaks German with you, gently
corrects your mistakes in real time, and lets you download a feedback summary at
the end. The language model runs on a GPU on **your own [Modal](https://modal.com)
account** and answers using a built-in RAG knowledge base of German grammar,
pronunciation, and role-play dialogs.

Everything runs on **your** accounts — you paste your keys in the browser, and the
app provisions the GPU model and the avatar for you. It never uses anyone else's
accounts or keys.

## How it works

```
Browser (localhost:8080)
  └─ paste Modal + Tavus keys ─▶ Local backend (Docker)
                                   ├─ modal deploy ─▶ your Modal GPU app
                                   │                    • OpenAI-compatible /v1/chat/completions (RAG + streaming)
                                   │                    • /feedback (your mistakes)
                                   └─ create Tavus persona + conversation
Browser ◀─ avatar iframe ◀─ Tavus ◀─ calls your Modal endpoint as its "custom LLM"
Browser ─ polls /api/feedback ─▶ live corrections panel + downloadable summary
```

The RAG corpus lives in [`content/`](content/): grammar notes, a pronunciation
guide, and three scripted scenarios (job **interview**, **shopping**, **doctor
visit**), aimed at CEFR levels **A1–B1**. Edit or extend those Markdown files and
redeploy to change what the tutor knows.

## Quick start (Docker)

```bash
docker build -t german-tutor .
docker run -p 8080:8080 german-tutor
```

Open <http://localhost:8080> and follow the setup wizard.

> By default the container starts in **mock mode** (`MOCK_MODE=true`), so the UI
> works without any keys or GPU — handy for a first look. To use the real avatar +
> GPU model, run with `-e MOCK_MODE=false`:
>
> ```bash
> docker run -p 8080:8080 -e MOCK_MODE=false german-tutor
> ```

### What you need

| Key | Where to get it |
|-----|-----------------|
| **Modal Token ID + Secret** | Create a free account at [modal.com](https://modal.com), then run `modal token new`, or copy the token id/secret from your Modal account settings. |
| **Tavus API Key** | From the [Tavus dashboard](https://platform.tavus.io). |
| **Tavus Replica ID** | A replica (avatar face) id from your Tavus dashboard. |

Paste them into the wizard and click **Set up my tutor**. The first setup deploys
the model to your Modal account and downloads the model weights, so it takes a few
minutes. After that, pick a scenario and level and start talking.

## Local development (without Docker)

```bash
# Backend
cd backend
pip install -r requirements.txt
cd ..
uvicorn backend.app.main:app --reload --port 8080

# Frontend (in another terminal)
cd frontend
npm install
npm run dev
```

Run the tests:

```bash
cd backend
pytest
```

## Project layout

```
backend/app/
  main.py          FastAPI routes: setup, session, feedback, SPA serving
  provisioning.py  deploys Modal + creates the Tavus persona from UI keys
  tavus_client.py  create/end Tavus conversations
  german_tutor.py  tutor persona + per-scenario role-play context
  state.py         in-memory runtime state (keys never written to disk)
modal_app/
  german_tutor_modal.py   GPU model + RAG + mistake analysis (deployed to Modal)
content/
  grammar/ pronunciation/ dialogs/   the German RAG corpus
frontend/src/App.tsx   setup wizard, scenario picker, avatar, feedback panel
```

## Configuration

Optional settings live in `.env` (see [`.env.example`](.env.example)). The default
model is `Qwen/Qwen2.5-7B-Instruct` (ungated, strong German). To use a cheaper GPU,
set a smaller model in both `.env` (`MODAL_MODEL_NAME`) and
`modal_app/german_tutor_modal.py` (`MODEL_NAME`).

## Notes & limitations

- Your pasted keys are kept **in the running process only** and are never written
  to disk by the app.
- Mistake feedback is kept in memory in a single warm Modal container; it is
  intended for one learner at a time (self-host).
- This is a **language-learning aid**, not a certified teacher — and the doctor
  scenario is role-play only, not medical advice.
