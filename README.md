# Webcast FCast (MVP)

Cast any web page to FCast receivers by rendering in headless Chromium and streaming HLS.

## Quickstart (local)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
python -m playwright install --with-deps chromium
mkdir -p sessions
export SESSIONS_DIR=$PWD/sessions HOST_PORT=8080
uvicorn app.serve.http_api:app --host 0.0.0.0 --port 8080
# in another shell:
python app/cli.py start https://example.com --receiver "Living Room"
```

Cookies format

--cookies cookies.json expects an array of Playwright cookie objects:
```json
[
  {"name":"session","value":"abc123","domain":".example.com","path":"/","httpOnly":true,"secure":true}
]
```

## Optional Dev Compose

```yaml

---

# 4) Optional: dev compose

## `docker-compose.yml`
```yaml
services:
  webcast:
    build: .
    network_mode: host
    environment:
      SESSIONS_DIR: /sessions
      HOST_PORT: 8080
      FC_HOSTNAME_OVERRIDE: 192.168.1.50 # set to your host IP
    volumes:
      - ./sessions:/sessions
```

## Sanity checklist to run locally

- pytest → all green
- uvicorn app.serve.http_api:app → /healthz returns ok
- python app/cli.py start <URL> --receiver "<Your FCast receiver>" → session id shown
- Receiver plays http://<host>:8080/cast/<id>/index.m3u8 within ~5–8 s
- python app/cli.py stop <id> cleans up

## local - no container

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
python -m playwright install --with-deps chromium
mkdir -p sessions
SESSIONS_DIR=$PWD/sessions HOST_PORT=8080 uvicorn app.serve.http_api:app --reload --host 0.0.0.0 --port 8080
# in another shell:
python app/cli.py start https://example.com --receiver "Living Room"
```

## in a container with host networking

```bash
docker build -t you/webcast-fcast:edge .
docker run --rm --network host -e HOST_PORT=8080 -e SESSIONS_DIR=/sessions \
  -v $PWD/sessions:/sessions you/webcast-fcast:edge
# in another shell on host:
API=http://localhost:8080 python app/cli.py start https://example.com --receiver "Living Room"
```

## Notes / next steps

Audio later: add PulseAudio/PipeWire and -f pulse -i default -c:a aac -b:a 128k to ffmpeg in FfmpegHls.start().

Multiple receivers: once stable, loop over a list and sender.play() for each.

LL-HLS: if you want lower glass-to-glass, change -hls_time to ~1s and adjust list size; 6–8s is fine for dashboards.

Perf on Pi 4: If needed, drop to 1600×900@15 or lower bitrate. Later try h264_v4l2m2m/VAAPI.

