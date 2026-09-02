FROM python:3.11-slim

# ffmpeg is required for clipping/cropping/caption burning.
# Node.js + git are required for the yt-dlp PO-Token provider (bgutil),
# which YouTube now effectively requires from datacenter IPs like Render's -
# cookies alone are no longer enough. See pipeline/downloader.py comments.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    curl \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Set up the bgutil PO-Token provider HTTP server (runs on port 4416,
# yt-dlp's PO-Token plugin auto-detects it there with no extra config).
RUN git clone --single-branch --branch 1.3.1 \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil-provider \
    && cd /opt/bgutil-provider/server \
    && npm ci \
    && npx tsc

COPY . .

RUN mkdir -p work/sources work/clips

EXPOSE 8000

# Start the PO-Token provider server in the background on a FIXED port
# (4416) that is NOT influenced by Render's $PORT env var - Node apps
# commonly auto-read process.env.PORT, which would otherwise make this
# server hijack the port Render routes public traffic to, instead of the
# FastAPI app. Explicitly unsetting PORT for that one process, and passing
# --port 4416 to be doubly sure, keeps the two servers on separate ports.
# The main API binds to $PORT (falls back to 8000 locally) since Render
# assigns that dynamically and expects the app to listen there.
CMD ["/bin/sh", "-c", "env -u PORT node /opt/bgutil-provider/server/build/main.js --port 4416 & uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
