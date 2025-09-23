FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg xvfb libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libasound2 libxkbcommon0 libgbm1 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install runtime deps
RUN pip install --no-cache-dir fastapi uvicorn[standard] typer[all] pydantic rich playwright

# Install Chromium
RUN python -m playwright install --with-deps chromium

WORKDIR /app
COPY app /app/app

ENV PYTHONUNBUFFERED=1 \
    SESSIONS_DIR=/sessions \
    DISPLAY=:99 \
    HOST_ADDR=0.0.0.0 \
    HOST_PORT=8080

VOLUME ["/sessions"]

EXPOSE 8080
CMD ["uvicorn", "app.serve.http_api:app", "--host", "0.0.0.0", "--port", "8080"]

