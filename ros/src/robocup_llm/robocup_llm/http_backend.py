"""OpenAI-compatible model-server chat adapter."""
import json

from robocup_ai_runtime.core import AiError, Code
from robocup_ai_runtime.http_backend import ModelHttp
from .backends import LlmBackend


class HttpLlmBackend(LlmBackend):
    def __init__(self, config):
        self.config = config
        self.client = ModelHttp(config['base_url'], config['total_timeout_sec'])

    def health(self):
        ready = self.client.models(self.config['model'])
        return ready, 'model server ready' if ready else 'model server unavailable or model not found'

    def stream(self, messages, op):
        c = self.config
        payload = {'model': c['model'], 'messages': messages, 'stream': False,
                   'temperature': c['temperature'], 'max_tokens': c['max_output_tokens'],
                   'chat_template_kwargs': {'enable_thinking': False}}
        raw = self.client.request('POST', '/v1/chat/completions', json.dumps(payload).encode(),
                                  {'Content-Type': 'application/json'}, op, 1024 * 1024)
        try:
            result = json.loads(raw)
            choice = result['choices'][0]
            text = choice['message']['content']
            if not isinstance(text, str) or not text or choice.get('finish_reason') == 'length':
                raise ValueError('empty or truncated completion')
            if len(text) > c['max_output_chars']:
                raise AiError(Code.OVERLOAD, 'model output length exceeded')
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AiError(Code.BACKEND, 'invalid model server completion') from exc
        yield text
