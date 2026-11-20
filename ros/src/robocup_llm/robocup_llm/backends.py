"""Mock and local Ollama HTTP adapters; standard library only."""
from abc import ABC, abstractmethod
import http.client
import json
import socket
import threading
import time
from urllib.parse import urlsplit
from robocup_ai_runtime.core import AiError, Code, Operation


class LlmBackend(ABC):
    @abstractmethod
    def stream(self, messages, op):
        pass


class MockLlmBackend(LlmBackend):
    def __init__(self, text='收到，我会等待任务状态机确认。', delay=0.01):
        self.text, self.delay = text, delay

    def stream(self, messages, op):
        for char in self.text:
            op.pause(self.delay)
            yield char


class OllamaBackend(LlmBackend):
    def __init__(self, config):
        self.config = dict(config)
        url = urlsplit(config['base_url'])
        if url.scheme != 'http' or url.hostname not in ('localhost', '127.0.0.1', '::1') or url.path not in ('', '/') or url.username:
            raise AiError(Code.INVALID, 'Ollama must use an explicit local HTTP address')
        if not config.get('model'):
            raise AiError(Code.UNAVAILABLE, 'Ollama model is not configured')
        self.host, self.port = url.hostname, url.port or 11434

    def connection(self):
        return http.client.HTTPConnection(self.host, self.port, timeout=self.config['connect_timeout_sec'])

    def health(self):
        connection = self.connection()
        try:
            connection.request('GET', '/api/tags')
            response = connection.getresponse()
            data = response.read(1024 * 1024 + 1)
            if response.status != 200 or len(data) > 1024 * 1024:
                return False, 'Ollama health request failed'
            models = json.loads(data).get('models', [])
            names = {m.get('name') for m in models}
            configured = self.config['model']
            ready = configured in names or configured + ':latest' in names
            return ready, 'Ollama ready' if ready else 'configured Ollama model not present (no automatic pull)'
        except (OSError, ValueError, http.client.HTTPException) as exc:
            return False, 'Ollama unavailable: ' + str(exc)
        finally:
            connection.close()

    def stream(self, messages, op):
        c = self.config
        connection = self.connection()
        stopped = threading.Event()
        interrupted = []
        first_deadline = [None]
        total = Operation(c['total_timeout_sec'], op.canceled)

        def watch():
            while not stopped.wait(0.01):
                try:
                    op.check()
                    total.check()
                    if first_deadline[0] is not None and time.monotonic() >= first_deadline[0]:
                        raise AiError(Code.TIMEOUT, 'Ollama first token timeout')
                except AiError as exc:
                    interrupted.append(exc)
                    if connection.sock:
                        try:
                            connection.sock.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                    return

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        try:
            payload = dict(model=c['model'], messages=messages, stream=True, keep_alive=c['keep_alive'],
                           think=False if c.get('structured_output') else c['think'],
                           options=dict(temperature=c['temperature'], num_ctx=c['num_ctx'],
                                        num_predict=c['max_output_tokens']))
            if c.get('structured_output'):
                payload['format'] = 'json'
            connection.connect()
            op.check()
            first_deadline[0] = time.monotonic() + c['first_token_timeout_sec']
            connection.sock.settimeout(min(c['first_token_timeout_sec'], c['total_timeout_sec']))
            connection.request('POST', '/api/chat', body=json.dumps(payload), headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            if response.status != 200:
                raise AiError(Code.BACKEND, f'Ollama HTTP {response.status}')
            size = 0
            suppress_thinking = c.get('suppress_thinking', False) and not c.get('structured_output')
            thinking_buffer = ''
            thinking_complete = not suppress_thinking
            strip_thinking_whitespace = False
            while True:
                op.check()
                line = response.readline(65537)
                if interrupted:
                    raise interrupted[0]
                if not line:
                    raise AiError(Code.BACKEND, 'Ollama stream closed without done=true')
                if len(line) > 65536:
                    raise AiError(Code.OVERLOAD, 'Ollama JSON line too large')
                event = json.loads(line)
                if 'error' in event:
                    raise AiError(Code.BACKEND, str(event['error']))
                delta = event.get('message', {}).get('content', '')
                if not isinstance(delta, str):
                    raise AiError(Code.BACKEND, 'invalid Ollama content')
                if delta and not thinking_complete:
                    thinking_buffer += delta
                    marker = thinking_buffer.find('</think>')
                    if marker < 0:
                        delta = ''
                    else:
                        delta = thinking_buffer[marker + len('</think>'):].lstrip()
                        thinking_complete = True
                        thinking_buffer = ''
                        strip_thinking_whitespace = True
                if delta and strip_thinking_whitespace:
                    delta = delta.lstrip()
                    if delta:
                        strip_thinking_whitespace = False
                if delta:
                    first_deadline[0] = None
                    size += len(delta)
                    if size > c['max_output_chars']:
                        raise AiError(Code.OVERLOAD, 'Ollama output length exceeded')
                    yield delta
                if event.get('done') is True:
                    if not thinking_complete:
                        raise AiError(Code.BACKEND, 'Ollama thinking did not finish before generation stopped')
                    break
        except (OSError, ValueError, http.client.HTTPException) as exc:
            if interrupted:
                raise interrupted[0] from exc
            if isinstance(exc, (socket.timeout, TimeoutError)):
                raise AiError(Code.TIMEOUT, 'Ollama HTTP timeout') from exc
            raise AiError(Code.BACKEND, 'Ollama HTTP error: ' + str(exc)) from exc
        finally:
            stopped.set()
            connection.close()
            watcher.join(timeout=0.2)
