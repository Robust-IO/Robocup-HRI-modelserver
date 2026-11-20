"""HTTP transport for the LAN model server."""
import http.client
import json
import socket
import threading
from urllib.parse import urlsplit

from .core import AiError, Code, Operation


class ModelHttp:
    def __init__(self, base_url, timeout):
        url = urlsplit(base_url)
        if url.scheme != 'http' or not url.hostname or url.path not in ('', '/') or url.query or url.fragment or url.username:
            raise AiError(Code.INVALID, 'model server URL must be an HTTP origin')
        self.host, self.port, self.timeout = url.hostname, url.port or 80, float(timeout)

    def request(self, method, path, body, headers, op, limit):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        stopped, interrupted = threading.Event(), []
        deadline = Operation(self.timeout, op.canceled)

        def watch():
            while not stopped.wait(0.01):
                try:
                    op.check()
                    deadline.check()
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
            op.check()
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            data = response.read(limit + 1)
            if interrupted:
                raise interrupted[0]
            op.check()
            if response.status != 200:
                raise AiError(Code.BACKEND, f'model server HTTP {response.status}: {data[:512].decode("utf-8", "replace")}')
            if len(data) > limit:
                raise AiError(Code.OVERLOAD, 'model server response too large')
            return data
        except (OSError, http.client.HTTPException) as exc:
            if interrupted:
                raise interrupted[0] from exc
            code = Code.TIMEOUT if isinstance(exc, (TimeoutError, socket.timeout)) else Code.BACKEND
            raise AiError(code, 'model server HTTP error: ' + str(exc)) from exc
        finally:
            stopped.set()
            connection.close()
            watcher.join(timeout=0.2)

    def models(self, model):
        try:
            probe = ModelHttp(f'http://[{self.host}]:{self.port}' if ':' in self.host else f'http://{self.host}:{self.port}', min(self.timeout, 2.0))
            raw = probe.request('GET', '/v1/models', None, {}, Operation(probe.timeout), 1024 * 1024)
            return any(item.get('id') == model for item in json.loads(raw)['data'])
        except (AiError, ValueError, KeyError, TypeError):
            return False
