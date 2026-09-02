"""
ClipForge AI - backend
Turns a long video (YouTube URL or upload) into scored, captioned,
9:16 short clips. Free/open-source pipeline: yt-dlp + faster-whisper + ffmpeg.

Run locally:
    uvicorn main:app --reload --port 8000

Deploy: see README.md (Render/Railway free tier instructions).
"""
import os
import shutil
import subprocess
import uuid
import traceback
from datetime import datetime, timedelta
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pipeline.downloader import download_from_url, save_uploaded_file
from pipeline.transcriber import transcribe
from pipeline.highlights import find_clip_candidates
from pipeline.clipper import render_clip

WORK_DIR = os.path.join(os.path.dirname(__file__), "work")
SOURCE_DIR = os.path.join(WORK_DIR, "sources")
CLIPS_DIR = os.path.join(WORK_DIR, "clips")
os.makedirs(SOURCE_DIR, exist_ok=True)
os.makedirs(CLIPS_DIR, exist_ok=True)

# --- Fair-use free-tier limiting (ad-funded model, no payment required) ---
FREE_VIDEOS_PER_WEEK = 3
_usage: dict[str, list[datetime]] = {}  # user_id -> list of processed timestamps


def check_and_record_usage(user_id: str):
    now = datetime.utcnow()
    window_start = now - timedelta(days=7)
    history = [t for t in _usage.get(user_id, []) if t > window_start]
    if len(history) >= FREE_VIDEOS_PER_WEEK:
        raise HTTPException(
            status_code=429,
            detail=f"Free limit reached: {FREE_VIDEOS_PER_WEEK} videos per 7 days. Try again later.",
        )
    history.append(now)
    _usage[user_id] = history


# --- In-memory job tracking (swap for Redis/DB if you need multi-instance) ---
_jobs: dict[str, dict] = {}


class ProcessRequest(BaseModel):
    url: str
    user_id: Optional[str] = "anonymous"


app = FastAPI(title="ClipForge AI Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this to your real frontend domain in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/files", StaticFiles(directory=CLIPS_DIR), name="files")


def _run_pipeline(job_id: str, source_path: str):
    try:
        _jobs[job_id]["status"] = "transcribing"
        segments = transcribe(source_path)

        _jobs[job_id]["status"] = "finding_highlights"
        candidates = find_clip_candidates(segments)

        if not candidates:
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["error"] = "No clip-worthy moments found (video may be too short or silent)."
            return

        _jobs[job_id]["status"] = "rendering_clips"
        clips = []
        for idx, cand in enumerate(candidates):
            out_path = render_clip(source_path, cand, segments, CLIPS_DIR)
            filename = os.path.basename(out_path)
            clips.append({
                "id": filename.replace(".mp4", ""),
                "url": f"/files/{filename}",
                "start": round(cand.start, 1),
                "end": round(cand.end, 1),
                "duration": round(cand.end - cand.start, 1),
                "score": cand.score,
                "reason": cand.reason,
                "preview_text": cand.text[:140],
            })

        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["clips"] = clips
    except Exception as e:
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(e)
        _jobs[job_id]["trace"] = traceback.format_exc()
    finally:
        if os.path.exists(source_path):
            os.remove(source_path)


@app.post("/api/process-url")
def process_url(req: ProcessRequest, background_tasks: BackgroundTasks):
    check_and_record_usage(req.user_id)
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "downloading", "clips": None, "error": None}

    try:
        source_path = download_from_url(req.url, SOURCE_DIR)
    except Exception as e:
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = f"Download failed: {e}"
        return {"job_id": job_id}

    background_tasks.add_task(_run_pipeline, job_id, source_path)
    return {"job_id": job_id}


@app.post("/api/process-upload")
def process_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_id: str = Form("anonymous"),
):
    check_and_record_usage(user_id)
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "saving_upload", "clips": None, "error": None}

    content = file.file.read()
    source_path = save_uploaded_file(content, file.filename, SOURCE_DIR)

    background_tasks.add_task(_run_pipeline, job_id, source_path)
    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
def get_status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/usage/{user_id}")
def get_usage(user_id: str):
    now = datetime.utcnow()
    window_start = now - timedelta(days=7)
    history = [t for t in _usage.get(user_id, []) if t > window_start]
    return {"used": len(history), "limit": FREE_VIDEOS_PER_WEEK}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/debug-cookies")
def debug_cookies():
    """
    TEMPORARY debug endpoint - checks whether the cookies file is present
    and readable, without exposing the actual cookie values.
    Remove this endpoint once cookies are confirmed working.
    """
    cookies_path = os.environ.get("COOKIES_FILE", "not set")
    result = {"COOKIES_FILE_env": cookies_path}

    if cookies_path and cookies_path != "not set":
        exists = os.path.exists(cookies_path)
        result["file_exists"] = exists
        if exists:
            size = os.path.getsize(cookies_path)
            result["file_size_bytes"] = size
            with open(cookies_path, "r", errors="replace") as f:
                first_line = f.readline().strip()
                line_count = 1 + sum(1 for _ in f)
            result["first_line"] = first_line
            result["total_lines"] = line_count
        else:
            # Show what IS in /etc/secrets/ to help diagnose
            secrets_dir = "/etc/secrets"
            if os.path.exists(secrets_dir):
                result["files_in_etc_secrets"] = os.listdir(secrets_dir)
            else:
                result["etc_secrets_exists"] = False
    return result


@app.get("/api/debug-pot")
def debug_pot():
    """
    TEMPORARY debug endpoint - checks whether the bgutil PO-Token provider
    HTTP server is reachable, and asks yt-dlp (verbosely) whether it can
    see and use it. Remove once PO tokens are confirmed working.
    """
    import subprocess
    import urllib.request
    result = {}

    # 1) Is the provider server itself up on port 4416?
    try:
        with urllib.request.urlopen("http://127.0.0.1:4416/ping", timeout=3) as resp:
            result["provider_server_reachable"] = True
            result["provider_server_status"] = resp.status
    except Exception as e:
        result["provider_server_reachable"] = False
        result["provider_server_error"] = str(e)

    # 2) Ask yt-dlp what PO-Token providers it sees (verbose debug line).
    try:
        proc = subprocess.run(
            ["yt-dlp", "-v", "--simulate", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
            capture_output=True, text=True, timeout=30,
        )
        output = proc.stdout + proc.stderr
        pot_lines = [line for line in output.splitlines() if "pot" in line.lower() or "PO Token" in line]
        result["yt_dlp_pot_debug_lines"] = pot_lines
        result["yt_dlp_returncode"] = proc.returncode
        if not pot_lines:
            result["full_output_tail"] = output[-1500:]
    except Exception as e:
        result["yt_dlp_check_error"] = str(e)

    return result


@app.get("/api/debug-verbose")
def debug_verbose(url: str):
    """
    TEMPORARY debug endpoint - runs yt-dlp verbosely against a REAL video
    URL (without downloading it) so we can see exactly which client was
    tried, whether cookies were loaded, and whether a PO token was used.
    Remove once the bot-check issue is resolved.
    """
    cookies_path = os.environ.get("COOKIES_FILE")
    cmd = ["yt-dlp", "-v", "--skip-download", "--extractor-args", "youtube:player_client=web,android"]
    if cookies_path and os.path.exists(cookies_path):
        writable = "/tmp/debug_cookies.txt"
        shutil.copyfile(cookies_path, writable)
        cmd += ["--cookies", writable]
    cmd.append(url)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        output = proc.stdout + proc.stderr
        return {
            "returncode": proc.returncode,
            "output_tail": output[-4000:],
        }
    except Exception as e:
        return {"error": str(e)}
