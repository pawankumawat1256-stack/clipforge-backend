"""
Scores transcript segments to find the most "clip-worthy" moments,
using free heuristics only (no paid LLM calls) so the tool can run
at zero marginal cost per video.

If you later want higher-quality scoring, you can swap `score_window`
to call an LLM API instead - see the ANTHROPIC OPTION note at the bottom.
"""
import re
from dataclasses import dataclass
from typing import List
from .transcriber import Segment

# Words/patterns that tend to correlate with an engaging, quotable moment.
_HOOK_PATTERNS = [
    r"\bnever\b", r"\balways\b", r"\bsecret\b", r"\btruth\b", r"\bmistake\b",
    r"\bwrong\b", r"\bshocking\b", r"\bcrazy\b", r"\bhonestly\b", r"\breally\b",
    r"\bbiggest\b", r"\bworst\b", r"\bbest\b", r"\bhack\b", r"\bproblem\b",
    r"\bwhy\b", r"\bhow to\b", r"\byou need to\b", r"\bstop\b", r"\bimportant\b",
    r"\bfirst\b", r"\blast\b", r"\bone thing\b", r"\bmoney\b", r"\bfailed\b",
]
_HOOK_RE = re.compile("|".join(_HOOK_PATTERNS), re.IGNORECASE)
_QUESTION_RE = re.compile(r"\?")
_NUMBER_RE = re.compile(r"\b\d+\b")


@dataclass
class ClipCandidate:
    start: float
    end: float
    text: str
    score: int
    reason: str


def _score_text(text: str) -> tuple[int, str]:
    score = 40  # baseline
    reasons = []

    hook_hits = len(_HOOK_RE.findall(text))
    if hook_hits:
        score += min(hook_hits * 8, 24)
        reasons.append("strong hook language")

    if _QUESTION_RE.search(text):
        score += 8
        reasons.append("poses a question")

    if _NUMBER_RE.search(text):
        score += 6
        reasons.append("uses a concrete number")

    word_count = len(text.split())
    if 15 <= word_count <= 60:
        score += 10
        reasons.append("good pacing/length")
    elif word_count < 8:
        score -= 10

    score = max(1, min(score, 99))
    reason = ", ".join(reasons) if reasons else "baseline pacing"
    return score, reason


def find_clip_candidates(
    segments: List[Segment],
    min_duration: float = 20.0,
    max_duration: float = 60.0,
    max_clips: int = 6,
) -> List[ClipCandidate]:
    """
    Groups transcript segments into candidate clip windows and scores each.
    Greedy sliding approach: build windows of min_duration..max_duration,
    score them, then pick the best non-overlapping set.
    """
    candidates: List[ClipCandidate] = []
    n = len(segments)

    i = 0
    while i < n:
        window_text = []
        start_time = segments[i].start
        j = i
        end_time = start_time
        while j < n and (segments[j].end - start_time) <= max_duration:
            window_text.append(segments[j].text)
            end_time = segments[j].end
            j += 1
            if (end_time - start_time) >= min_duration and (
                j >= n or (segments[j].end - start_time) > max_duration
            ):
                break

        duration = end_time - start_time
        if duration >= min_duration:
            text = " ".join(window_text)
            score, reason = _score_text(text)
            candidates.append(ClipCandidate(start=start_time, end=end_time, text=text, score=score, reason=reason))

        # Slide forward roughly one segment at a time for overlap coverage.
        i += max(1, (j - i) // 2)

    # Sort by score, then greedily pick non-overlapping top clips.
    candidates.sort(key=lambda c: c.score, reverse=True)
    chosen: List[ClipCandidate] = []
    for c in candidates:
        overlaps = any(not (c.end <= x.start or c.start >= x.end) for x in chosen)
        if not overlaps:
            chosen.append(c)
        if len(chosen) >= max_clips:
            break

    chosen.sort(key=lambda c: c.start)
    return chosen

# ANTHROPIC OPTION:
# For noticeably better highlight selection, replace _score_text's heuristic
# with a call to the Claude API, passing the transcript window and asking
# it to return a 1-99 score + one-line reason as JSON. This costs a small
# amount per video (a few cents), so it's a good "paid tier" upgrade rather
# than the free-tier default.
