# 🎬 TubeAgent - Autonomous YouTube Video AI Agent

**TubeAgent** is an autonomous AI agent designed to monitor a local folder for newly exported video files, analyze their multimodal content with **Google Gemini AI**, generate high-CTR titles, SEO-optimized descriptions, tags, and chapters, and upload them directly to your specified **YouTube Channel** via the YouTube Data API v3.

---

## ✨ Key Features

- 📁 **Safe Folder Ingestion**: Automatically watches any designated inbox folder for videos (`.mp4`, `.mov`, `.mkv`, `.avi`, `.webm`). Employs a file stability lock to avoid processing files while they are still being written or exported by video editors.
- 🧠 **Gemini Multimodal Intelligence**: Inspects video frames/audio and companion creator notes (`.txt`/`.notes`) to produce:
  - High-CTR, engaging YouTube Titles (< 100 chars).
  - SEO-rich YouTube Descriptions with overview, key moments/timestamps, hashtags, and social links.
  - 10–15 targeted keyword tags.
  - Optimal YouTube category selection (e.g., Tech, Education, Entertainment).
- 🔒 **Privacy-First Uploads**: Default privacy is set to **Private**, allowing you to verify the video in YouTube Studio before going live (with options for **Unlisted** and **Public**).
- 📺 **Specific Channel Authentication**: Full OAuth 2.0 integration allowing you to bind to any specific YouTube channel, displaying channel avatars, subscriber counts, and video stats in real time.
- ⚡ **Resumable Chunked Uploads**: High-reliability upload engine with exponential backoff for large 4K / 1080p files.
- 🎛️ **Modern Dark-Mode Web Dashboard**:
  - Live status cards (Channel, Watcher, Gemini).
  - Drag-and-drop dropzone for direct browser ingestion.
  - Video queue with real-time progress bars and live logs.
  - Interactive metadata review & approval modal.
  - Autopilot Mode vs. Review Mode switch.

---

## 🚀 Quick Start Guide

### 1. Environment Setup

If not already created, install dependencies:
```bash
uv pip install -r requirements.txt
# or:
pip install -r requirements.txt
```

### 2. Configure Credentials

#### A. YouTube OAuth (`client_secrets.json`):
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project or select an existing one.
3. Enable the **YouTube Data API v3** under **APIs & Services > Library**.
4. Go to **APIs & Services > Credentials**:
   - Configure the **OAuth Consent Screen** (User Type: External, add `https://www.googleapis.com/auth/youtube.upload` scope, and add your Google email as a Test User).
   - Click **Create Credentials > OAuth client ID**.
   - Choose Application type: **Desktop App**.
5. Download the JSON credential file and name it `client_secrets.json` in this workspace root (or upload it directly via the Web Dashboard).

#### B. Google Gemini API Key:
1. Obtain a free API key at [Google AI Studio](https://aistudio.google.com/apikey).
2. Enter it into `.env` as `GEMINI_API_KEY=AIzaSy...` or configure it via the Web Dashboard Settings dialog.

---

## 🐳 Running with Docker (Recommended)

You can run TubeAgent completely containerized while having it watch any folder on your laptop:

### 1. Configure Your Laptop's Folder in [`.env`](file:///c:/Users/blago/Dev/agentic-b100/.env)
Open [`.env`](file:///c:/Users/blago/Dev/agentic-b100/.env) and set `LOCAL_WATCH_FOLDER` to any folder on your laptop:
```env
# Example 1: Use a folder in your workspace (default)
LOCAL_WATCH_FOLDER=./watch_folder
LOCAL_PROCESSED_FOLDER=./processed_folder

# Example 2: Use your Windows Videos folder:
# LOCAL_WATCH_FOLDER=C:/Users/blago/Videos/YouTube_Inbox
# LOCAL_PROCESSED_FOLDER=C:/Users/blago/Videos/YouTube_Processed

# Gemini API Key (optional for AI generation)
GEMINI_API_KEY=your_gemini_api_key_here
```

### 2. Start the Docker Container
```bash
docker compose up -d
```
The container will build and start in the background.

### 3. Open the Dashboard
Navigate to: **[http://localhost:8000](http://localhost:8000)**

### 4. Useful Docker Commands
```bash
# View live container logs & watcher events
docker compose logs -f

# Check container status & health
docker compose ps

# Stop the container
docker compose down

# Restart container after changing .env
docker compose restart
```

---

## 💻 Running Directly with Python (Without Docker)

### Mode 2: Headless Daemon (Background Service)
```bash
.venv\Scripts\python main.py --daemon
```
Runs continuously in the terminal, monitoring the watch folder and executing the agent pipeline.

### Mode 3: CLI OAuth Wizard
```bash
.venv\Scripts\python main.py --auth
```
Launches the browser authentication flow directly from the terminal to link your YouTube channel.

### Mode 4: System Status Check
```bash
.venv\Scripts\python main.py --status
```

---

## 📁 Directory Structure

```
agentic-b100/
├── config.py                 # Configuration manager (.env persistence)
├── db.py                     # SQLite job tracking and event logs
├── ai_generator.py           # Gemini multimodal metadata generator
├── youtube_uploader.py       # YouTube Data API v3 OAuth & resumable uploader
├── watcher.py                # Safe folder monitoring & stability checks
├── agent.py                  # Workflow coordinator & event dispatcher
├── server.py                 # FastAPI backend & WebSocket server
├── main.py                   # Unified CLI entrypoint
├── templates/index.html      # Glassmorphic web dashboard
├── static/css/style.css      # Dark-mode design system
├── static/js/app.js          # Reactive dashboard frontend
├── watch_folder/             # Drop videos here
├── processed_folder/         # Completed videos are moved here
└── client_secrets.json       # (User-provided) Google OAuth credentials
```

---

## 🛠️ Companion Creator Notes (Optional)
You can drop a `.txt` file with the same name as the video into `watch_folder/` (for example, `MyTutorial.mp4` and `MyTutorial.txt`). The agent will incorporate your notes, prompts, or custom instructions directly into Gemini's prompt!
