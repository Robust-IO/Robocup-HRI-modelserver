"""PCM conversion and strict stream validation without NumPy or ROS."""
from dataclasses import dataclass
import io
import math
import struct
import wave
from .core import AiError, Code, identifier


def pcm_s16le(samples):
    values = []
    for sample in samples:
        value = float(sample)
        if not math.isfinite(value):
            raise AiError(Code.AUDIO, 'non-finite PCM sample')
        values.append(round(max(-1.0, min(1.0, value)) * (32768 if value < 0 else 32767)))
    return struct.pack('<' + 'h' * len(values), *values)


def validate_format(rate, channels, encoding):
    if rate not in (8000, 16000, 22050, 24000, 32000, 44100, 48000) or channels not in (1, 2) or encoding != 'pcm_s16le':
        raise AiError(Code.AUDIO, 'unsupported sample rate, channels or encoding')


def mono_pcm_to_wav(pcm, rate):
    if not pcm:
        raise AiError(Code.INVALID, 'no microphone audio received')
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return output.getvalue()


@dataclass
class Chunk:
    stream_id: str
    sequence: int
    sample_rate: int
    channels: int
    encoding: str
    end_of_stream: bool
    data: bytes


def chunks(data, stream_id, rate=16000, channels=1, chunk_bytes=4096):
    validate_format(rate, channels, 'pcm_s16le')
    identifier(stream_id, 'stream_id')
    alignment = 2 * channels
    if not data or len(data) % alignment or chunk_bytes < alignment:
        raise AiError(Code.AUDIO, 'empty or unaligned PCM')
    chunk_bytes -= chunk_bytes % alignment
    for sequence, offset in enumerate(range(0, len(data), chunk_bytes)):
        part = data[offset:offset + chunk_bytes]
        yield Chunk(stream_id, sequence, rate, channels, 'pcm_s16le',
                    offset + len(part) == len(data), part)


class Assembler:
    def __init__(self, stream_id, rate, channels, encoding, max_duration):
        identifier(stream_id, 'stream_id')
        validate_format(rate, channels, encoding)
        if not math.isfinite(max_duration) or not 0 < max_duration <= 300:
            raise AiError(Code.INVALID, 'audio duration must be in (0, 300]')
        self.stream_id, self.rate, self.channels, self.encoding = stream_id, rate, channels, encoding
        self.limit = int(max_duration * rate * channels * 2)
        self.sequence, self.data, self.ended = 0, bytearray(), False

    def accept(self, chunk):
        if self.ended:
            raise AiError(Code.AUDIO, 'chunk after end_of_stream')
        if chunk.stream_id != self.stream_id or chunk.sequence != self.sequence:
            raise AiError(Code.AUDIO, 'wrong stream, lost, duplicate or out-of-order chunk')
        if (chunk.sample_rate, chunk.channels, chunk.encoding) != (self.rate, self.channels, self.encoding):
            raise AiError(Code.AUDIO, 'format changed within stream')
        if len(chunk.data) % (self.channels * 2) or not chunk.data:
            raise AiError(Code.AUDIO, 'empty or unaligned chunk')
        if len(self.data) + len(chunk.data) > self.limit:
            raise AiError(Code.AUDIO, 'maximum audio duration exceeded')
        self.data.extend(chunk.data)
        self.sequence += 1
        self.ended = chunk.end_of_stream

    @property
    def duration(self):
        return len(self.data) / (self.rate * self.channels * 2)
