from abc import ABC, abstractmethod
from dataclasses import dataclass
import importlib
import struct
from robocup_ai_runtime.core import AiError, Code


@dataclass
class Transcript:
    text: str
    language: str
    confidence: float = -1.0


class Vad(ABC):
    @abstractmethod
    def speech(self, pcm):
        pass


class EnergyVad(Vad):
    def __init__(self, threshold=200):
        self.threshold = threshold

    def speech(self, pcm):
        if not pcm or len(pcm) % 2:
            return False
        values = struct.unpack('<' + 'h' * (len(pcm) // 2), pcm)
        return sum(abs(v) for v in values) / len(values) >= self.threshold


class AsrBackend(ABC):
    @abstractmethod
    def partial(self, pcm, language, hotwords, op):
        pass

    @abstractmethod
    def finalize(self, pcm, language, hotwords, op):
        pass


class MockAsrBackend(AsrBackend):
    def __init__(self, text='你好，请介绍比赛任务'):
        self.text = text

    def partial(self, pcm, language, hotwords, op):
        op.check()
        return self.text[:max(1, len(self.text) // 2)] if pcm else ''

    def finalize(self, pcm, language, hotwords, op):
        op.check()
        if not pcm:
            raise AiError(Code.INVALID, 'no microphone audio received')
        return Transcript(self.text, language or 'zh', -1.0)


# The optional modules implement create_backend(config) -> AsrBackend. Qwen3-ASR
# is maintained in this package, but its inference dependencies remain isolated
# in a separately configured worker environment.
PLUGINS = {
    'qwen3_asr': 'robocup_asr.qwen3_backend',
    'funasr': 'robocup_asr_funasr',
    'faster_whisper': 'robocup_asr_faster_whisper',
    'sherpa_onnx': 'robocup_asr_sherpa_onnx',
}


def create_backend(name, config):
    if name == 'mock':
        return MockAsrBackend(config.get('mock_text', '你好'))
    if not config.get('allow_real_backends') or not config.get('model_path'):
        return MockAsrBackend(config.get('mock_text', '你好'))
    if name == 'http':
        from .http_backend import HttpAsrBackend
        return HttpAsrBackend(config)
    if name not in PLUGINS:
        raise AiError(Code.UNAVAILABLE, 'unknown ASR backend: ' + name)
    try:
        module = importlib.import_module(PLUGINS[name])
    except ImportError as exc:
        raise AiError(Code.UNAVAILABLE, 'ASR backend unavailable: ' + name) from exc
    backend = module.create_backend(config)
    if not isinstance(backend, AsrBackend):
        raise AiError(Code.UNAVAILABLE, 'ASR plugin does not implement AsrBackend')
    return backend
