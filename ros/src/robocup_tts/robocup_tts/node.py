import threading
import uuid
from robocup_interfaces.action import Speak, PlayAudio
from robocup_interfaces.msg import AudioChunk
from robocup_ai_runtime.audio import chunks
from robocup_ai_runtime.core import AiError, Code, backend_selection
from robocup_ai_runtime.ros import AiNode, QueuedServer, RemoteAction, spin
from .backends import MockTtsBackend, Qwen3Backend, DirectoryVoiceCache


class TtsNode(AiNode):
    def __init__(self, **kwargs):
        super().__init__('tts_node', 'tts', **kwargs)
        allow = self.param('ai.allow_real_backends', False)
        chosen = self.param('tts.backend', 'mock')
        path = self.param('tts.model_path', '')
        config = {key: self.param('tts.' + key, value) for key, value in {
            'mode': 'CustomVoice', 'language': 'Chinese', 'speaker': '', 'instruct': '',
            'device': 'cpu', 'dtype': 'float32', 'attention_implementation': 'sdpa',
            'reference_audio': '', 'reference_text': '', 'x_vector_only_mode': False,
            'python_executable': '', 'worker_start_timeout_sec': 120.0,
            'request_timeout_sec': 60.0, 'speed': 1.0}.items()}
        base_url = self.param('tts.base_url', '')
        location = base_url if chosen == 'http' else path
        config.update(model_path=path, allow_real_backends=allow, base_url=base_url,
                      http_model=self.param('tts.http_model', 'qwen3-tts'))
        self.backend_name = backend_selection(allow, chosen, location)
        if chosen == 'http' and self.backend_name != 'http':
            raise AiError(Code.UNAVAILABLE, 'HTTP TTS requires enabled real backends and base_url')
        self.model = path if self.backend_name != 'mock' else ''
        self.backend = None
        self.cache_dir = self.param('tts.cache_dir', '')
        self.max_text = self.param('tts.max_text_length', 4096, minimum=1, maximum=16384)
        self.duration = self.param('tts.mock_duration_sec', 0.15, minimum=0.01, maximum=30.0)
        self.chunk_bytes = self.param('tts.chunk_bytes', 4096, minimum=256, maximum=65536)
        self.max_audio = self.param('tts.max_audio_sec', 30.0, minimum=0.1, maximum=300.0)
        self.timeout = self.param('tts.timeout_sec', 60.0, minimum=0.1, maximum=600.0)
        capacity = self.param('tts.queue_depth', 4, minimum=1, maximum=32)
        chunks_topic = self.topic(self.param('tts.chunks_topic', 'audio/tts_chunks'))
        self.audio_pub = self.create_publisher(AudioChunk, chunks_topic, self.qos('tts_audio', 32))
        self.player = RemoteAction(self, PlayAudio, 'audio/play')
        self.server = QueuedServer(self, Speak, 'ai/speak', self.speak, capacity, self.timeout, preempt=True)
        self.loader = threading.Thread(target=self.load, args=(config,), daemon=True)
        self.loader.start()

    def load(self, config):
        try:
            if self.backend_name == 'mock':
                self.backend = MockTtsBackend(self.duration)
            elif self.backend_name == 'qwen3':
                self.backend = Qwen3Backend(config)
                self.backend.load()
            elif self.backend_name == 'http':
                from .http_backend import HttpTtsBackend
                self.backend = HttpTtsBackend(config)
            else:
                raise AiError(Code.UNAVAILABLE, 'TTS backend unavailable: ' + self.backend_name)
            self.cache = DirectoryVoiceCache(self.cache_dir) if self.cache_dir else None
            if self.backend_name == 'http':
                while not self.stopping.is_set():
                    ready = self.backend.client.models(self.backend.model)
                    self.set_status('ready' if ready else 'degraded', ready, 'HTTP TTS ready' if ready else 'HTTP TTS unavailable')
                    self.stopping.wait(2.0)
            else:
                self.set_status('ready', True, 'TTS backend ready: ' + self.backend_name)
        except Exception as exc:
            self.set_status('degraded', False, str(exc))

    def speak(self, handle, op):
        goal = handle.request
        if not goal.text.strip() or len(goal.text) > self.max_text:
            raise AiError(Code.INVALID, 'text empty or too long')
        handle.publish_feedback(Speak.Feedback(stage='synthesizing', progress=0.1, message='synthesizing'))
        data, rate, channels = self.backend.synthesize(goal.text, goal.language, goal.voice, op)
        if len(data) / (rate * channels * 2) > self.max_audio:
            raise AiError(Code.AUDIO, 'synthesized audio too long')
        stream = uuid.uuid4().hex
        receiving = threading.Event()

        def feedback(msg):
            if msg.feedback.stage == 'receiving':
                receiving.set()
            handle.publish_feedback(Speak.Feedback(
                stage=msg.feedback.stage, progress=msg.feedback.progress, message=msg.feedback.message))

        def send_audio(_):
            while not receiving.is_set():
                op.pause(0.01)
            # The reader must match before the first volatile audio sample.
            while self.audio_pub.get_subscription_count() == 0:
                op.pause(0.01)
            for chunk in chunks(data, stream, rate, channels, self.chunk_bytes):
                op.check()
                self.audio_pub.publish(AudioChunk(**vars(chunk)))
                op.pause(0.002)
        play_goal = PlayAudio.Goal(request_id=goal.request_id, stream_id=stream, sample_rate=rate,
                                   channels=channels, encoding='pcm_s16le', priority=goal.priority,
                                   interrupt_current=goal.interrupt_current, max_duration_sec=self.max_audio,
                                   protocol_version=self.protocol)
        result = self.player.call(play_goal, op, feedback, send_audio)
        return Speak.Result(success=True, audio_duration_sec=result.audio_duration_sec)

    def stop(self):
        super().stop()
        self.server.stop()
        self.loader.join(timeout=1.0)
        if hasattr(self.backend, 'close'):
            self.backend.close()


def main():
    spin(TtsNode)
