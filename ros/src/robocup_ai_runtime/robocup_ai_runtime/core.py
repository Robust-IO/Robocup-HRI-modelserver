"""Bounded, model-free primitives shared by both deployment roles."""
from collections import OrderedDict
from enum import IntEnum
import json
import math
import threading
import time

PROTOCOL_VERSION = '1.0'
PACKAGE_VERSION = '0.1.0'


class Code(IntEnum):
    OK = 0
    INVALID = 1
    UNAVAILABLE = 2
    TIMEOUT = 3
    CANCELED = 4
    OVERLOAD = 5
    DUPLICATE = 6
    AUDIO = 7
    VERSION = 8
    BACKEND = 9
    UNSAFE_OUTPUT = 10
    STOP_UNCONFIRMED = 11


class AiError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = int(code)


class Operation:
    def __init__(self, timeout, canceled=lambda: False):
        if not math.isfinite(timeout) or timeout <= 0:
            raise AiError(Code.INVALID, 'timeout must be finite and positive')
        self.deadline = time.monotonic() + timeout
        self.canceled = canceled

    def check(self):
        if self.canceled():
            raise AiError(Code.CANCELED, 'operation canceled')
        if time.monotonic() >= self.deadline:
            raise AiError(Code.TIMEOUT, 'operation deadline exceeded')

    def pause(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.check()
            threading.Event().wait(min(0.01, max(0, end - time.monotonic())))
        self.check()


def validate_protocol(version):
    if version != PROTOCOL_VERSION:
        raise AiError(Code.VERSION, f'protocol mismatch: peer={version!r}, local={PROTOCOL_VERSION}')


def backend_selection(allow, backend, location):
    """Never auto-discover a model or service. The three gates are conjunctive."""
    return backend if allow and backend != 'mock' and location.strip() else 'mock'


def identifier(value, name='request_id'):
    if not value or len(value) > 128 or any(not (c.isalnum() or c in '-_.') for c in value):
        raise AiError(Code.INVALID, f'{name} must be 1..128 letters/digits/-_.')
    return value


class RequestLedger:
    """Active and recent requests. Admission is atomic; retries never replay audio.

    Completed IDs retained for ttl seconds. At capacity reject new requests instead
    of evicting IDs early. Restart loses ledger; callers must not retry across restart.
    """
    def __init__(self, capacity=1024, ttl=300.0):
        self.capacity, self.ttl = capacity, ttl
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def admit(self, request_id):
        identifier(request_id)
        with self.lock:
            now = time.monotonic()
            for key, expiry in list(self.entries.items()):
                if expiry is not None and expiry <= now:
                    del self.entries[key]
            if request_id in self.entries:
                raise AiError(Code.DUPLICATE, 'duplicate request_id (active or retained)')
            if len(self.entries) >= self.capacity:
                raise AiError(Code.OVERLOAD, 'request ledger full')
            self.entries[request_id] = None

    def finish(self, request_id):
        with self.lock:
            self.entries[request_id] = time.monotonic() + self.ttl


def validate_intent(text):
    """Only a small, typed, non-actuating intent vocabulary crosses this boundary."""
    if not text.lstrip().startswith(('{', '[')):
        return ''
    try:
        value = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise AiError(Code.UNSAFE_OUTPUT, 'invalid structured JSON') from exc
    if not isinstance(value, dict) or set(value) != {'intent', 'text'}:
        raise AiError(Code.UNSAFE_OUTPUT, 'expected exactly intent and text')
    if value['intent'] not in ('say', 'ask', 'none') or not isinstance(value['text'], str):
        raise AiError(Code.UNSAFE_OUTPUT, 'intent is not in the non-actuating allowlist')
    if len(value['text']) > 4096:
        raise AiError(Code.UNSAFE_OUTPUT, 'intent text too long')
    return json.dumps(value, ensure_ascii=False)
