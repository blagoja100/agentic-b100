"""
TubeAgent Main CLI Entrypoint.
Usage:
    python main.py                  # Starts Web Dashboard & Background Watcher (Default)
    python main.py --daemon         # Runs as headless background daemon in terminal
    python main.py --auth           # Run interactive YouTube OAuth login wizard
    python main.py --status         # Display current configuration & channel status
    python main.py --scan           # Scan watch folder once
"""

import sys
import time
import argparse
import uvicorn
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from config import Config
from db import init_db, log_event, get_all_videos
from watcher import FolderWatcher
from agent import agent_instance
import youtube_uploader


def run_web(host: str = None, port: int = None):
    """Starts FastAPI web server and background watcher."""
    h = host or Config.WEB_HOST
    p = port or Config.WEB_PORT
    print(f"\n" + "=" * 60)
    print(f"🚀 Launching TubeAgent Web Dashboard...")
    print(f"👉 Open in browser: http://{h}:{p}")
    print(f"📁 Monitored Folder: {Config.WATCH_FOLDER}")
    print(f"📁 Processed Folder: {Config.PROCESSED_FOLDER}")
    print(f"=" * 60 + "\n")
    uvicorn.run("server:app", host=h, port=p, reload=False, log_level="info")


def run_daemon():
    """Runs as a headless terminal daemon."""
    init_db()
    Config.ensure_directories()
    
    print("\n" + "=" * 60)
    print("🤖 TubeAgent Running in Headless Daemon Mode")
    print(f"📁 Monitored Folder: {Config.WATCH_FOLDER}")
    print(f"⚙️ Auto-Upload: {'ENABLED' if Config.AUTO_UPLOAD else 'DISABLED (requires approval)'}")
    print("=" * 60 + "\n")

    watcher = FolderWatcher(on_video_ready=agent_instance.on_video_detected)
    watcher.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping daemon...")
        watcher.stop()
        print("Daemon stopped gracefully.")


def run_auth_cli():
    """Interactive OAuth login flow in CLI."""
    init_db()
    Config.ensure_directories()
    print("\n" + "=" * 60)
    print("🔑 YouTube Account OAuth Setup")
    print("=" * 60)

    if not Config.CLIENT_SECRETS_FILE.exists():
        print(f"\n❌ Error: '{Config.CLIENT_SECRETS_FILE}' not found!")
        print("To connect your YouTube channel:")
        print("1. Go to Google Cloud Console (https://console.cloud.google.com/)")
        print("2. Enable 'YouTube Data API v3'")
        print("3. Create an OAuth 2.0 Client ID (Application type: Desktop App)")
        print("4. Download the JSON and save it as 'client_secrets.json' in this folder.")
        print(f"Expected path: {Config.CLIENT_SECRETS_FILE.resolve()}\n")
        return

    print("Launching browser for Google Account authentication...")
    try:
        channel = youtube_uploader.run_oauth_flow(port=8088)
        print(f"\n✅ Connected successfully to channel: {channel.get('title')}")
        print(f"Channel ID: {channel.get('channel_id')}")
        print(f"Subscribers: {channel.get('subscribers')}")
    except Exception as e:
        print(f"\n❌ Authentication failed: {e}")


def show_status():
    """Displays current system status."""
    init_db()
    Config.ensure_directories()
    print("\n" + "=" * 60)
    print("📊 TubeAgent System Status")
    print("=" * 60)
    print(f"Watch Folder:       {Config.WATCH_FOLDER}")
    print(f"Processed Folder:   {Config.PROCESSED_FOLDER}")
    print(f"Default Privacy:    {Config.DEFAULT_PRIVACY}")
    print(f"Auto-Upload:        {'Enabled' if Config.AUTO_UPLOAD else 'Disabled'}")
    print(f"Gemini API Key:     {'Configured' if Config.GEMINI_API_KEY else 'Missing (using fallback)'}")
    print(f"Gemini Model:       {Config.GEMINI_MODEL}")
    
    print("\n[YouTube Account]")
    info = youtube_uploader.get_channel_info()
    if info.get("authenticated"):
        print(f"Status:             Connected ✓")
        print(f"Channel Name:       {info.get('title')}")
        print(f"Channel ID:         {info.get('channel_id')}")
        print(f"Subscribers:        {info.get('subscribers')}")
        print(f"Videos:             {info.get('videos')}")
    else:
        print(f"Status:             Not connected")
        print(f"Client Secrets:     {'Found' if info.get('has_client_secrets') else 'Missing client_secrets.json'}")

    videos = get_all_videos()
    print(f"\n[Video Queue: {len(videos)} total]")
    for v in videos[:10]:
        print(f" - #{v['id']} [{v['status']}] {v['filename']} -> {v.get('title') or '(no title)'}")
    print("=" * 60 + "\n")


def create_test_video():
    """Creates a sample mp4 placeholder file in the watch folder for testing."""
    Config.ensure_directories()
    test_file = Config.WATCH_FOLDER / "Sample_AI_Coding_Demo.mp4"
    
    # Create companion notes file too!
    notes_file = Config.WATCH_FOLDER / "Sample_AI_Coding_Demo.txt"
    with open(notes_file, "w", encoding="utf-8") as f:
        f.write("A deep dive into autonomous coding agents, how they plan and deploy web applications.\nKeywords: Python, Gemini, Fullstack.")

    # Write a dummy binary file to simulate video
    with open(test_file, "wb") as f:
        f.write(b"\x00\x00\x00 ftypisom\x00\x00\x02\x00isomiso2mp41\x00\x00\x00\x08free" + b"\x00" * 1024 * 50)
        
    print(f"✅ Created test video file: {test_file}")
    print(f"✅ Created companion notes: {notes_file}")


def main():
    parser = argparse.ArgumentParser(description="TubeAgent - Autonomous YouTube Video AI Agent")
    parser.add_argument("--web", action="store_true", help="Start Web Dashboard (Default)")
    parser.add_argument("--daemon", action="store_true", help="Run in headless terminal daemon mode")
    parser.add_argument("--auth", action="store_true", help="Run YouTube OAuth setup wizard")
    parser.add_argument("--status", action="store_true", help="Show system status and channel details")
    parser.add_argument("--scan", action="store_true", help="Perform a single folder scan")
    parser.add_argument("--create-test-video", action="store_true", help="Generate a sample test video in the watch folder")
    parser.add_argument("--port", type=int, default=8000, help="Web dashboard port")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Web dashboard host")

    args = parser.parse_args()

    if args.daemon:
        run_daemon()
    elif args.auth:
        run_auth_cli()
    elif args.status:
        show_status()
    elif args.create_test_video:
        create_test_video()
    elif args.scan:
        init_db()
        Config.ensure_directories()
        w = FolderWatcher(on_video_ready=agent_instance.on_video_detected)
        print("Scanning folder...")
        w.scan_once()
        print("Done.")
    else:
        run_web(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
