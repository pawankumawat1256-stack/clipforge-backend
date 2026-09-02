"""
Cuts clips out of the source video, crops them to 9:16, and burns
word-timed captions in — all via ffmpeg (free, no external API).
"""
import os
import subprocess
import uuid
from typing import List
from .transcriber import Segment
from .highlights import ClipCandidate


def _build_ass_subtitles(words, clip_start: float, path: str):
    """
    Writes an .ass subtitle file with word-level timing, styled for
    a bold centered caption look (TikTok/Shorts style).
    """
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, Bold, Outline, Shadow, Alignment, MarginV
Style: Default,Arial Black,72,&H00FFFFFF,&H00000000,1,4,0,2,120

[Events]
Format: Layer, Start, End, Style, Text
"""
    def fmt_time(t):
        t = max(t, 0)
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = t % 60
        return f"{h:01d}:{m:02d}:{s:05.2f}"

    lines = [header]
    for w in words:
        start = w.start - clip_start
        end = w.end - clip_start
        if end <= 0:
            continue
        text = w.text.replace("{", "").replace("}", "")
        lines.append(f"Dialogue: 0,{fmt_time(start)},{fmt_time(end)},Default,{text}\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def render_clip(
    source_path: str,
    candidate: ClipCandidate,
    all_segments: List[Segment],
    out_dir: str,
) -> str:
    """
    Cuts [candidate.start, candidate.end] from source_path, center-crops
    to 9:16, burns in word-level captions, and writes an mp4 to out_dir.
    Returns the output file path.
    """
    os.makedirs(out_dir, exist_ok=True)
    clip_id = str(uuid.uuid4())
    trimmed_path = os.path.join(out_dir, f"{clip_id}_trim.mp4")
    ass_path = os.path.join(out_dir, f"{clip_id}.ass")
    final_path = os.path.join(out_dir, f"{clip_id}.mp4")

    duration = candidate.end - candidate.start

    # 1) Trim the segment first (fast, keyframe-friendly with -ss before -i).
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", str(max(candidate.start - 0.25, 0)),
            "-i", source_path,
            "-t", str(duration + 0.5),
            "-c:v", "libx264", "-c:a", "aac",
            "-preset", "veryfast",
            trimmed_path,
        ],
        check=True,
        capture_output=True,
    )

    # 2) Collect words that fall inside this clip window for captions.
    words_in_clip = []
    for seg in all_segments:
        for w in seg.words:
            if w.start >= candidate.start - 0.25 and w.end <= candidate.end + 0.5:
                words_in_clip.append(w)
    _build_ass_subtitles(words_in_clip, candidate.start, ass_path)

    # 3) Crop to 9:16 (center crop) and burn in captions.
    #    crop filter: take full height, crop width to height*9/16, centered.
    #    Commas inside filter expressions must be escaped (\,) since ffmpeg
    #    otherwise treats a bare comma as the next filter in the chain.
    #    The ass filter's path also needs colons escaped on top of that,
    #    since ffmpeg's filtergraph parser uses ':' to separate options.
    escaped_ass_path = ass_path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    vf = (
        "crop=w='min(iw\\,ih*9/16)':h=ih:x='(iw-min(iw\\,ih*9/16))/2':y=0,"
        "scale=1080:1920,"
        f"ass='{escaped_ass_path}'"
    )
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", trimmed_path,
            "-vf", vf,
            "-c:v", "libx264", "-c:a", "aac",
            "-preset", "veryfast",
            "-crf", "23",
            final_path,
        ],
        check=True,
        capture_output=True,
    )

    os.remove(trimmed_path)
    os.remove(ass_path)
    return final_path
