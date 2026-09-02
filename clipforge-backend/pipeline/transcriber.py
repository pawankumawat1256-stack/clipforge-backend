"""
Transcribes a video's audio track into word-level timestamped text
using faster-whisper (open-source, runs locally, no per-call API cost).
"""
from dataclasses import dataclass
from typing import List
from faster_whisper import WhisperModel

# "small" is a good free/local balance of speed vs accuracy on CPU.
# Use "base" for faster but less accurate, "medium" for slower but better.
_MODEL_SIZE = "small"
_model = None


def _get_model():
    global _model
    if _model is None:
        # compute_type="int8" keeps this runnable on CPU-only free-tier hosts.
        _model = WhisperModel(_MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Segment:
    text: str
    start: float
    end: float
    words: List[Word]


def transcribe(video_path: str) -> List[Segment]:
    """
    Returns a list of transcript segments with word-level timestamps.
    """
    model = _get_model()
    segments, _info = model.transcribe(video_path, word_timestamps=True, vad_filter=True)

    result = []
    for seg in segments:
        words = [Word(text=w.word.strip(), start=w.start, end=w.end) for w in (seg.words or [])]
        result.append(Segment(text=seg.text.strip(), start=seg.start, end=seg.end, words=words))
    return result
