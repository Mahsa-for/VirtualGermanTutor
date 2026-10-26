import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from .config import Settings, get_settings
from .models import (
    FeedbackResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionEndRequest,
    SetupRequest,
    SetupStatusResponse,
)
from .provisioning import run_setup
from .state import STATE
from .tavus_client import TavusClient

app = FastAPI(title='Virtual German Tutor API', version='1.0.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=False,
    allow_methods=['*'],
    allow_headers=['*'],
)

_rate_bucket: dict[str, deque[float]] = defaultdict(deque)
_setup_lock = threading.Lock()

_MOCK_FEEDBACK = [
    {
        'error': 'Ich habe nach Hause gegangen.',
        'correction': 'Ich bin nach Hause gegangen.',
        'rule': 'Perfekt with sein (movement)',
        'explanation': 'Verbs of movement form the Perfekt with "sein", not "haben".',
        'reference': '[grammar/verb-conjugation-and-tenses] Verbs of movement use sein.',
        'utterance': 'Ich habe nach Hause gegangen.',
    }
]


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get('x-forwarded-for')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return 'unknown'


def enforce_rate_limit(request: Request, settings: Settings) -> None:
    limit = settings.session_create_rate_limit_per_minute
    now = time.time()
    bucket = _rate_bucket[get_client_ip(request)]
    one_minute_ago = now - 60

    while bucket and bucket[0] < one_minute_ago:
        bucket.popleft()

    if len(bucket) >= limit:
        raise HTTPException(status_code=429, detail='Too many session requests. Please wait and try again.')

    bucket.append(now)


@app.get('/api/health')
def health(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return {
        'status': 'ok',
        'app': 'virtual-german-tutor',
        'mock_mode': settings.mock_mode,
        'setup_status': STATE.status,
        'ready': STATE.ready,
    }


@app.post('/api/setup', response_model=SetupStatusResponse)
def setup(payload: SetupRequest, settings: Settings = Depends(get_settings)) -> SetupStatusResponse:
    if settings.mock_mode:
        # No real provisioning in mock mode — pretend everything is ready.
        STATE.set_status('ready', 'Mock mode: tutor ready without real keys.')
        return SetupStatusResponse(**STATE.snapshot())

    with _setup_lock:
        if STATE.status in ('deploying_model', 'creating_avatar'):
            raise HTTPException(status_code=409, detail='Setup is already in progress.')
        STATE.set_status('deploying_model', 'Starting setup…')

    thread = threading.Thread(
        target=run_setup, args=(payload, settings, STATE), daemon=True
    )
    thread.start()
    return SetupStatusResponse(**STATE.snapshot())


@app.get('/api/setup/status', response_model=SetupStatusResponse)
def setup_status() -> SetupStatusResponse:
    return SetupStatusResponse(**STATE.snapshot())


@app.post('/api/session/create', response_model=SessionCreateResponse)
async def create_session(
    payload: SessionCreateRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> SessionCreateResponse:
    enforce_rate_limit(request, settings)

    tavus_client = TavusClient(settings, STATE)
    try:
        session_data = await tavus_client.create_session(payload)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f'Failed to create Tavus session: {exc}') from exc

    return SessionCreateResponse(
        session_id=str(session_data['session_id']),
        conversation_url=str(session_data['conversation_url']),
        max_duration_seconds=settings.tavus_max_duration_seconds,
        mock_mode=settings.mock_mode,
    )


@app.post('/api/session/end', status_code=204)
async def end_session(
    payload: SessionEndRequest,
    settings: Settings = Depends(get_settings),
) -> Response:
    tavus_client = TavusClient(settings, STATE)
    try:
        await tavus_client.end_session(payload.session_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f'Failed to end Tavus session: {exc}') from exc
    return Response(status_code=204)


async def _fetch_feedback(settings: Settings) -> list[dict]:
    if settings.mock_mode:
        return _MOCK_FEEDBACK
    if not STATE.ready or not STATE.modal_url:
        return []
    headers = {'Authorization': f'Bearer {STATE.model_api_key}'} if STATE.model_api_key else {}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f'{STATE.modal_url}/feedback', headers=headers)
        resp.raise_for_status()
        return resp.json().get('items', [])


@app.get('/api/feedback', response_model=FeedbackResponse)
async def feedback(settings: Settings = Depends(get_settings)) -> FeedbackResponse:
    try:
        items = await _fetch_feedback(settings)
    except Exception:
        items = []
    return FeedbackResponse(items=items)


@app.get('/api/feedback/summary')
async def feedback_summary(settings: Settings = Depends(get_settings)) -> PlainTextResponse:
    try:
        items = await _fetch_feedback(settings)
    except Exception:
        items = []

    lines = ['# Your German feedback summary', '']
    if not items:
        lines.append('No mistakes were recorded in this session. Gut gemacht!')
    else:
        lines.append(f'You made {len(items)} correction(s) to review:')
        lines.append('')
        for i, item in enumerate(items, 1):
            lines.append(f'## {i}. {item.get("rule", "Correction")}')
            if item.get('utterance'):
                lines.append(f'- You said: *{item["utterance"]}*')
            if item.get('error'):
                lines.append(f'- Issue: {item["error"]}')
            if item.get('correction'):
                lines.append(f'- Correct form: **{item["correction"]}**')
            if item.get('explanation'):
                lines.append(f'- Why: {item["explanation"]}')
            if item.get('reference'):
                lines.append(f'- Reference: {item["reference"]}')
            lines.append('')

    document = '\n'.join(lines)
    return PlainTextResponse(
        content=document,
        media_type='text/markdown',
        headers={'Content-Disposition': 'attachment; filename="german-feedback.md"'},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={'detail': exc.detail})


FRONTEND_DIST = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'

if FRONTEND_DIST.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount('/assets', StaticFiles(directory=FRONTEND_DIST / 'assets'), name='assets')

    @app.get('/')
    async def root() -> FileResponse:
        return FileResponse(FRONTEND_DIST / 'index.html')

    @app.get('/{full_path:path}')
    async def spa_fallback(full_path: str):
        if full_path.startswith('api/'):
            return JSONResponse(status_code=404, content={'detail': 'Not found'})
        return FileResponse(FRONTEND_DIST / 'index.html')
