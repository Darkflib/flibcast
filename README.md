# Webcast FCast

Render any web page in headless Chromium, capture the pixels with FFmpeg, and stream the result to FCast receivers over HLS.

## Features
- Session controller API (FastAPI) with `/sessions` lifecycle and `/cast/{id}/` static HLS hosting
- Headless rendering pipeline (Xvfb ➜ Playwright ➜ FFmpeg) with freshness monitoring and cleanup
- Optional FCast sender integration via `fcast-client` for discovery/playback
- Typer CLI for quick starts/stops without crafting HTTP requests manually

## Requirements
- Python 3.12+
- System packages: `ffmpeg`, `xvfb`, Chromium dependencies (installed automatically by Playwright)
- Optional: [`fcast-client`](https://pypi.org/project/fcast-client/) for receiver control

## Environment variables
| Variable | Purpose | Default |
| --- | --- | --- |
| `SESSIONS_DIR` | Directory where HLS artifacts are written | `<repo>/sessions` |
| `HOST_PORT` | Public port the API serves on (used to form HLS URLs) | `8080` |
| `DISPLAY` | X display used by Xvfb/FFmpeg | `:99` (handled internally) |
| `FC_HOSTNAME_OVERRIDE` | Host/IP advertised to receivers | Resolved host address |
| `API` | Base URL used by the CLI | `http://localhost:8080` |

## Setup (using `uv`)
```bash
# Install Python dependencies + dev tools
uv sync --group dev

# Install Chromium + Playwright runtime (once)
uv run playwright install --with-deps chromium

# Create a writable sessions directory
mkdir -p sessions
```

If you prefer virtualenv/pip, the project exposes the same dependencies via `pyproject.toml`.

## Running the API
```bash
export SESSIONS_DIR=$PWD/sessions HOST_PORT=8080
uv run uvicorn app.serve.http_api:app --host 0.0.0.0 --port ${HOST_PORT}
```

The server exposes:
- `GET /healthz` – health probe
- `POST /sessions` – start a new cast session
- `GET /sessions` – list known sessions and their freshness metadata
- `GET /sessions/{id}/status` – poll state & segment freshness
- `DELETE /sessions/{id}` – stop and clean up a session
- `GET /receivers` – enumerate available FCast receivers (requires `fcast-client`)
- `GET /cast/{id}/index.m3u8` – HLS master playlist for active sessions

### Starting a session via cURL
```bash
curl -X POST http://localhost:8080/sessions \
  -H 'Content-Type: application/json' \
  -d '{
        "url": "https://example.com",
        "receiver_name": "Living Room",
        "receiver_host": "192.168.16.237",
        "receiver_port": 46899,
        "width": 1920,
        "height": 1080,
        "fps": 15,
        "video_bitrate": "3500k",
        "audio": false
      }'
```

## CLI usage
```bash
# Start a new session (uses API env var for base URL)
uv run python app/cli.py start https://example.com \
  --receiver "Living Room" \
  --receiver-host 192.168.16.237

# Inspect status
uv run python app/cli.py status <session-id>

# Stop and clean up
uv run python app/cli.py stop <session-id>
```

Cookies can be supplied via `--cookies path/to/cookies.json`; the file should contain a Playwright-compatible cookie list.

## Receiver discovery

Receiver control is optional, but when [`fcast-client`](https://pypi.org/project/fcast-client/) is installed you can list available devices straight from Python:

```bash
uv run python -c "from app.sender.fcast_adapter import Sender; print(Sender().discover())"
```

Or via the API:

```bash
curl http://localhost:8080/receivers | jq
```

Each entry is a `{name, id}` pair. Use the `name` field when calling the CLI or `POST /sessions`. If nothing is returned:

- Make sure the machine running the API is on the same network segment as your receivers.
- Some receivers require multicast/UDP discovery; ensure firewalls allow it.
- Verify that the `fcast-client` install is visible to the virtual environment (`uv pip list | grep fcast`).

You can also embed discovery in your own tools by importing `Sender` and reusing its `discover()`, `play()`, and `stop()` helpers.

**No discovery?** Provide `receiver_host` (and optionally `receiver_port`) in the session request or `--receiver-host` on the CLI to connect directly. This path uses the raw `fcast` TCP client and works even when mDNS is blocked (e.g., WSL2 or segmented networks).

## Session management

Sessions transition through a small state machine:

| State | Meaning |
| --- | --- |
| `starting` | Orchestration thread is provisioning Xvfb/Playwright/FFmpeg |
| `playing` | HLS output is fresh (new segments generated under `sessions/<id>/`) |
| `stopping` | A stop request is in progress; teardown will complete soon |
| `stopped` | Runtime has been torn down and directories cleaned |
| `error` | The pipeline failed (stale HLS, missing binaries, etc.) |

Use the status endpoint or CLI command to poll `last_segment_age_ms`; values below ~8000 ms indicate the playlist is still live. When you delete a session (API or CLI) the runtime stops FFmpeg, closes the browser, signals Xvfb, tells the receiver to stop, and finally removes the session directory. Deleting an already-failed session is safe—the cleanup routines are idempotent.

**Manual cleanup:** If the process hosting the API is interrupted, call `python -c "from app.core.session import SessionManager; SessionManager().all()"` to see any orphaned sessions and delete the corresponding directories.

The API also runs a shutdown hook: stopping the server triggers a graceful teardown of any remaining runtimes, so leaving sessions active won't leak processes between restarts.

## Running tests & lint
```bash
# Unit + integration tests (stubs are used for external binaries)
uv run pytest -q

# Static analysis
uv run ruff check
```

## Docker
```bash
docker build -t webcast-fcast:dev .
docker run --rm --network host \
  -e HOST_PORT=8080 -e SESSIONS_DIR=/sessions \
  -v $PWD/sessions:/sessions \
  webcast-fcast:dev
```

With the container running, interact via the CLI from the host:
```bash
API=http://localhost:8080 uv run python app/cli.py start https://example.com --receiver "Living Room"
```

## Architecture overview
1. **SessionManager** provisions per-session directories, IDs, and lifecycle metadata.
2. **Renderer** spins up Xvfb and Playwright to keep the target page active, injecting an anti-sleep script.
3. **Capture** runs FFmpeg against the virtual display to produce HLS segments and playlists, exposing freshness probes used by the API.
4. **Sender** (optional) uses `fcast-client` to instruct receivers to play/stop the generated HLS URL.

Cleanup is idempotent: stopping a session tears down FFmpeg, Playwright, Xvfb, and removes artifacts even if a component has already exited.

## Troubleshooting
- **`FileNotFoundError: 'Xvfb'`** – install the `xvfb` system package (`sudo apt-get install xvfb`) or use the Docker image which bundles all binaries. Double-check that the binary is on `PATH` for the user running the API.
- **`No FCast client available; skipping play`** – the optional dependency is missing. Install it (`uv add fcast-client`) and restart the API to enable automatic playback.
- **No receivers returned** – see the discovery checklist above. Some Wi-Fi setups block multicast; try plugging into wired Ethernet or adjusting firewall rules. You can also hard-code an ID by calling `Sender(client=...).play("<name>", url)` in a REPL to confirm connectivity.
- **“not enough frames to estimate rate” (FFmpeg)** – harmless startup warning. It disappears once the page begins rendering. If it persists, ensure Playwright can reach the target URL (headless browsers still respect network/firewall policies).
- **Stale session (`state = error`)** – inspect logs. Typical culprits: the page redirected indefinitely, `ffmpeg` exited because the display or audio device disappeared, or the host name advertised to receivers is unreachable. Adjust `FC_HOSTNAME_OVERRIDE`, `video_bitrate`, or supply cookies/user-data for authenticated dashboards.

---
Happy casting!
