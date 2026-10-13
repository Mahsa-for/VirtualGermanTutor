from httpx import ASGITransport, AsyncClient
import pytest

from app.config import get_settings
from app.main import app
from app.tutor import build_tutor_instruction


@pytest.fixture(autouse=True)
def test_settings_env(monkeypatch):
    monkeypatch.setenv('MOCK_MODE', 'true')
    monkeypatch.setenv('SESSION_CREATE_RATE_LIMIT_PER_MINUTE', '100')
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_instruction_includes_roleplay_and_level():
    prompt = build_tutor_instruction('A2', 'ordering coffee')
    assert 'learner level is A2' in prompt
    assert 'cafe waiter' in prompt


@pytest.mark.asyncio
async def test_create_session_mock():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://testserver') as client:
        response = await client.post('/api/session/create', json={'level': 'A1', 'topic': 'shopping'})

    assert response.status_code == 200
    body = response.json()
    assert body['mock_mode'] is True
    assert body['session_id'].startswith('mock-')
    assert 'conversation_url' in body


@pytest.mark.asyncio
async def test_tavus_stream_ends_with_done():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://testserver') as client:
        response = await client.post(
            '/api/tavus/llm/chat/completions',
            json={
                'stream': True,
                'metadata': {'level': 'A1', 'topic': 'introducing yourself'},
                'messages': [{'role': 'user', 'content': 'Hallo'}],
            },
        )

    assert response.status_code == 200
    assert 'data: [DONE]' in response.text
