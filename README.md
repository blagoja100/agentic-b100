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

You can run **TubeAgent** and **CatAgent** completely containerized while having both agents watch and save to folders on your laptop:

### 1. Configure Your Laptop's Folders in [`.env`](file:///c:/Users/blago/Dev/agentic-b100/.env)
Open [`.env`](file:///c:/Users/blago/Dev/agentic-b100/.env) and set your local folders:
```env
# Laptop folders:
LOCAL_WATCH_FOLDER=C:\Users\blago\Run\watch_folder
LOCAL_PROCESSED_FOLDER=C:\Users\blago\Run\processed_folder
LOCAL_DATA_FOLDER=C:\Users\blago\Run\data
LOCAL_CAT_VIDEOS_FOLDER=C:\Users\blago\Run\cat_videos

# Gemini API Key (for multimodal understanding & Veo cat video generation)
GEMINI_API_KEY=your_gemini_api_key_here
```

### 2. Start the Docker Services
```bash
docker compose up -d
```
Docker Compose will launch both services in the background:
- 🎬 `tubeagent`: Web Dashboard, YouTube uploader, folder watcher (Ports `8000`, `8088`, `8089`).
- 🐱 `cat-agent`: Autonomous Gmail inbox monitor & 10-second cat video generator daemon.

### 3. Open the Dashboard
Navigate to: **[http://localhost:8000](http://localhost:8000)**

### 4. Useful Docker Commands
```bash
# View live logs for both agents
docker compose logs -f

# View live logs for CatAgent specifically
docker compose logs -f cat-agent

# View live logs for TubeAgent web & folder watcher
docker compose logs -f tubeagent

# Check container status & health
docker compose ps

# Restart containers after changing .env
docker compose restart

# Stop the containers
docker compose down
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

## 🐱 CatAgent - Autonomous Be100 Gmail & Cat Video Generator

**CatAgent** is the second autonomous AI agent in the system. It connects to your Gmail inbox via OAuth 2.0, listens for production requests, extracts video links from social platforms, and creates a 10-second video of an expressive talking cat explaining whatever was said in the video, saved directly to a local folder!

### 🌟 How CatAgent Works

1. 📧 **Gmail Monitor**:
   - Searches your Gmail inbox for emails with subjects matching:
     ```
     Be100 Prod: [title]
     ```
   - Automatically extracts video links from email bodies (plain text & HTML):
     - **Instagram**: Reels & Posts (`instagram.com/reel/...`)
     - **Facebook**: Shorts & Reels (`facebook.com/reel/...`, `fb.watch/...`)
     - **YouTube**: Shorts & Videos (`youtube.com/shorts/...`, `youtu.be/...`)
   - Marks processed emails as read so they are not ingested twice.

2. 🧠 **Gemini Multimodal Analysis**:
   - Downloads the short video using `yt-dlp`.
   - Transcribes and summarizes the core dialogue, message, and events.
   - Generates an energetic **10-second cat explanation script** (~25 to 35 words) delivered from the perspective of a witty, charming cat.
   - Generates a cinematic photorealistic prompt for Google Veo 2.0.

3. 🎬 **10-Second Cat Video Generation (Google Veo 2.0)**:
   - Calls Google Veo (`veo-2.0-generate-001`) via `google-genai` SDK in vertical 9:16 format.
   - Includes an automated local Talking Cat Synthesizer (gTTS / pyttsx3 cat voiceover + cat avatar portrait + FFmpeg) fallback for instant resilience.

4. 💾 **Local Folder Storage**:
   - Saves the final generated 10-second MP4 video directly to your local folder:
     ```
     ./cat_videos/Be100_Cat_[Title]_[Timestamp].mp4
     ```

---

### 💻 Running CatAgent

#### 1. Web Dashboard (Unified UI)
Run the web dashboard:
```bash
python main.py
```
Click on the **🐱 CatAgent (Be100 Gmail Explainer)** tab in the header. From the UI you can:
- View live Gmail connection status.
- Trigger an immediate inbox scan with **Check Now**.
- Test any Instagram/Facebook/YouTube link instantly via the **Manual / Quick Video Ingestion** box.
- Preview and play generated 10-second cat videos directly in your browser with interactive script balloons!
- Download or delete generated videos.

#### 2. Headless Terminal Daemon
```bash
python main.py --cat-agent
```
Continuously polls Gmail in the background and runs the pipeline autonomously.

#### 3. Gmail OAuth Setup Wizard
```bash
python main.py --cat-auth
```
Launches your browser to grant Gmail read/modify access using your `client_secrets.json`.

#### 4. Test Single Video URL (CLI)
```bash
python main.py --cat-test "https://www.youtube.com/shorts/YOUR_SHORT_ID" --title "Coding Tips"
```

#### 5. Check Inbox Once
```bash
python main.py --cat-check
```

---

## 🛠️ Companion Creator Notes (Optional)
You can drop a `.txt` file with the same name as the video into `watch_folder/` (for example, `MyTutorial.mp4` and `MyTutorial.txt`). The agent will incorporate your notes, prompts, or custom instructions directly into Gemini's prompt!
