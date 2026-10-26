"""Provision the user's OWN Modal + Tavus accounts from UI-supplied credentials.

Everything here runs inside the user's local Docker container using the keys they
paste in the browser. No repo-owner accounts are ever touched.
"""

import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

import httpx

from .config import Settings
from .german_tutor import TUTOR_PERSONA_PROMPT
from .models import SetupRequest
from .state import RuntimeState

REPO_ROOT = Path(__file__).resolve().parents[2]
MODAL_SECRET_NAME = 'german-tutor-secret'
_MODAL_URL_RE = re.compile(r'https://[^\s"\']+\.modal\.run')


def run_setup(req: SetupRequest, settings: Settings, state: RuntimeState) -> None:
    """Blocking end-to-end provisioning. Intended to run in a background thread."""
    try:
        state.reset()
        model_api_key = secrets.token_urlsafe(32)
        env = {
            **os.environ,
            'MODAL_TOKEN_ID': req.modal_token_id,
            'MODAL_TOKEN_SECRET': req.modal_token_secret,
        }

        state.set_status('deploying_model', 'Storing model key as a Modal secret…')
        _create_modal_secret(model_api_key, env, state)

        state.set_status('deploying_model', 'Deploying the GPU model to your Modal account (this takes a few minutes)…')
        modal_url = _deploy_modal(settings.modal_deploy_file, env, state)

        state.set_status('creating_avatar', 'Creating your Tavus avatar persona…')
        persona_id = _create_tavus_persona(req, settings, modal_url, model_api_key)

        state.tavus_api_key = req.tavus_api_key
        state.modal_url = modal_url
        state.model_api_key = model_api_key
        state.persona_id = persona_id
        state.replica_id = req.replica_id
        state.set_status('ready', 'Ready! You can start a conversation.')
    except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
        state.fail(str(exc))


def _run_modal(args: list[str], env: dict, state: RuntimeState) -> str:
    cmd = [sys.executable, '-m', 'modal', *args]
    proc = subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output_lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        output_lines.append(line)
        state.log(line)
    proc.wait()
    output = ''.join(output_lines)
    if proc.returncode != 0:
        raise RuntimeError(f'`modal {" ".join(args)}` failed (exit {proc.returncode}). See logs.')
    return output


def _create_modal_secret(model_api_key: str, env: dict, state: RuntimeState) -> None:
    _run_modal(
        ['secret', 'create', MODAL_SECRET_NAME, f'MODEL_API_KEY={model_api_key}', '--force'],
        env,
        state,
    )


def _deploy_modal(deploy_file: str, env: dict, state: RuntimeState) -> str:
    output = _run_modal(['deploy', deploy_file], env, state)
    match = _MODAL_URL_RE.search(output)
    if not match:
        raise RuntimeError('Could not find the deployed Modal URL in the deploy output.')
    # Strip any trailing path so we own the base URL.
    url = match.group(0)
    return url.split('/v1')[0].rstrip('/')


def _create_tavus_persona(
    req: SetupRequest, settings: Settings, modal_url: str, model_api_key: str
) -> str:
    payload: dict = {
        'persona_name': 'Virtual German Tutor',
        'pipeline_mode': 'full',
        'system_prompt': TUTOR_PERSONA_PROMPT,
        'layers': {
            'llm': {
                'model': settings.modal_model_name,
                'base_url': f'{modal_url}/v1',
                'api_key': model_api_key,
            }
        },
    }
    if req.replica_id:
        payload['default_replica_id'] = req.replica_id

    headers = {'x-api-key': req.tavus_api_key, 'Content-Type': 'application/json'}
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(settings.tavus_persona_create_url, json=payload, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(f'Tavus persona creation failed ({resp.status_code}): {resp.text}')
        data = resp.json()

    persona_id = data.get('persona_id') or data.get('id')
    if not persona_id:
        raise RuntimeError(f'Unexpected Tavus persona response: {data}')
    return str(persona_id)
