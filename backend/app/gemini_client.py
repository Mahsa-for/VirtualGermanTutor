import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from .config import Settings


class GeminiClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def stream_reply(
        self,
        user_messages: list[dict[str, Any]],
        system_instruction: str,
    ) -> AsyncGenerator[str, None]:
        if self.settings.mock_mode:
            for chunk in ['Hallo! ', 'Wie geht es dir heute?']:
                await asyncio.sleep(0)
                yield chunk
            return

        if not self.settings.gcp_project_id:
            raise RuntimeError('GCP_PROJECT_ID is required when MOCK_MODE=false.')

        import vertexai
        from vertexai.generative_models import GenerativeModel

        vertexai.init(project=self.settings.gcp_project_id, location=self.settings.gcp_region)
        model = GenerativeModel(self.settings.gemini_model, system_instruction=[system_instruction])

        prompt_lines: list[str] = []
        for msg in user_messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            if isinstance(content, list):
                content = ' '.join(str(part.get('text', '')) for part in content if isinstance(part, dict))
            prompt_lines.append(f'{role}: {content}')

        prompt = '\n'.join(prompt_lines).strip() or 'Start the tutoring conversation with one short German question.'
        responses = model.generate_content(prompt, stream=True)

        for response in responses:
            text = getattr(response, 'text', '')
            if text:
                await asyncio.sleep(0)
                yield text
