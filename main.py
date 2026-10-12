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
from typing import Optional

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

    # CatAgent status
    from db import get_all_cat_jobs
    from cat_agent.gmail_monitor import is_gmail_authenticated
    cat_jobs = get_all_cat_jobs()
    is_gmail_auth, gmail_email = is_gmail_authenticated()
    print("\n[CatAgent (Be100 Gmail Explainer)]")
    print(f"Gmail Account:      {gmail_email if is_gmail_auth else 'Not connected'}")
    print(f"Subject Matcher:    {Config.GMAIL_SUBJECT_PREFIX} [title]")
    print(f"Veo Model:          {Config.VEO_MODEL}")
    print(f"Cat Videos Folder:  {Config.CAT_VIDEOS_FOLDER}")
    print(f"Cat Video Jobs:     {len(cat_jobs)} total")
    for j in cat_jobs[:5]:
        print(f" - #{j['id']} [{j['status']}] {j.get('title')} -> {j.get('generated_video_path') or j.get('source_url')}")
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


def run_cat_daemon():
    """Runs Cat Explainer Agent as a headless background terminal daemon."""
    init_db()
    Config.ensure_directories()
    from cat_agent import cat_agent_instance
    from cat_agent.gmail_monitor import is_gmail_authenticated

    print("\n" + "=" * 60)
    print("🐱 CatAgent Running in Headless Daemon Mode")
    print(f"📧 Gmail Subject Prefix: '{Config.GMAIL_SUBJECT_PREFIX}'")
    print(f"⏱️ Poll Interval:        {Config.GMAIL_POLL_INTERVAL_SECONDS}s")
    print(f"🎬 Video Model:           {Config.VEO_MODEL}")
    print(f"📁 Output Folder:         {Config.CAT_VIDEOS_FOLDER}")
    
    is_auth, email_addr = is_gmail_authenticated()
    if is_auth:
        print(f"🔑 Gmail Auth:            Connected as {email_addr} ✓")
    else:
        print("⚠️ Gmail Auth:            Not connected. Run 'python main.py --cat-auth' to authenticate.")
    print("=" * 60 + "\n")

    cat_agent_instance.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping CatAgent daemon...")
        cat_agent_instance.stop()
        print("CatAgent stopped gracefully.")


def run_cat_auth_cli():
    """Interactive Gmail OAuth setup in CLI."""
    init_db()
    Config.ensure_directories()
    from cat_agent.gmail_monitor import run_gmail_oauth_flow
    print("\n" + "=" * 60)
    print("📧 Gmail Account OAuth Setup for CatAgent")
    print("=" * 60)
    print("Launching browser for Gmail permissions...")
    try:
        res = run_gmail_oauth_flow(port=8089)
        print(f"\n✅ Authenticated successfully with Gmail: {res.get('email')}")
    except Exception as e:
        print(f"\n❌ Gmail authentication failed: {e}")


def run_cat_check_cli():
    """Performs a single Gmail inbox poll and processes matching emails."""
    init_db()
    Config.ensure_directories()
    from cat_agent import cat_agent_instance
    print("Checking Gmail inbox for 'Be100 Prod:' emails...")
    jobs = cat_agent_instance.check_now()
    if jobs:
        print(f"✅ Found and launched {len(jobs)} jobs:")
        for j in jobs:
            print(f" - #{j['id']} [{j['status']}] {j.get('title')} -> {j.get('source_url')}")
    else:
        print("No new matching emails found.")


def run_cat_test_cli(url: str, title: Optional[str] = None):
    """Downloads a video link and generates a 10s cat video explainer."""
    init_db()
    Config.ensure_directories()
    from cat_agent import cat_agent_instance
    print(f"\n🚀 Testing CatAgent pipeline for URL: {url}")
    job_id = cat_agent_instance.process_url(url=url, title=title)
    print(f"Launched Job #{job_id}. Processing in background...")
    
    # Wait for completion
    from db import get_cat_job_by_id
    while True:
        job = get_cat_job_by_id(job_id)
        status = job.get("status")
        progress = job.get("progress", 0)
        print(f"\rStatus: [{status}] {progress}%...", end="", flush=True)
        if status in ["completed", "failed"]:
            print()
            if status == "completed":
                print(f"✅ Generated Cat Video: {job.get('generated_video_path')}")
                print(f"🗣️ Cat Script: {job.get('cat_script')}")
            else:
                print(f"❌ Failed: {job.get('error_message')}")
            break
        time.sleep(2)


def main():
    parser = argparse.ArgumentParser(description="TubeAgent & CatAgent - Autonomous AI Agents")
    parser.add_argument("--web", action="store_true", help="Start Web Dashboard (Default)")
    parser.add_argument("--daemon", action="store_true", help="Run TubeAgent in headless terminal daemon mode")
    parser.add_argument("--auth", action="store_true", help="Run YouTube OAuth setup wizard")
    parser.add_argument("--status", action="store_true", help="Show system status and channel details")
    parser.add_argument("--scan", action="store_true", help="Perform a single folder scan")
    parser.add_argument("--create-test-video", action="store_true", help="Generate a sample test video in the watch folder")
    parser.add_argument("--port", type=int, default=8000, help="Web dashboard port")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Web dashboard host")

    # CatAgent CLI arguments
    parser.add_argument("--cat-agent", action="store_true", help="Run Cat Explainer Agent daemon")
    parser.add_argument("--cat-auth", action="store_true", help="Authenticate Gmail account for CatAgent")
    parser.add_argument("--cat-check", action="store_true", help="Check Gmail inbox once for Be100 emails")
    parser.add_argument("--cat-test", type=str, help="Directly test video URL with CatAgent pipeline")
    parser.add_argument("--title", type=str, help="Title to accompany --cat-test")

    args = parser.parse_args()

    if args.cat_agent:
        run_cat_daemon()
    elif args.cat_auth:
        run_cat_auth_cli()
    elif args.cat_check:
        run_cat_check_cli()
    elif args.cat_test:
        run_cat_test_cli(args.cat_test, args.title)
    elif args.daemon:
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
