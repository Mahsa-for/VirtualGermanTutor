import json
from collections.abc import Mapping
from typing import Any

import httpx

from .config import Settings
from .models import SessionCreateRequest
from .tutor import build_tutor_instruction


class TavusClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def create_session(self, request: SessionCreateRequest) -> dict[str, Any]:
        if self.settings.mock_mode:
            return {
                'session_id': f'mock-{request.level.lower()}-{request.topic.replace(" ", "-")}',
                'conversation_url': 'https://example.com/mock-tavus-session',
            }

        if not self.settings.tavus_api_key:
            raise RuntimeError('TAVUS_API_KEY is required when MOCK_MODE=false.')
        if not self.settings.tavus_session_create_url:
            raise RuntimeError('Set TAVUS_SESSION_CREATE_URL from Tavus documentation.')
        if not self.settings.tavus_session_payload_template:
            raise RuntimeError(
                'Set TAVUS_SESSION_PAYLOAD_TEMPLATE to the exact JSON body required by your Tavus account. '
                'Use placeholders: {level}, {topic}, {instructions}, {llm_endpoint}, {max_duration_seconds}.'
            )

        instruction = build_tutor_instruction(request.level, request.topic)
        llm_endpoint = f'{self.settings.public_base_url.rstrip("/")}/api/tavus/llm/chat/completions'

        payload = self._build_payload(
            self.settings.tavus_session_payload_template,
            {
                'level': request.level,
                'topic': request.topic,
                'instructions': instruction,
                'llm_endpoint': llm_endpoint,
                'max_duration_seconds': str(self.settings.tavus_max_duration_seconds),
            },
        )

        headers = {
            'Authorization': 'Bearer ' + self.settings.tavus_api_key,
            'Content-Type': 'application/json',
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(self.settings.tavus_session_create_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        session_id = data.get('conversation_id') or data.get('session_id') or data.get('id')
        conversation_url = data.get('conversation_url') or data.get('url')

        if not session_id or not conversation_url:
            raise RuntimeError(
                'Unexpected Tavus response. Verify your payload template and response mapping fields '
                '(conversation_id/session_id/id and conversation_url/url).'
            )

        return {
            'session_id': session_id,
            'conversation_url': conversation_url,
        }

    async def end_session(self, session_id: str) -> None:
        if self.settings.mock_mode:
            return

        if not self.settings.tavus_api_key:
            raise RuntimeError('TAVUS_API_KEY is required when MOCK_MODE=false.')
        if not self.settings.tavus_session_end_url_template:
            raise RuntimeError('Set TAVUS_SESSION_END_URL_TEMPLATE from Tavus documentation.')

        url = self.settings.tavus_session_end_url_template.format(session_id=session_id)
        headers = {'Authorization': 'Bearer ' + self.settings.tavus_api_key}

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, headers=headers)
            response.raise_for_status()

    @staticmethod
    def _build_payload(template: str, values: Mapping[str, str]) -> dict[str, Any]:
        try:
            rendered = template.format_map(values)
            payload = json.loads(rendered)
            if not isinstance(payload, dict):
                raise ValueError('payload must be an object')
            return payload
        except Exception as exc:  # pragma: no cover - explicit configuration error path
            raise RuntimeError(f'Invalid TAVUS_SESSION_PAYLOAD_TEMPLATE: {exc}') from exc
