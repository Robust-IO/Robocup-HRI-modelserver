import http.client
import json
import threading
import unittest
from http.server import HTTPServer
from types import SimpleNamespace

from scripts import tts_server


class TTSServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.speaker_ids = []
        def generate(text, sid, speed):
            cls.speaker_ids.append(sid)
            return SimpleNamespace(samples=[0.2] * 2000, sample_rate=24000)
        tts_server.engine = SimpleNamespace(generate=generate)
        cls.server = HTTPServer(('127.0.0.1', 0), tts_server.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, payload=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        conn.request('GET' if payload is None else 'POST', path,
                     body=None if payload is None else json.dumps(payload).encode(),
                     headers={'Content-Type': 'application/json'})
        response = conn.getresponse()
        result = response.status, response.getheader('Content-Type'), response.read()
        conn.close()
        return result

    def test_models_and_wav(self):
        status, _, body = self.request('/v1/models')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['data'][0]['id'], 'kokoro-tts')
        status, content_type, body = self.request('/v1/audio/speech', {'model': 'kokoro-tts', 'input': '你好'})
        self.assertEqual((status, content_type), (200, 'audio/wav'))
        self.assertTrue(body.startswith(b'RIFF'))
        self.assertEqual(self.speaker_ids[-1], 3)
        self.request('/v1/audio/speech', {'input': 'Hello'})
        self.assertEqual(self.speaker_ids[-1], 0)

    def test_mp3_and_invalid_reference(self):
        status, content_type, body = self.request('/v1/audio/speech', {'input': '你好', 'response_format': 'mp3'})
        self.assertEqual((status, content_type), (200, 'audio/mpeg'))
        self.assertTrue(body.startswith(b'ID3') or body.startswith(b'\xff'))
        status, _, _ = self.request('/v1/audio/speech', {'input': '你好', 'ref_audio': 'old'})
        self.assertEqual(status, 400)


if __name__ == '__main__':
    unittest.main()
