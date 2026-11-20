"""TTS adapters; real inference stays behind an explicitly enabled worker."""
from abc import ABC, abstractmethod
from collections import deque
from pathlib import Path
import json
import math
import os
import queue
import subprocess
import threading
import time
from robocup_ai_runtime.audio import pcm_s16le
from robocup_ai_runtime.core import AiError, Code


class TtsBackend(ABC):
    @abstractmethod
    def synthesize(self, text, language, voice, op):
        """Return (PCM S16LE bytes, sample_rate, channels)."""


class MockTtsBackend(TtsBackend):
    def __init__(self, duration=0.15):
        self.duration = duration

    def synthesize(self, text, language, voice, op):
        op.pause(0.02)
        rate = 16000
        return pcm_s16le(0.05 * math.sin(2 * math.pi * 440 * i / rate)
                         for i in range(int(rate * self.duration))), rate, 1


class VoiceCache(ABC):
    @abstractmethod
    def get(self, key):
        pass

    @abstractmethod
    def put(self, key, audio):
        pass


class DirectoryVoiceCache(VoiceCache):
    """Reserved local cache interface; no model or audio created automatically."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def get(self, key):
        return None

    def put(self, key, audio):
        # Intentionally disabled until a bounded cache policy is selected.
        return False


class Qwen3Backend(TtsBackend):
    def __init__(self, config):
        self.config = dict(config)
        self.process = None
        self.worker_path = Path(__file__).with_name('qwen_worker.py')
        self.lock = threading.Lock()
        self.stderr_tail = deque(maxlen=20)

    def load(self):
        if not self.config.get('allow_real_backends'):
            raise AiError(Code.UNAVAILABLE, 'real backends disabled')
        path = Path(self.config['model_path']).expanduser().resolve()
        if not path.is_dir():
            raise AiError(Code.UNAVAILABLE, 'explicit local Qwen model directory does not exist')
        executable = Path(self.config.get('python_executable') or os.sys.executable).expanduser().resolve()
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise AiError(Code.UNAVAILABLE, 'explicit Qwen Python executable is unavailable')
        self.config['model_path'] = str(path)
        self.config['python_executable'] = str(executable)
        self._start_worker()

    def _diagnostic(self):
        return self.stderr_tail[-1].strip() if self.stderr_tail else 'no worker diagnostic'

    def _drain_stderr(self, process):
        for raw in iter(process.stderr.readline, b''):
            self.stderr_tail.append(raw.decode('utf-8', errors='replace'))

    def _stop_worker(self):
        process, self.process = self.process, None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream:
                stream.close()

    def _send(self, value):
        try:
            self.process.stdin.write(json.dumps(value, ensure_ascii=False).encode('utf-8') + b'\n')
            self.process.stdin.flush()
        except (AttributeError, BrokenPipeError, OSError) as exc:
            self._stop_worker()
            raise AiError(Code.BACKEND, 'Qwen worker pipe failed') from exc

    def _receive(self, op=None, timeout=60.0):
        process = self.process
        result = queue.Queue(maxsize=1)

        def read_frame():
            try:
                line = process.stdout.readline()
                if not line:
                    raise EOFError('Qwen worker closed its response pipe')
                header = json.loads(line)
                length = int(header.pop('payload_bytes', 0))
                if length < 0 or length > 64 * 1024 * 1024:
                    raise ValueError('invalid Qwen worker payload size')
                payload = bytearray()
                while len(payload) < length:
                    part = process.stdout.read(length - len(payload))
                    if not part:
                        raise EOFError('truncated Qwen worker payload')
                    payload.extend(part)
                result.put((header, bytes(payload)))
            except Exception as exc:
                result.put(exc)

        reader = threading.Thread(target=read_frame, daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout
        try:
            while True:
                try:
                    value = result.get(timeout=0.02)
                    if isinstance(value, Exception):
                        raise value
                    return value
                except queue.Empty:
                    if op is not None:
                        op.check()
                    if time.monotonic() >= deadline:
                        raise AiError(Code.TIMEOUT, 'Qwen worker response timeout')
                    if process.poll() is not None:
                        raise AiError(Code.BACKEND, 'Qwen worker exited: ' + self._diagnostic())
        except AiError:
            self._stop_worker()
            reader.join(timeout=1.0)
            raise
        except (EOFError, OSError, ValueError, json.JSONDecodeError) as exc:
            self._stop_worker()
            reader.join(timeout=1.0)
            raise AiError(Code.BACKEND, 'Qwen worker protocol error: ' + str(exc)) from exc

    def _start_worker(self, op=None):
        if self.process is not None and self.process.poll() is None:
            return
        self._stop_worker()
        try:
            self.process = subprocess.Popen(
                [self.config['python_executable'], str(self.worker_path)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=str(self.worker_path.parent), bufsize=0)
        except OSError as exc:
            raise AiError(Code.UNAVAILABLE, 'failed to start Qwen worker: ' + str(exc)) from exc
        threading.Thread(target=self._drain_stderr, args=(self.process,), daemon=True).start()
        self._send(self.config)
        header, _ = self._receive(op, float(self.config.get('worker_start_timeout_sec', 120.0)))
        if header.get('status') != 'ready':
            self._stop_worker()
            message = 'Qwen worker failed to become ready: ' + str(header.get('error', self._diagnostic()))
            raise AiError(Code.UNAVAILABLE, message)

    def synthesize(self, text, language, voice, op):
        op.check()
        with self.lock:
            self._start_worker(op)
            self._send({'command': 'synthesize', 'text': text, 'language': language, 'voice': voice})
            header, payload = self._receive(op, float(self.config.get('request_timeout_sec', 60.0)))
            if not header.get('ok'):
                raise AiError(Code.BACKEND, 'Qwen inference failed: ' + str(header.get('error', 'unknown error')))
            try:
                rate, channels = int(header['sample_rate']), int(header['channels'])
            except (KeyError, TypeError, ValueError) as exc:
                raise AiError(Code.BACKEND, 'invalid Qwen audio metadata') from exc
            if rate < 8000 or rate > 192000 or channels < 1 or channels > 8 or len(payload) % (channels * 2):
                raise AiError(Code.BACKEND, 'invalid Qwen audio payload')
            op.check()
            return payload, rate, channels

    def close(self):
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                try:
                    self._send({'command': 'shutdown'})
                    self.process.wait(timeout=2.0)
                except (AiError, subprocess.TimeoutExpired):
                    pass
            self._stop_worker()
