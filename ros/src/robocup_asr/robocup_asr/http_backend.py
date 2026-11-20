"""Final-only Qwen3-ASR HTTP adapter."""
import json
import uuid

from robocup_ai_runtime.audio import mono_pcm_to_wav
from robocup_ai_runtime.core import AiError, Code
from robocup_ai_runtime.http_backend import ModelHttp
from .backends import AsrBackend, Transcript


class HttpAsrBackend(AsrBackend):
    def __init__(self, config):
        self.client = ModelHttp(config['base_url'], config['request_timeout_sec'])
        self.model, self.rate = config['http_model'], config['sample_rate']

    def partial(self, pcm, language, hotwords, op):
        op.check()
        return ''

    def finalize(self, pcm, language, hotwords, op):
        return self.transcribe_wav(mono_pcm_to_wav(pcm, self.rate), op)

    def transcribe_wav(self, wav, op):
        if not wav:
            raise AiError(Code.INVALID, 'no microphone audio received')
        boundary = 'robocup-' + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{self.model}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
                'Content-Type: audio/wav\r\n\r\n').encode() + wav + f'\r\n--{boundary}--\r\n'.encode()
        raw = self.client.request('POST', '/v1/audio/transcriptions', body,
                                  {'Content-Type': f'multipart/form-data; boundary={boundary}'}, op, 1024 * 1024)
        try:
            text = json.loads(raw)['text']
            if not isinstance(text, str):
                raise ValueError('text is not a string')
        except (ValueError, KeyError, TypeError) as exc:
            raise AiError(Code.BACKEND, 'invalid ASR response') from exc
        return Transcript(text, '', -1.0)
