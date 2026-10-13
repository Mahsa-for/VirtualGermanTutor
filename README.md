# Virtual German Tutor (React + FastAPI + Tavus + Gemini)

This repository contains an MVP web app called **My German Tutor**.

- Frontend: **React + TypeScript**
- Backend: **FastAPI (Python)**
- LLM: **Gemini via Vertex AI**
- Avatar conversation: **Tavus Conversational Video**
- Deployment target: **Google Cloud Run (single service serving frontend + backend)**

> ⚠️ This environment could not access external docs hosts during implementation, so the Tavus session-creation/end request details are intentionally driven by environment variables (`TAVUS_SESSION_CREATE_URL`, `TAVUS_SESSION_END_URL_TEMPLATE`, `TAVUS_SESSION_PAYLOAD_TEMPLATE`) to avoid hard-coding potentially incorrect API shapes. The app runs end-to-end in **MOCK_MODE** by default.

---

## Folder structure

```text
backend/
  app/
    config.py
    gemini_client.py
    main.py
    models.py
    tavus_client.py
    tutor.py
  tests/
    test_app.py
  requirements.txt
frontend/
  src/
    App.tsx
    main.tsx
    styles.css
  index.html
  package.json
  tsconfig*.json
  vite.config.ts
Dockerfile
.env.example
```

---

## Features in this MVP

- Clean responsive page titled **My German Tutor**
- Level selector: **A1 / A2 / B1**
- Topic selector: **ordering coffee / shopping / introducing yourself**
- **Start conversation** and **End conversation**
- Embedded conversation surface (`iframe` URL returned by backend)
- Loading states and error messages
- Microphone/camera permission request on start
- Tutor behavior instructions include level/topic and role-play logic for ordering coffee
- Tavus custom LLM adapter endpoint using OpenAI-compatible SSE chunks
- Session duration cap (`TAVUS_MAX_DURATION_SECONDS`) and simple per-IP rate limit

---

## Local setup

### 1) Prerequisites

- Python 3.11+
- Node.js 20+
- npm

### 2) Configure environment

```bash
cp .env.example .env
```

For local mock run, keep `MOCK_MODE=true`.

### 3) Backend install + run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8080
```

### 4) Frontend install + run (separate terminal)

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

---

## Tavus configuration instructions

1. Create/configure your Tavus persona + replica in Tavus dashboard.
2. From official Tavus docs for your account/plan, collect:
   - Session (or conversation) **create endpoint URL**
   - Session end/terminate endpoint format (with session ID)
   - Exact required create payload schema
   - Embeddable conversation URL field returned in response
3. Put those values into:
   - `TAVUS_SESSION_CREATE_URL`
   - `TAVUS_SESSION_END_URL_TEMPLATE`
   - `TAVUS_SESSION_PAYLOAD_TEMPLATE`
4. Set `TAVUS_API_KEY` and shared webhook token `TAVUS_LLM_AUTH_TOKEN`.
5. Configure Tavus custom LLM to call:
   - `https://<your-service>/api/tavus/llm/chat/completions`
   - Include an Authorization bearer token that matches `TAVUS_LLM_AUTH_TOKEN`.

---

## Google Cloud / Vertex AI setup

### Required APIs

```bash
gcloud services enable run.googleapis.com aiplatform.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com
```

### Service account and IAM

```bash
PROJECT_ID="YOUR_PROJECT_ID"
REGION="us-central1"
SA_NAME="virtual-german-tutor-sa"

# Create runtime service account
gcloud iam service-accounts create "$SA_NAME" --project "$PROJECT_ID"

# Allow Vertex AI model invocation
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role "roles/aiplatform.user"

# Allow Cloud Run to run as this service account
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "user:YOUR_EMAIL@example.com" \
  --role "roles/iam.serviceAccountUser"
```

### Build and deploy to Cloud Run

```bash
PROJECT_ID="YOUR_PROJECT_ID"
REGION="us-central1"
SERVICE="virtual-german-tutor"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/virtual-german-tutor/${SERVICE}:latest"

# one-time repo
 gcloud artifacts repositories create virtual-german-tutor \
  --repository-format=docker --location="$REGION" --project="$PROJECT_ID" || true

gcloud auth configure-docker "${REGION}-docker.pkg.dev"

docker build -t "$IMAGE" .
docker push "$IMAGE"

gcloud run deploy "$SERVICE" \
  --image "$IMAGE" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --service-account "virtual-german-tutor-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --set-env-vars "MOCK_MODE=false,PUBLIC_BASE_URL=https://<YOUR_RUN_URL>,GCP_PROJECT_ID=${PROJECT_ID},GCP_REGION=${REGION},GEMINI_MODEL=gemini-2.0-flash-001,TAVUS_API_KEY=<SECRET>,TAVUS_SESSION_CREATE_URL=<SECRET>,TAVUS_SESSION_END_URL_TEMPLATE=<SECRET>,TAVUS_SESSION_PAYLOAD_TEMPLATE=<SECRET_JSON>,TAVUS_LLM_AUTH_TOKEN=<SECRET>,TAVUS_MAX_DURATION_SECONDS=900"
```

> For production, store secrets in Secret Manager and reference them from Cloud Run instead of inline env values.

---

## Request flow (simple)

1. User selects level/topic and clicks **Start conversation**.
2. Frontend requests mic/camera permissions.
3. Frontend calls `POST /api/session/create`.
4. Backend rate-limits + creates Tavus session (or mock session).
5. Frontend embeds returned conversation URL in iframe.
6. Tavus calls backend custom LLM endpoint `POST /api/tavus/llm/chat/completions`.
7. Backend builds tutor instruction from selected level/topic metadata, streams Gemini output as OpenAI-compatible chunks.
8. User can click **End conversation**; frontend calls `POST /api/session/end`.

---

## Validation checks included

- Session creation endpoint (`/api/session/create`) success and error handling.
- Streaming endpoint format includes SSE chunks and `[DONE]`.
- Session ending endpoint exists (`/api/session/end`) with error handling.
- Frontend shows loading/error states and preserves responsive behavior.

Run backend tests:

```bash
PYTHONPATH=backend pytest backend/tests -q
```

Build frontend:

```bash
cd frontend && npm install && npm run build
```

---

## Costs (brief)

Potential billable services:

- **Tavus**: conversation/session usage, avatar/video minutes
- **Vertex AI Gemini**: token usage
- **Cloud Run**: CPU/memory/network based on requests and runtime
- **Artifact Registry**: image storage and transfer
- **Cloud Build** (if used): build minutes

Keep `MOCK_MODE=true` for local UI/dev testing without paid calls.
