#!/usr/bin/env python3
import array
import io
import json
import re
import subprocess
import sys
import traceback
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

MODEL_ID = 'kokoro-tts'
engine = None


class Handler(BaseHTTPRequestHandler):
    def send_data(self, status, content_type, data):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status, data):
        self.send_data(status, 'application/json', json.dumps(data).encode())

    def do_GET(self):
        if self.path == '/health':
            self.send_json(200, {'status': 'ok'})
        elif self.path == '/v1/models':
            self.send_json(200, {'object': 'list', 'data': [{'id': MODEL_ID, 'object': 'model'}]})
        else:
            self.send_json(404, {'error': 'Not found'})

    def do_POST(self):
        if self.path != '/v1/audio/speech':
            self.send_json(404, {'error': 'Not found'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 16384:
                raise ValueError('Request body must be between 1 and 16384 bytes')
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict):
                raise ValueError('Request must be a JSON object')
            if set(request) - {'model', 'input', 'response_format', 'speed'}:
                raise ValueError('Unsupported field; reference audio and voice cloning are not supported')
            if request.get('model', MODEL_ID) != MODEL_ID:
                raise ValueError(f'model must be {MODEL_ID}')
            text = request.get('input')
            if not isinstance(text, str) or not text.strip() or len(text) > 500:
                raise ValueError('input must be non-empty text of at most 500 characters')
            fmt = request.get('response_format', 'wav')
            if fmt not in ('wav', 'mp3'):
                raise ValueError('response_format must be wav or mp3')
            speed = request.get('speed', 1.0)
            if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not 0.5 <= speed <= 2.0:
                raise ValueError('speed must be between 0.5 and 2.0')
        except (ValueError, TypeError, UnicodeDecodeError) as exc:
            self.send_json(400, {'error': str(exc)})
            return
        try:
            audio = engine.generate(text, sid=3 if re.search(r'[\u3400-\u9fff]', text) else 0, speed=speed)
            if not len(audio.samples):
                raise RuntimeError('TTS produced no audio')
            samples = array.array('h', (int(max(-1.0, min(1.0, s)) * 32767) for s in audio.samples))
            if sys.byteorder != 'little':
                samples.byteswap()
            buffer = io.BytesIO()
            with wave.open(buffer, 'wb') as wav:
                wav.setparams((1, 2, audio.sample_rate, 0, 'NONE', 'not compressed'))
                wav.writeframes(samples.tobytes())
            data = buffer.getvalue()
            if fmt == 'mp3':
                result = subprocess.run(['ffmpeg', '-v', 'error', '-i', 'pipe:0', '-f', 'mp3', 'pipe:1'],
                                        input=data, capture_output=True, check=True)
                data = result.stdout
            self.send_data(200, 'audio/mpeg' if fmt == 'mp3' else 'audio/wav', data)
        except Exception:
            traceback.print_exc()
            self.send_json(500, {'error': 'TTS generation failed'})


def main():
    import sherpa_onnx

    global engine
    root = Path('/models/tts-kokoro-onnx')
    config = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                model=str(root / 'model.onnx'), voices=str(root / 'voices.bin'),
                tokens=str(root / 'tokens.txt'), data_dir=str(root / 'espeak-ng-data'),
                lexicon=','.join(str(root / name) for name in ('lexicon-us-en.txt', 'lexicon-zh.txt'))),
            provider='cpu', num_threads=4), max_num_sentences=1)
    if not config.validate():
        raise RuntimeError('Invalid Kokoro model configuration')
    engine = sherpa_onnx.OfflineTts(config)
    HTTPServer(('0.0.0.0', 8003), Handler).serve_forever()


if __name__ == '__main__':
    main()
