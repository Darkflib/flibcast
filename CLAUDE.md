# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Webcast FCast is a web-to-FCast streaming service that renders web pages in headless Chromium and streams them as HLS to FCast receivers. The architecture consists of:

- **FastAPI HTTP API** (`app/serve/http_api.py`) - Main service endpoint
- **CLI interface** (`app/cli.py`) - Command-line client using Typer
- **Session management** (`app/core/session.py`) - Manages streaming sessions and HLS output
- **Browser rendering** (`app/render/`) - Playwright driver with Xvfb for headless display
- **FFmpeg capture** (`app/capture/ffmpeg_hls.py`) - Captures display and encodes to HLS
- **FCast integration** (`app/sender/fcast_adapter.py`) - Sends streams to FCast receivers

## Development Commands

### Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
python -m playwright install --with-deps chromium
mkdir -p sessions
```

### Testing
```bash
pytest -q                    # Run all tests
pytest tests/unit/           # Unit tests only
pytest tests/integration/    # Integration tests only
```

### Linting
```bash
ruff check .                 # Check code style and quality
```

### Running the Service
```bash
# Local development
SESSIONS_DIR=$PWD/sessions HOST_PORT=8080 uvicorn app.serve.http_api:app --reload --host 0.0.0.0 --port 8080

# Using CLI
python app/cli.py start https://example.com --receiver "Living Room"
```

## Architecture Notes

### Session Orchestration
The service orchestrates multiple components for each streaming session:
1. **Xvfb** - Virtual framebuffer for headless display
2. **Playwright** - Browser automation for web page rendering
3. **FFmpeg** - Screen capture and HLS encoding
4. **FCast Sender** - Delivers stream to receiver

Sessions are managed with unique IDs and have states: `starting`, `playing`, `stopping`, `stopped`, `error`.

### Environment Variables
- `SESSIONS_DIR` - Directory for HLS output files (default: `/sessions`)
- `HOST_PORT` - API server port (default: `8080`)
- `FC_HOSTNAME_OVERRIDE` - Override hostname for FCast URLs
- `API` - CLI client API endpoint (default: `http://localhost:8080`)

### Key Components
- `SessionManager` - Creates, tracks, and cleans up streaming sessions
- `BrowserController` - Manages Playwright browser instances with cookie/user-data support
- `FfmpegHls` - Configurable HLS encoding with video profiles
- `Sender` - FCast device communication using fcast-client library

### Testing Structure
- Unit tests focus on individual components (Xvfb, FFmpeg commands, sessions)
- Integration tests verify API endpoints and service interaction
- Tests use pytest with environment setup for sessions directory