"""
Handles pulling a source video onto local disk, either from a YouTube
(or other yt-dlp supported) URL, or from a file the user uploaded directly.
"""
import os
import uuid
import yt_dlp


def download_from_url(url: str, out_dir: str) -> str:
    """
    Downloads a video from a URL using yt-dlp.
    Returns the local file path to the downloaded video.
    """
    os.makedirs(out_dir, exist_ok=True)
    file_id = str(uuid.uuid4())
    out_template = os.path.join(out_dir, f"{file_id}.%(ext)s")

    ydl_opts = {
        "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "outtmpl": out_template,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        # Respect a reasonable duration cap to avoid runaway processing costs.
        "match_filter": _duration_filter(max_minutes=45),
        # YouTube's "web" client increasingly requires a Proof-of-Origin (PO)
        # token that yt-dlp cannot mint without a JS runtime. The Android
        # client historically doesn't require one, so spoofing it as the
        # extractor client is the standard free workaround. This is an
        # arms race with YouTube though - it can stop working if YouTube
        # tightens Android-client requirements too, in which case yt-dlp
        # will need updating again (or a PO-token provider plugin, which
        # needs a JS runtime like Deno installed in the container).
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }

    # YouTube increasingly blocks datacenter/cloud-host IPs (Render, AWS, etc.)
    # with "Sign in to confirm you're not a bot". Passing browser cookies from
    # a real logged-in session works around this. Set COOKIES_FILE to the path
    # of a cookies.txt file (Netscape format) if you hit that error.
    cookies_path = os.environ.get("COOKIES_FILE")
    if cookies_path and os.path.exists(cookies_path):
        ydl_opts["cookiefile"] = cookies_path

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    expected_path = os.path.join(out_dir, f"{file_id}.mp4")
    if not os.path.exists(expected_path):
        # yt-dlp may have picked a different container; find it.
        for f in os.listdir(out_dir):
            if f.startswith(file_id):
                return os.path.join(out_dir, f)
        raise FileNotFoundError("Download completed but output file not found.")
    return expected_path


def _duration_filter(max_minutes: int):
    def filter_fn(info_dict):
        duration = info_dict.get("duration")
        if duration and duration > max_minutes * 60:
            return f"Video is longer than {max_minutes} minutes; skipping to control processing cost."
        return None
    return filter_fn


def save_uploaded_file(upload_bytes: bytes, filename: str, out_dir: str) -> str:
    """
    Saves an uploaded file's raw bytes to disk and returns the local path.
    """
    os.makedirs(out_dir, exist_ok=True)
    ext = os.path.splitext(filename)[1] or ".mp4"
    file_id = str(uuid.uuid4())
    path = os.path.join(out_dir, f"{file_id}{ext}")
    with open(path, "wb") as f:
        f.write(upload_bytes)
    return path
