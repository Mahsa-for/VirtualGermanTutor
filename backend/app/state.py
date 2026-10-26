"""In-memory runtime state for a single self-hosted session.

The user's pasted credentials and the provisioning results live here for the
lifetime of the running process only — nothing is written to disk.
"""

import threading
from dataclasses import dataclass, field


@dataclass
class RuntimeState:
    # Setup progress for the UI wizard.
    status: str = 'idle'  # idle | deploying_model | creating_avatar | ready | error
    step: str = 'Not started.'
    logs: list[str] = field(default_factory=list)
    error: str = ''

    # Provisioned resources (all on the user's own accounts).
    tavus_api_key: str = ''
    modal_url: str = ''        # e.g. https://ws--german-tutor-germantutor-web.modal.run
    model_api_key: str = ''
    persona_id: str = ''
    replica_id: str = ''

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def ready(self) -> bool:
        return self.status == 'ready'

    def set_status(self, status: str, step: str) -> None:
        with self._lock:
            self.status = status
            self.step = step
            self.logs.append(step)

    def log(self, line: str) -> None:
        line = line.rstrip()
        if line:
            with self._lock:
                self.logs.append(line)

    def fail(self, message: str) -> None:
        with self._lock:
            self.status = 'error'
            self.error = message
            self.logs.append(f'ERROR: {message}')

    def snapshot(self) -> dict:
        with self._lock:
            return {
                'status': self.status,
                'step': self.step,
                'logs': self.logs[-40:],
                'error': self.error,
                'ready': self.status == 'ready',
            }

    def reset(self) -> None:
        with self._lock:
            self.status = 'idle'
            self.step = 'Not started.'
            self.logs = []
            self.error = ''


# Single process-wide instance.
STATE = RuntimeState()
