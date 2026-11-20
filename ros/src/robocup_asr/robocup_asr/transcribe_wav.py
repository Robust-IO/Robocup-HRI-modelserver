"""Transcribe complete WAV recordings using the base station's HTTP model."""
import threading

from robocup_ai_runtime.core import AiError, Code
from robocup_ai_runtime.ros import AiNode, QueuedServer, spin
from robocup_interfaces.action import TranscribeWav

from .http_backend import HttpAsrBackend


class TranscribeWavNode(AiNode):
    def __init__(self, **kwargs):
        super().__init__('transcribe_wav_node', 'asr_wav', **kwargs)
        if not self.param('ai.allow_real_backends', False):
            raise AiError(Code.UNAVAILABLE, 'real backends are disabled')
        base_url = self.param('asr.base_url', '')
        self.model = self.param('asr.http_model', 'qwen3-asr')
        timeout = self.param('asr.request_timeout_sec', 60.0)
        self.backend_name = 'http'
        self.backend = HttpAsrBackend(dict(
            base_url=base_url, request_timeout_sec=timeout,
            http_model=self.model, sample_rate=16000))
        self.server = QueuedServer(
            self, TranscribeWav, 'ai/transcribe_wav', self.transcribe,
            capacity=1, timeout=timeout)
        self.health = threading.Thread(target=self.check_backend, daemon=True)
        self.health.start()

    def check_backend(self):
        while not self.stopping.is_set():
            ready = self.backend.client.models(self.model)
            self.set_status('ready' if ready else 'degraded', ready,
                            'HTTP ASR ready' if ready else 'HTTP ASR unavailable')
            if ready:
                return
            self.stopping.wait(2.0)

    def transcribe(self, handle, op):
        result = self.backend.transcribe_wav(bytes(handle.request.wav), op)
        return TranscribeWav.Result(success=True, text=result.text)

    def stop(self):
        super().stop()
        self.server.stop()
        self.health.join(timeout=3.0)


def main():
    spin(TranscribeWavNode)
