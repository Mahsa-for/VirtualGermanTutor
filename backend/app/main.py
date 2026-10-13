import json
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings, get_settings
from .gemini_client import GeminiClient
from .models import (
    SessionCreateRequest,
    SessionCreateResponse,
    SessionEndRequest,
    TavusChatCompletionRequest,
)
from .tavus_client import TavusClient
from .tutor import build_tutor_instruction

app = FastAPI(title='My German Tutor API', version='0.1.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=False,
    allow_methods=['*'],
    allow_headers=['*'],
)

_rate_bucket: dict[str, deque[float]] = defaultdict(deque)


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


def verify_tavus_auth(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    if settings.mock_mode:
        return
    if not settings.tavus_llm_auth_token:
        raise HTTPException(
            status_code=500,
            detail='TAVUS_LLM_AUTH_TOKEN must be configured when MOCK_MODE=false.',
        )

    expected = 'Bearer ' + settings.tavus_llm_auth_token
    if authorization != expected:
        raise HTTPException(status_code=401, detail='Unauthorized Tavus LLM request.')


@app.get('/api/health')
def health(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return {'status': 'ok', 'mock_mode': settings.mock_mode}


@app.post('/api/session/create', response_model=SessionCreateResponse)
async def create_session(
    payload: SessionCreateRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> SessionCreateResponse:
    enforce_rate_limit(request, settings)

    tavus_client = TavusClient(settings)
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
    tavus_client = TavusClient(settings)
    try:
        await tavus_client.end_session(payload.session_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f'Failed to end Tavus session: {exc}') from exc
    return Response(status_code=204)


@app.post('/api/tavus/llm/chat/completions')
async def tavus_custom_llm(
    payload: TavusChatCompletionRequest,
    settings: Settings = Depends(get_settings),
    _: None = Depends(verify_tavus_auth),
) -> StreamingResponse:
    metadata = payload.metadata or {}
    level = metadata.get('level', 'A1')
    topic = metadata.get('topic', 'introducing yourself')

    if level not in {'A1', 'A2', 'B1'}:
        level = 'A1'
    if topic not in {'ordering coffee', 'shopping', 'introducing yourself'}:
        topic = 'introducing yourself'

    system_instruction = build_tutor_instruction(level, topic)  # type: ignore[arg-type]
    gemini = GeminiClient(settings)

    async def stream() -> AsyncGenerator[str, None]:
        created = int(time.time())
        completion_id = f'chatcmpl-{uuid.uuid4().hex}'

        async for text_chunk in gemini.stream_reply(
            [m.model_dump() for m in payload.messages],
            system_instruction,
        ):
            message = {
                'id': completion_id,
                'object': 'chat.completion.chunk',
                'created': created,
                'model': settings.gemini_model,
                'choices': [
                    {
                        'index': 0,
                        'delta': {'content': text_chunk},
                        'finish_reason': None,
                    }
                ],
            }
            yield f'data: {json.dumps(message)}\n\n'

        final_chunk = {
            'id': completion_id,
            'object': 'chat.completion.chunk',
            'created': created,
            'model': settings.gemini_model,
            'choices': [
                {
                    'index': 0,
                    'delta': {},
                    'finish_reason': 'stop',
                }
            ],
        }
        yield f'data: {json.dumps(final_chunk)}\n\n'
        yield 'data: [DONE]\n\n'

    return StreamingResponse(stream(), media_type='text/event-stream')


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={'detail': exc.detail})


FRONTEND_DIST = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'

if FRONTEND_DIST.exists():
    app.mount('/assets', StaticFiles(directory=FRONTEND_DIST / 'assets'), name='assets')

    @app.get('/')
    async def root() -> FileResponse:
        return FileResponse(FRONTEND_DIST / 'index.html')

    @app.get('/{full_path:path}')
    async def spa_fallback(full_path: str):
        if full_path.startswith('api/'):
            return JSONResponse(status_code=404, content={'detail': 'Not found'})
        return FileResponse(FRONTEND_DIST / 'index.html')
