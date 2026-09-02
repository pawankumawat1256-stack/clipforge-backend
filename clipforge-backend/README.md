# ClipForge AI — Backend

Turns a long video (YouTube URL or upload) into scored, captioned, 9:16 short
clips. 100% open-source pipeline — **no paid API required**:

- **yt-dlp** — downloads the source video
- **faster-whisper** — free local transcription with word-level timestamps
- **heuristic scorer** (`pipeline/highlights.py`) — finds "clip-worthy" moments
  using keyword/pattern rules (no LLM call, so it's free at any scale)
- **ffmpeg** — trims, crops to 9:16, and burns in styled word-by-word captions

This has been tested end-to-end in this environment: a synthetic video was
run through crop + caption burning and produced a correct 1080x1920 output
with captions rendering at the right timestamp. Transcription and download
depend on network access to YouTube/Whisper's model weights, which you'll
have on your own machine or host — they aren't reachable from this sandbox,
so test those two steps once you deploy.

## Local setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# ffmpeg must be installed on your system separately:
#   Ubuntu/Debian: sudo apt install ffmpeg
#   Mac:           brew install ffmpeg
#   Windows:       https://ffmpeg.org/download.html

uvicorn main:app --reload --port 8000
```

Visit `http://localhost:8000/docs` for interactive API docs (Swagger UI).

## API endpoints

- `POST /api/process-url` — body: `{"url": "...", "user_id": "..."}` → returns `{"job_id": "..."}`
- `POST /api/process-upload` — multipart form: `file`, `user_id` → returns `{"job_id": "..."}`
- `GET /api/status/{job_id}` — poll this until `status` is `"done"` or `"failed"`
- `GET /api/usage/{user_id}` — check free-tier usage (3 videos / 7 days by default)
- `GET /files/{clip_filename}` — serves the finished clip files

### Example flow (curl)

```bash
curl -X POST http://localhost:8000/api/process-url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=SOME_ID", "user_id": "demo"}'
# => {"job_id": "abc-123"}

curl http://localhost:8000/api/status/abc-123
# => {"status": "rendering_clips", ...}
# ... poll until status = "done" ...
# => {"status": "done", "clips": [{"url": "/files/xyz.mp4", "score": 88, ...}, ...]}
```

Your frontend (the bolt.new SaaS UI) should call these endpoints instead of
using mock data once you're ready to wire it up.

## Free-tier cost model (matches the "ad-funded, no payment" plan)

`main.py` enforces `FREE_VIDEOS_PER_WEEK = 3` per `user_id` in memory. This
protects your server from runaway processing cost. Tune the number in
`main.py`. For real usage tracking across server restarts, swap the
in-memory `_usage` dict for a small database (SQLite is enough to start).

Revenue path: put Google AdSense on the frontend site. Users never pay;
your ad impressions fund the compute.

## Deploying for free

**Render.com (recommended free tier):**
1. Push this folder to a GitHub repo.
2. New "Web Service" on Render → connect the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add a "Native Runtime" or Docker environment that includes `ffmpeg`
   (Render's default Python environment does not include it — see the
   included `Dockerfile`, which Render can build directly instead of the
   native buildpack).

**Railway.app** works the same way — connect repo, it detects the
`Dockerfile` automatically.

⚠️ Free tiers on both platforms have limited CPU/RAM and monthly hours.
Video transcription + ffmpeg encoding is CPU-heavy, so on a free instance
expect a ~10 minute video to take a few minutes to process. If you outgrow
the free tier, that's a sign of real usage — a good problem to have.

## Known constraints (be upfront with yourself about these)

- **Downloading YouTube videos via yt-dlp sits in a legal gray area** —
  YouTube's Terms of Service don't permit it, even though the tool is
  widely used. Worth knowing before you scale this publicly.
- **No GPU on free hosting tiers** → transcription runs on CPU. The
  `small` Whisper model is chosen as a speed/accuracy balance; drop to
  `base` in `pipeline/transcriber.py` if a free host is too slow.
- **Highlight scoring is heuristic, not true "AI understanding"** — it's
  free and works reasonably, but won't match a paid LLM-based scorer.
  See the comment at the bottom of `pipeline/highlights.py` for how to
  upgrade this later if you introduce a paid tier.
- **In-memory job/usage tracking** resets on server restart. Fine for an
  MVP; move to a real database before relying on it long-term.
