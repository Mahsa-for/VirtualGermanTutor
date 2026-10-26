from typing import Any

import httpx

from .config import Settings
from .german_tutor import scenario_context
from .models import SessionCreateRequest
from .state import RuntimeState


class TavusClient:
    def __init__(self, settings: Settings, state: RuntimeState) -> None:
        self.settings = settings
        self.state = state

    async def create_session(self, request: SessionCreateRequest) -> dict[str, Any]:
        if self.settings.mock_mode:
            return {
                'session_id': f'mock-{request.scenario}',
                'conversation_url': 'https://example.com/mock-tavus-session',
            }

        if not self.state.ready:
            raise RuntimeError('Tutor is not set up yet. Add your Modal and Tavus keys first.')

        context = (
            f'{scenario_context(request.scenario)} '
            f"The learner's level is {request.level}."
        )

        payload: dict[str, Any] = {
            'persona_id': self.state.persona_id,
            'conversation_name': f'German tutor — {request.scenario}',
            'conversational_context': context,
            'properties': {
                'max_call_duration': self.settings.tavus_max_duration_seconds,
                'participant_left_timeout': 10,
                'participant_absent_timeout': 120,
            },
        }
        if self.state.replica_id:
            payload['replica_id'] = self.state.replica_id

        headers = {'x-api-key': self.state.tavus_api_key, 'Content-Type': 'application/json'}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self.settings.tavus_session_create_url, json=payload, headers=headers
            )
            response.raise_for_status()
            data = response.json()

        session_id = data.get('conversation_id') or data.get('session_id') or data.get('id')
        conversation_url = data.get('conversation_url') or data.get('url')
        if not session_id or not conversation_url:
            raise RuntimeError(f'Unexpected Tavus conversation response: {data}')

        return {'session_id': str(session_id), 'conversation_url': str(conversation_url)}

    async def end_session(self, session_id: str) -> None:
        if self.settings.mock_mode:
            return

        url = self.settings.tavus_session_end_url_template.format(session_id=session_id)
        headers = {'x-api-key': self.state.tavus_api_key}
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, headers=headers)
            response.raise_for_status()
