# Sage on Cloud Run.
#
# 3.11 to match .devcontainer; -slim because pymupdf, pillow and pypdf all ship
# manylinux wheels, so there is no apt layer to add and the image stays small
# enough to sit inside Artifact Registry's 0.5 GB free tier.
FROM python:3.11-slim

# PYTHONUNBUFFERED so Streamlit's logs reach Cloud Logging as they happen rather
# than when the buffer fills -- structured logs are half the point of deploying here.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Requirements first so an edit to sage/ does not re-resolve the dependency tree.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# The corpus ships inside the image: `docs/` (72 .md, 767 KB -- the User Guide, and the
# higher-weighted of the two sources) and `web/` (55 scraped .txt, 341 KB), plus
# docs_snapshot.json. About 1.1 MB, small enough that pulling it from Cloud Storage at
# boot would cost more cold-start time than it saves in image size. `.gcloudignore`
# says which parts of `docs/` are left behind and why -- it is the 42 MB of screenshots,
# never the markdown.
COPY . .

# Cloud Run runs as root by default; it does not have to.
RUN useradd --create-home --uid 1000 sage && chown -R sage:sage /app
USER sage

# Streamlit's own config, set here so the CMD line stays about Cloud Run.
#   headless   -- skip the "enter your email" first-run prompt
#   enableCORS -- Cloud Run terminates TLS and proxies the WebSocket; the origin
#                 check sees the proxy, not the browser, and rejects the upgrade
#   gatherUsageStats -- no phoning home from a deployed app
ENV STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ENABLE_CORS=false \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# XSRF protection stays ON. If file attachments fail through the proxy, add
#   STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=false
# and know that you are turning off a CSRF guard on a public URL. Sage is read-only,
# so the blast radius is small -- but it is a deliberate choice, not a default.

# Shell form: $PORT is injected by Cloud Run at start time (8080), so it has to be
# expanded by a shell rather than baked in. `exec` keeps Streamlit as PID 1 so it
# receives SIGTERM and shuts down cleanly when the instance scales to zero.
EXPOSE 8080
CMD exec streamlit run app.py \
      --server.port="${PORT:-8080}" \
      --server.address=0.0.0.0
