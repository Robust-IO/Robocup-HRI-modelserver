"""Qwen3 Base and Kokoro HTTP synthesis returning PCM for the ROS audio player."""
import base64
import io
import json
import mimetypes
from pathlib import Path
import wave

from robocup_ai_runtime.audio import validate_format
from robocup_ai_runtime.core import AiError, Code
from robocup_ai_runtime.http_backend import ModelHttp


class HttpTtsBackend:
    def __init__(self, config):
        self.client = ModelHttp(config['base_url'], config['request_timeout_sec'])
        self.model = config['http_model']
        if self.model == 'kokoro-tts':
            return
        reference = Path(config['reference_audio']).expanduser()
        if not reference.is_file() or reference.suffix.lower() not in ('.wav', '.mp3'):
            raise AiError(Code.INVALID, 'TTS HTTP reference_audio must be a WAV or MP3 file')
        mime = mimetypes.guess_type(str(reference))[0]
        self.reference = 'data:' + mime + ';base64,' + base64.b64encode(reference.read_bytes()).decode('ascii')

    def synthesize(self, text, language, voice, op):
        names = {'zh': 'Chinese', 'en': 'English', '': 'Chinese'}
        payload = {'model': self.model, 'input': text, 'response_format': 'wav'}
        if self.model == 'kokoro-tts':
            if voice:
                payload['voice'] = voice
        else:
            payload.update(task_type='Base', language=names.get(language.lower(), language),
                           ref_audio=self.reference, x_vector_only_mode=True)
        raw = self.client.request('POST', '/v1/audio/speech', json.dumps(payload).encode(),
                                  {'Content-Type': 'application/json'}, op, 64 * 1024 * 1024)
        try:
            with wave.open(io.BytesIO(raw), 'rb') as wav:
                rate, channels = wav.getframerate(), wav.getnchannels()
                if wav.getsampwidth() != 2 or wav.getcomptype() != 'NONE':
                    raise ValueError('expected PCM 16-bit WAV')
                data = wav.readframes(wav.getnframes())
            validate_format(rate, channels, 'pcm_s16le')
            if not data:
                raise ValueError('empty WAV')
            return data, rate, channels
        except (wave.Error, EOFError, ValueError) as exc:
            raise AiError(Code.AUDIO, 'invalid TTS WAV: ' + str(exc)) from exc
