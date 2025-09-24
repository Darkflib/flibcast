from __future__ import annotations
import json
import os
from pathlib import Path
import time
import typer
import requests
from rich import print

API = os.getenv("API", "http://localhost:8080")

app = typer.Typer(add_completion=False, help="Cast a webpage to an FCast receiver")


@app.command("start")
def start(
    url: str = typer.Argument(..., help="Web page URL"),
    receiver: str = typer.Option(..., "--receiver", "-r", help="Receiver name"),
    receiver_host: str | None = typer.Option(None, help="Receiver host/IP (bypass discovery)"),
    receiver_port: int = typer.Option(46899, help="Receiver port"),
    hide_browser_ui: bool = typer.Option(
        True,
        "--hide-browser-ui/--show-browser-ui",
        help="Hide Chromium chrome (fullscreen) in the capture window",
        show_default=True,
    ),
    width: int = 1920,
    height: int = 1080,
    fps: int = 15,
    bitrate: str = "3500k",
    cookies: Path | None = typer.Option(None, help="Path to cookies.json"),
    user_data_dir: Path | None = typer.Option(None, help="Chromium user-data-dir"),
    title: str | None = typer.Option(None, help="Media title"),
):
    payload = {
        "url": url,
        "receiver_name": receiver,
        "receiver_host": receiver_host,
        "receiver_port": receiver_port,
        "hide_browser_ui": hide_browser_ui,
        "width": width,
        "height": height,
        "fps": fps,
        "video_bitrate": bitrate,
        "audio": False,
        "cookies_path": str(cookies) if cookies else None,
        "user_data_dir": str(user_data_dir) if user_data_dir else None,
        "title": title,
    }
    r = requests.post(f"{API}/sessions", json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    sid = data["id"]
    print(f"[bold green]Session:[/bold green] {sid}  HLS: {data['hls_url']}")
    print("Waiting for segments...")
    fresh = None
    for _ in range(20):
        time.sleep(1)
        s = requests.get(f"{API}/sessions/{sid}/status", timeout=10).json()
        fresh = s.get("last_segment_age_ms")
        if fresh is not None and fresh < 8000:
            print("[green]Streaming looks fresh.[/green]")
            break
    print("[yellow]Use Ctrl+C then `stop` to clean up if needed.[/yellow]")


@app.command("status")
def status(sid: str):
    r = requests.get(f"{API}/sessions/{sid}/status", timeout=10)
    if r.status_code != 200:
        print("[red]Not found[/red]")
        raise typer.Exit(1)
    print(json.dumps(r.json(), indent=2))


@app.command("stop")
def stop(sid: str):
    r = requests.delete(f"{API}/sessions/{sid}", timeout=10)
    r.raise_for_status()
    print("[green]Stopped.[/green]")


if __name__ == "__main__":
    app()
