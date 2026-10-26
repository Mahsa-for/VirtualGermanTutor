from httpx import ASGITransport, AsyncClient
import pytest

from app.config import get_settings
from app.german_tutor import SCENARIO_CONTEXT, scenario_context
from app.main import app
from app.state import STATE


@pytest.fixture(autouse=True)
def test_settings_env(monkeypatch):
    monkeypatch.setenv('MOCK_MODE', 'true')
    monkeypatch.setenv('SESSION_CREATE_RATE_LIMIT_PER_MINUTE', '100')
    get_settings.cache_clear()
    STATE.reset()
    yield
    get_settings.cache_clear()
    STATE.reset()


def test_scenario_context_covers_all_scenarios():
    assert set(SCENARIO_CONTEXT) == {'free', 'interview', 'shopping', 'doctor'}
    assert 'recruiter' in scenario_context('interview')
    assert scenario_context('unknown') == SCENARIO_CONTEXT['free']


@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://testserver') as client:
        response = await client.get('/api/health')
    assert response.status_code == 200
    body = response.json()
    assert body['app'] == 'virtual-german-tutor'
    assert body['mock_mode'] is True


@pytest.mark.asyncio
async def test_setup_mock_marks_ready():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://testserver') as client:
        response = await client.post(
            '/api/setup',
            json={
                'modal_token_id': 'ak-x',
                'modal_token_secret': 'as-y',
                'tavus_api_key': 'tv-z',
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body['ready'] is True
    assert body['status'] == 'ready'


@pytest.mark.asyncio
async def test_setup_rejects_missing_keys():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://testserver') as client:
        response = await client.post('/api/setup', json={'modal_token_id': 'only-this'})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_session_mock_uses_scenario():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://testserver') as client:
        response = await client.post('/api/session/create', json={'scenario': 'doctor', 'level': 'B1'})
    assert response.status_code == 200
    body = response.json()
    assert body['mock_mode'] is True
    assert body['session_id'] == 'mock-doctor'
    assert 'conversation_url' in body


@pytest.mark.asyncio
async def test_feedback_mock_returns_items():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://testserver') as client:
        response = await client.get('/api/feedback')
    assert response.status_code == 200
    items = response.json()['items']
    assert len(items) >= 1
    assert items[0]['correction'].startswith('Ich bin nach Hause')


@pytest.mark.asyncio
async def test_feedback_summary_is_markdown():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://testserver') as client:
        response = await client.get('/api/feedback/summary')
    assert response.status_code == 200
    assert 'text/markdown' in response.headers['content-type']
    assert '# Your German feedback summary' in response.text
    assert 'Perfekt with sein' in response.text
