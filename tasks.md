awesome — moving to **Step 4 — Execute the plan**. here’s a crisp, hand-off friendly task breakdown with deliverables, DoD, and tests. you can drop these straight into issues for Claude Code/Cursor.

# Work packages & tasks (with DoD + tests)

## WP1 — session core

**Goal:** lifecycle for a single cast session (ids, paths, timers, cleanup).

* **T1.1 `Session` model + ID**

  * *Deliverable:* `app/core/session.py` with `Session(id, dir, state, started_at, last_ok_at)`.
  * *DoD:* unit tests create/serialize a session; ULID/UUID IDs; ensures dirs created under `/sessions/{id}`.
  * *Tests:* `tests/unit/test_session.py` (create, persist, cleanup).

* **T1.2 freshness checker**

  * *Deliverable:* `SessionFreshness` that inspects `index.m3u8` mtime and newest segment age.
  * *DoD:* returns `last_segment_age_ms`; flags stale if > 8000 ms.
  * *Tests:* use tmpdir; touch files with backdated mtimes.

* **T1.3 cleanup**

  * *Deliverable:* `session.cleanup()` deletes segments; idempotent.
  * *DoD:* safe if encoder still running (no crash).
  * *Tests:* run twice; no exceptions; dirs removed.

---

## WP2 — renderer (Playwright + Xvfb)

**Goal:** open URL in Chromium under Xvfb at fixed viewport; optional cookies/profile.

* **T2.1 Xvfb wrapper**

  * *Deliverable:* `app/render/xvfb.py` with `Xvfb(display=":99", size=1920x1080)` context manager.
  * *DoD:* starts/stops Xvfb; sets `DISPLAY`; logs PID.
  * *Tests:* mock subprocess; ensure env set, stop kills proc.

* **T2.2 Playwright driver**

  * *Deliverable:* `app/render/playwright_driver.py` with:

    * `launch(url, width, height, cookies=None, user_data_dir=None, extra_headers=None)`
    * `close()`
  * *DoD:* loads page, waits for `networkidle` or timeout; cookie injection via `context.add_cookies`; supports `user_data_dir` path.
  * *Tests:* spin a tiny `http.server` (or FastAPI) page; assert `page.title()` fetched; cookie visible in `document.cookie`.

* **T2.3 anti-sleep/keepalive script**

  * *Deliverable:* inject small JS to disable page sleeps (visibility timers, etc.).
  * *DoD:* no JS errors on typical dashboards.
  * *Tests:* not strict — smoke test: no console errors captured.

---

## WP3 — encoder (FFmpeg → HLS)

**Goal:** capture X display and write HLS; 1080p\@15, \~6–8s latency.

* **T3.1 baseline HLS pipeline (video-only)**

  * *Deliverable:* `app/capture/ffmpeg_hls.py` with `start(display, out_dir, profile)` and `stop()`.
  * *Cmd (starter):*

    ```
    ffmpeg -loglevel warning -nostdin -y \
      -f x11grab -framerate 15 -video_size 1920x1080 -i :99 \
      -c:v libx264 -preset veryfast -tune zerolatency \
      -b:v 3500k -maxrate 3500k -bufsize 7000k \
      -g 30 -keyint_min 30 -sc_threshold 0 \
      -hls_time 2 -hls_list_size 6 -hls_flags delete_segments+independent_segments \
      -master_pl_name index.m3u8 -f hls /sessions/{id}/variant_1080p.m3u8
    ```
  * *DoD:* playlist + segments exist within 5s; updated every \~2s.
  * *Tests:* integration test waits for `index.m3u8` and ≥3 segments.

* **T3.2 optional audio input**

  * *Deliverable:* flag `audio=True` adds `-f pulse -i default -c:a aac -b:a 128k`.
  * *DoD:* HLS includes audio track (when Pulse available).
  * *Tests:* skip on CI if Pulse absent; local manual.

* **T3.3 health probe**

  * *Deliverable:* `is_fresh(max_ms=8000)` checks newest segment age.
  * *DoD:* returns True during run; False after stop.
  * *Tests:* assert toggles with process lifecycle.

---

## WP4 — HTTP server (FastAPI)

**Goal:** serve HLS, expose control/status API.

* **T4.1 static serving of session dir**

  * *Deliverable:* `GET /cast/{id}/` mounted to `/sessions/{id}` (whitelist).
  * *DoD:* remote `curl` fetches `index.m3u8` and segments.
  * *Tests:* integration — create dummy files; fetch via TestClient.

* **T4.2 control endpoints**

  * *Deliverable:*

    * `POST /sessions` (StartRequest)
    * `GET /sessions/{id}/status` (SessionStatus)
    * `DELETE /sessions/{id}` (stop + cleanup)
    * `GET /healthz`
  * *DoD:* e2e creates session → status shows fresh → delete cleans up.
  * *Tests:* happy path + 404s.

---

## WP5 — FCast sender adapter

**Goal:** discover receivers and play/stop via `fcast-client`.

* **T5.1 list receivers**

  * *Deliverable:* `sender/fcast_adapter.py: discover() -> list[Receiver]`.
  * *DoD:* prints names/ids.
  * *Tests:* mocked client; returns fixtures.

* **T5.2 play & stop**

  * *Deliverable:* `play(receiver_name, media_url, title=None)`, `stop(receiver_name)`.
  * *DoD:* plays public test HLS (e.g., local sample) on a receiver; stop halts.
  * *Tests:* mock transport; assert payloads built correctly.

* **T5.3 subscribe to status (optional MVP+)**

  * *Deliverable:* callback wire-up to reflect receiver state into `SessionStatus.receiver_state`.
  * *DoD:* basic event logging.

---

## WP6 — CLI (Typer)

**Goal:** one command to run the whole flow; small helpers.

* **T6.1 `cast-webpage start`**

  * *Deliverable:* `app/cli.py`:

    ```
    cast-webpage start --url ... --receiver "TV 1" \
      --width 1920 --height 1080 --fps 15 \
      --bitrate 3500k --audio/--no-audio \
      --cookies cookies.json --user-data-dir /data/profile
    ```
  * *DoD:* starts Xvfb→Playwright→FFmpeg→serves HLS→plays via FCast; Ctrl+C/`stop` cleans up.
  * *Tests:* smoke: start then stop within 10s; asserts files created.

* **T6.2 helpers**

  * `cast-webpage list-receivers`
  * `cast-webpage stop --session ID`
  * `cast-webpage status --session ID`
  * *DoD:* all commands return non-error; human-readable.

---

## WP7 — containerisation

**Goal:** single container, host networking, arm64-ready.

* **T7.1 Dockerfile**

  * *Deliverable:* multi-stage `Dockerfile`:

    * base `python:3.12-slim`
    * install `ffmpeg`, `xvfb`, `playwright` (+ `playwright install --with-deps chromium`)
    * `pip install` app deps (`fastapi`, `uvicorn`, `playwright`, `typer`, `pydantic`, `fcast-client`, `uvloop`, `httptools`, `rich`, `ruff`, `pytest`)
    * entrypoint script starts uvicorn API, then orchestrates session on CLI command.
  * *DoD:* `docker run --rm --network host -v /sessions:/sessions image cast-webpage ...` works on AMD64 + ARM64.
  * *Tests:* buildx multi-arch build in CI (no run on arm in CI unless emulation).

* **T7.2 dev compose**

  * *Deliverable:* `docker-compose.yml` with host net, bind-mount `/sessions`, env for defaults.
  * *DoD:* `docker compose up` exposes API at `:8080`.

---

## WP8 — config & profiles

**Goal:** easy presets for bitrate/fps/size and auth inputs.

* **T8.1 YAML profiles**

  * *Deliverable:* `profiles/1080p15.yml`, `profiles/720p30.yml`.
  * *DoD:* CLI `--profile 1080p15` loads defaults; flags override.

* **T8.2 cookies & headers**

  * *Deliverable:* `--cookies path.json`, `--extra-header "Name: Value"` (multi).
  * *DoD:* visible to target site; simple example in README.

---

## WP9 — QA & CI

**Goal:** basic hygiene & e2e confidence.

* **T9.1 lint & tests**

  * *Deliverable:* ruff + pytest; GitHub Actions workflow:

    * Lint
    * Unit tests
    * Integration test with `xvfb-run` (no FFmpeg audio)
    * Build multi-arch image
  * *DoD:* green pipeline; artifacts include test logs.

* **T9.2 smoke script**

  * *Deliverable:* `scripts/smoke.sh` that:

    * starts API
    * POST /sessions with `url=http://localhost:8080/_demo`
    * waits for fresh HLS
    * lists receivers (mock in CI)
    * stops session
  * *DoD:* exit 0 locally.

---

# Minimal starter artifacts (you can paste straight in)

### `pyproject.toml` (core bits)

```toml
[project]
name = "webcast-fcast"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi",
  "uvicorn[standard]",
  "typer[all]",
  "pydantic>=2",
  "playwright",
  "fcast-client",
  "rich",
]

[tool.ruff]
line-length = 100
```

### `Dockerfile` (starter)

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg xvfb libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libasound2 libxkbcommon0 libgbm1 curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Playwright + Chromium
RUN pip install --no-cache-dir playwright && \
    playwright install --with-deps chromium

# App deps
COPY pyproject.toml /app/
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn[standard] typer[all] pydantic fcast-client rich

# App code
COPY app /app/app

ENV PYTHONUNBUFFERED=1 \
    SESSIONS_DIR=/sessions \
    DISPLAY=:99

VOLUME ["/sessions"]

# Default: provide API; CLI runs via docker run ... cast-webpage
CMD ["uvicorn", "app.serve.http_api:app", "--host", "0.0.0.0", "--port", "8080"]
```

### `app/serve/http_api.py` (skeleton)

```python
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
from pathlib import Path
import os

SESSIONS_DIR = Path(os.getenv("SESSIONS_DIR", "/sessions"))
app = FastAPI()

class StartRequest(BaseModel):
    url: HttpUrl
    receiver_name: str
    width: int = 1920
    height: int = 1080
    fps: int = 15
    video_bitrate: str = "3500k"
    audio: bool = False
    cookies_path: str | None = None
    user_data_dir: str | None = None

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.post("/sessions")
def start_session(req: StartRequest):
    # TODO: orchestrate (WP1-5)
    return {"id": "TODO", "hls": f"/cast/TODO/index.m3u8"}

@app.get("/sessions/{sid}/status")
def status(sid: str):
    # TODO
    return {"id": sid, "state": "starting"}

@app.delete("/sessions/{sid}")
def stop(sid: str):
    # TODO
    return {"ok": True}

# mount static for any existing session dirs
if SESSIONS_DIR.exists():
    app.mount("/cast", StaticFiles(directory=str(SESSIONS_DIR), html=False), name="cast")
```

### `app/sender/fcast_adapter.py` (skeleton)

```python
from typing import List

class Receiver(dict): ...
def discover() -> List[Receiver]:
    # TODO: wrap fcast-client lib to return names/ids
    return []

def play(receiver_name: str, media_url: str, title: str | None = None) -> None:
    # TODO: call fcast-client play API
    ...

def stop(receiver_name: str) -> None:
    # TODO
    ...
```

### `Makefile` (handy)

```makefile
.PHONY: dev build run lint test

dev:
\tuvicorn app.serve.http_api:app --reload --host 0.0.0.0 --port 8080

lint:
\truff check .

test:
\tpytest -q

build:
\tdocker buildx build --platform linux/amd64,linux/arm64 -t you/webcast-fcast:edge .

run:
\tdocker run --rm --network host -v $$PWD/sessions:/sessions you/webcast-fcast:edge
```

---

# Acceptance checklist for MVP demo

* [ ] `docker run --network host ... cast-webpage start --url https://your-dashboard` renders and begins segmenting within \~5s.
* [ ] `curl http://<host>:8080/cast/<id>/index.m3u8` returns a playlist with ≥3 segments.
* [ ] `cast-webpage list-receivers` shows your two Pi-attached screens.
* [ ] `cast-webpage start ... --receiver "Screen A"` starts playback on that receiver.
* [ ] `cast-webpage stop --session <id>` halts; segments cleaned in ≤3s.
* [ ] Optional: `--cookies cookies.json` works for an auth’d dashboard.

