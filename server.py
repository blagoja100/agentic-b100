"""
FastAPI Backend and WebSocket server for TubeAgent Web Dashboard.
"""

import os
import json
import asyncio
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import Config
from db import (
    init_db,
    get_all_videos,
    get_video_by_id,
    delete_video,
    update_video_metadata,
    get_recent_logs,
    log_event,
    get_all_cat_jobs,
    get_cat_job_by_id,
    delete_cat_job
)
from agent import agent_instance
from watcher import FolderWatcher
from cat_agent import cat_agent_instance
from cat_agent import gmail_monitor
from cat_agent.gmail_monitor import is_gmail_authenticated, run_gmail_oauth_flow, GMAIL_SCOPES
import youtube_uploader
import ai_generator

# Initialize database
init_db()

app = FastAPI(title="TubeAgent", description="Autonomous YouTube AI Agent & Watcher")

# Mount static files
static_dir = Config.BASE_DIR / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

templates_dir = Config.BASE_DIR / "templates"
templates_dir.mkdir(parents=True, exist_ok=True)

# Watcher instance
watcher_instance = FolderWatcher(on_video_ready=agent_instance.on_video_detected)

# Active WebSocket connections
active_connections: List[WebSocket] = []
loop = asyncio.get_event_loop()


class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active:
            self.active.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)


manager = ConnectionManager()


# Register agent event listener to broadcast over WebSocket
def broadcast_agent_event(event_data: dict):
    # Use loop.call_soon_threadsafe to schedule on the asyncio event loop
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if current_loop:
        asyncio.run_coroutine_threadsafe(manager.broadcast(event_data), current_loop)


agent_instance.events.subscribe(broadcast_agent_event)
cat_agent_instance.events.subscribe(broadcast_agent_event)


@app.on_event("startup")
async def startup_event():
    Config.ensure_directories()
    watcher_instance.start()
    enable_cat_poller = os.getenv("ENABLE_CAT_POLLER_IN_WEB", "true").lower() in ("true", "1", "yes")
    if enable_cat_poller:
        cat_agent_instance.start()
        log_event("SUCCESS", "System", "TubeAgent and CatAgent systems started successfully.")
    else:
        log_event("SUCCESS", "System", "TubeAgent web server started. (CatAgent background polling handled by dedicated service).")


@app.on_event("shutdown")
async def shutdown_event():
    watcher_instance.stop()
    if cat_agent_instance._running:
        cat_agent_instance.stop()


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = templates_dir / "index.html"
    if index_file.exists():
        with open(index_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>TubeAgent</h1><p>Dashboard is loading...</p>")


@app.get("/api/status")
async def get_system_status():
    videos = get_all_videos()
    channel = youtube_uploader.get_channel_info()
    
    total = len(videos)
    uploaded = len([v for v in videos if v["status"] == "uploaded"])
    pending = len([v for v in videos if v["status"] in ["detected", "analyzing", "review_ready", "uploading"]])
    failed = len([v for v in videos if v["status"] == "failed"])

    return {
        "watcher_running": watcher_instance._running,
        "watch_folder": str(Config.WATCH_FOLDER),
        "processed_folder": str(Config.PROCESSED_FOLDER),
        "auto_upload": Config.AUTO_UPLOAD,
        "default_privacy": Config.DEFAULT_PRIVACY,
        "has_gemini_key": bool(Config.GEMINI_API_KEY),
        "gemini_model": Config.GEMINI_MODEL,
        "channel": channel,
        "stats": {
            "total": total,
            "uploaded": uploaded,
            "pending": pending,
            "failed": failed
        }
    }


@app.get("/api/videos")
async def list_videos():
    return get_all_videos()


@app.get("/api/videos/{video_id}")
async def get_video(video_id: int):
    video = get_video_by_id(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


class VideoUpdateRequest(BaseModel):
    title: str
    description: str
    tags: str
    category_id: str
    privacy_status: str


@app.post("/api/videos/{video_id}/update")
async def update_video(video_id: int, req: VideoUpdateRequest):
    video = get_video_by_id(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    update_video_metadata(
        video_id=video_id,
        title=req.title,
        description=req.description,
        tags=req.tags,
        category_id=req.category_id,
        privacy_status=req.privacy_status
    )

    # Sync update to live YouTube video if already uploaded
    if video.get("youtube_video_id"):
        try:
            youtube_uploader.update_youtube_video_metadata(
                youtube_video_id=video["youtube_video_id"],
                title=req.title,
                description=req.description,
                tags=req.tags,
                category_id=req.category_id
            )
        except Exception as e:
            log_event("WARNING", "Server", f"Could not sync update to YouTube: {e}", video_id)

    updated = get_video_by_id(video_id)
    agent_instance.events.emit("video_updated", updated)
    return {"status": "success", "video": updated}


@app.post("/api/videos/{video_id}/regenerate")
async def regenerate_video_metadata(video_id: int):
    video = get_video_by_id(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    video_path = Path(video["filepath"])
    if not video_path.exists():
        candidates = [
            Config.WATCH_FOLDER / video["filename"],
            Config.PROCESSED_FOLDER / video["filename"],
            Config.FAILED_FOLDER / video["filename"],
        ]
        for c in candidates:
            if c.exists():
                video_path = c
                break

    log_event("INFO", "Agent", f"Regenerating metadata for video #{video_id} ('{video['filename']}')...", video_id)
    new_metadata = ai_generator.generate_video_metadata(video_path, video_id)

    update_video_metadata(
        video_id=video_id,
        title=new_metadata["title"],
        description=new_metadata["description"],
        tags=new_metadata["tags"],
        category_id=new_metadata["category_id"],
        privacy_status=video.get("privacy_status", Config.DEFAULT_PRIVACY)
    )

    # If already on YouTube, update live video
    if video.get("youtube_video_id"):
        try:
            youtube_uploader.update_youtube_video_metadata(
                youtube_video_id=video["youtube_video_id"],
                title=new_metadata["title"],
                description=new_metadata["description"],
                tags=new_metadata["tags"],
                category_id=new_metadata["category_id"]
            )
        except Exception as e:
            log_event("WARNING", "Server", f"Could not sync regenerated metadata to YouTube: {e}", video_id)

    updated = get_video_by_id(video_id)
    agent_instance.events.emit("video_updated", updated)
    return {"status": "success", "video": updated}


@app.post("/api/videos/{video_id}/approve")
async def approve_video(video_id: int):
    try:
        agent_instance.trigger_approval(video_id)
        return {"status": "success", "message": f"Upload triggered for video #{video_id}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/videos/{video_id}/retry")
async def retry_video(video_id: int):
    try:
        agent_instance.retry_pipeline(video_id)
        return {"status": "success", "message": f"Pipeline restarted for video #{video_id}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/videos/{video_id}")
async def remove_video(video_id: int):
    delete_video(video_id)
    agent_instance.events.emit("video_deleted", {"id": video_id})
    return {"status": "success", "message": f"Video #{video_id} deleted"}


@app.post("/api/scan")
async def scan_now():
    thread = threading.Thread(target=watcher_instance.scan_once, daemon=True)
    thread.start()
    return {"status": "success", "message": "Folder scan initiated"}


@app.get("/api/channel")
async def get_channel():
    return youtube_uploader.get_channel_info()


@app.post("/api/auth/start")
async def start_oauth_flow():
    if not Config.CLIENT_SECRETS_FILE.exists():
        raise HTTPException(
            status_code=400,
            detail="Missing client_secrets.json. Please upload your Google OAuth credentials first."
        )

    from oauth_manager import start_oauth_flow as start_unified_oauth

    def on_yt_success(creds, info):
        channel = youtube_uploader.get_channel_info()
        agent_instance.events.emit("auth_success", channel)

    def on_yt_error(err):
        agent_instance.events.emit("auth_error", {"error": str(err)})

    try:
        res = start_unified_oauth(
            service_name="YouTube",
            scopes=youtube_uploader.SCOPES,
            token_file=Config.TOKEN_FILE,
            on_success=on_yt_success,
            on_error=on_yt_error
        )
        return {
            "status": "ready",
            "auth_url": res["auth_url"],
            "port": res["port"],
            "message": "YouTube OAuth authorization initiated."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/auth/redirect")
async def youtube_auth_redirect():
    """Direct browser navigation link for YouTube OAuth that redirects directly to Google sign-in."""
    if not Config.CLIENT_SECRETS_FILE.exists():
        raise HTTPException(
            status_code=400,
            detail="Missing client_secrets.json. Please upload your Google OAuth credentials first."
        )

    from oauth_manager import start_oauth_flow as start_unified_oauth

    def on_yt_success(creds, info):
        channel = youtube_uploader.get_channel_info()
        agent_instance.events.emit("auth_success", channel)

    def on_yt_error(err):
        agent_instance.events.emit("auth_error", {"error": str(err)})

    try:
        res = start_unified_oauth(
            service_name="YouTube",
            scopes=youtube_uploader.SCOPES,
            token_file=Config.TOKEN_FILE,
            on_success=on_yt_success,
            on_error=on_yt_error
        )
        return RedirectResponse(url=res["auth_url"], status_code=303)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/auth/client-secrets")
async def upload_client_secrets(file: Optional[UploadFile] = File(None), raw_json: Optional[str] = Form(None)):
    try:
        content = ""
        if file:
            content = (await file.read()).decode("utf-8")
        elif raw_json:
            content = raw_json
        else:
            raise HTTPException(status_code=400, detail="No client secrets file or JSON provided.")

        data = json.loads(content)
        if "installed" not in data and "web" not in data:
            raise HTTPException(status_code=400, detail="Invalid Google OAuth client secrets format.")

        with open(Config.CLIENT_SECRETS_FILE, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2))

        log_event("SUCCESS", "System", "Saved client_secrets.json successfully.")
        return {"status": "success", "message": "Saved client_secrets.json"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to save credentials: {e}")


class SettingsUpdate(BaseModel):
    watch_folder: Optional[str] = None
    processed_folder: Optional[str] = None
    default_privacy: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    auto_upload: Optional[bool] = None
    cat_videos_folder: Optional[str] = None
    gmail_subject_prefix: Optional[str] = None
    gmail_poll_interval: Optional[int] = None
    veo_model: Optional[str] = None


@app.get("/api/settings")
async def get_settings():
    return {
        "watch_folder": str(Config.WATCH_FOLDER),
        "processed_folder": str(Config.PROCESSED_FOLDER),
        "default_privacy": Config.DEFAULT_PRIVACY,
        "gemini_api_key": "***" if Config.GEMINI_API_KEY else "",
        "gemini_model": Config.GEMINI_MODEL,
        "auto_upload": Config.AUTO_UPLOAD,
        "has_client_secrets": Config.CLIENT_SECRETS_FILE.exists(),
        "has_token": Config.TOKEN_FILE.exists(),
        "cat_videos_folder": str(Config.CAT_VIDEOS_FOLDER),
        "gmail_subject_prefix": Config.GMAIL_SUBJECT_PREFIX,
        "gmail_poll_interval": Config.GMAIL_POLL_INTERVAL_SECONDS,
        "veo_model": Config.VEO_MODEL,
        "has_gmail_token": Config.GMAIL_TOKEN_FILE.exists(),
    }


@app.post("/api/settings")
async def update_settings(settings: SettingsUpdate):
    if settings.watch_folder is not None:
        Config.update_setting("WATCH_FOLDER", settings.watch_folder)
    if settings.processed_folder is not None:
        Config.update_setting("PROCESSED_FOLDER", settings.processed_folder)
    if settings.default_privacy is not None:
        Config.update_setting("DEFAULT_PRIVACY", settings.default_privacy)
    if settings.gemini_api_key is not None and settings.gemini_api_key != "***":
        Config.update_setting("GEMINI_API_KEY", settings.gemini_api_key)
    if settings.gemini_model is not None:
        Config.update_setting("GEMINI_MODEL", settings.gemini_model)
    if settings.auto_upload is not None:
        Config.update_setting("AUTO_UPLOAD", str(settings.auto_upload).lower())
    if settings.cat_videos_folder is not None:
        Config.update_setting("CAT_VIDEOS_FOLDER", settings.cat_videos_folder)
    if settings.gmail_subject_prefix is not None:
        Config.update_setting("GMAIL_SUBJECT_PREFIX", settings.gmail_subject_prefix)
    if settings.gmail_poll_interval is not None:
        Config.update_setting("GMAIL_POLL_INTERVAL_SECONDS", str(settings.gmail_poll_interval))
    if settings.veo_model is not None:
        Config.update_setting("VEO_MODEL", settings.veo_model)

    Config.ensure_directories()
    return {"status": "success", "message": "Settings updated"}


# ==========================================
# Cat Explainer Agent API Endpoints
# ==========================================

class CatProcessUrlRequest(BaseModel):
    url: str
    title: Optional[str] = None


@app.get("/api/cat/status")
async def get_cat_status():
    is_auth, email_addr = is_gmail_authenticated()
    jobs = get_all_cat_jobs()
    completed = len([j for j in jobs if j.get("status") == "completed"])
    active = len([j for j in jobs if j.get("status") in ["detected", "downloading", "transcribing", "generating_video"]])
    failed = len([j for j in jobs if j.get("status") == "failed"])

    return {
        "gmail_authenticated": is_auth,
        "gmail_email": email_addr,
        "subject_prefix": Config.GMAIL_SUBJECT_PREFIX,
        "poll_interval": Config.GMAIL_POLL_INTERVAL_SECONDS,
        "veo_model": Config.VEO_MODEL,
        "cat_videos_folder": str(Config.CAT_VIDEOS_FOLDER),
        "agent_running": cat_agent_instance._running,
        "stats": {
            "total": len(jobs),
            "completed": completed,
            "active": active,
            "failed": failed
        }
    }


@app.get("/api/cat/jobs")
async def get_cat_jobs_endpoint():
    return get_all_cat_jobs(limit=100)


@app.post("/api/cat/check-now")
async def cat_check_now():
    """Manually checks Gmail inbox immediately."""
    new_jobs = cat_agent_instance.check_now()
    return {"status": "success", "jobs_found": len(new_jobs)}


@app.post("/api/cat/process-url")
async def cat_process_url(req: CatProcessUrlRequest):
    """Processes a video link directly from the UI without an email."""
    if not req.url:
        raise HTTPException(status_code=400, detail="Video URL is required")
    job_id = cat_agent_instance.process_url(url=req.url, title=req.title)
    return {"status": "success", "job_id": job_id}


@app.post("/api/cat/auth")
async def cat_auth_trigger():
    """Launches Gmail OAuth browser flow and returns the authorization URL."""
    if not Config.CLIENT_SECRETS_FILE.exists():
        raise HTTPException(
            status_code=400,
            detail="Missing client_secrets.json. Please upload your Google OAuth credentials first."
        )

    from oauth_manager import start_oauth_flow as start_unified_oauth

    def on_gmail_success(creds, info):
        agent_instance.events.emit("cat_auth_success", info)

    def on_gmail_error(err):
        agent_instance.events.emit("cat_auth_error", {"error": str(err)})

    try:
        res = start_unified_oauth(
            service_name="Gmail",
            scopes=gmail_monitor.GMAIL_SCOPES,
            token_file=Config.GMAIL_TOKEN_FILE,
            on_success=on_gmail_success,
            on_error=on_gmail_error
        )
        return {
            "status": "ready",
            "auth_url": res["auth_url"],
            "port": res["port"],
            "message": "Gmail OAuth authorization initiated."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/cat/auth/redirect")
async def cat_auth_redirect():
    """Direct browser navigation link for Gmail OAuth that redirects directly to Google sign-in."""
    if not Config.CLIENT_SECRETS_FILE.exists():
        raise HTTPException(
            status_code=400,
            detail="Missing client_secrets.json. Please upload your Google OAuth credentials first."
        )

    from oauth_manager import start_oauth_flow as start_unified_oauth

    def on_gmail_success(creds, info):
        agent_instance.events.emit("cat_auth_success", info)

    def on_gmail_error(err):
        agent_instance.events.emit("cat_auth_error", {"error": str(err)})

    try:
        res = start_unified_oauth(
            service_name="Gmail",
            scopes=gmail_monitor.GMAIL_SCOPES,
            token_file=Config.GMAIL_TOKEN_FILE,
            on_success=on_gmail_success,
            on_error=on_gmail_error
        )
        return RedirectResponse(url=res["auth_url"], status_code=303)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/cat/video/{job_id}")
async def serve_cat_video(job_id: int):
    """Streams the generated cat video MP4 file."""
    job = get_cat_job_by_id(job_id)
    if not job or not job.get("generated_video_path"):
        raise HTTPException(status_code=404, detail="Video file not found")
    p = Path(job["generated_video_path"])
    if not p.exists():
        raise HTTPException(status_code=404, detail="Video file does not exist on disk")
    return FileResponse(p, media_type="video/mp4", filename=p.name)


@app.delete("/api/cat/jobs/{job_id}")
async def remove_cat_job(job_id: int):
    """Deletes a cat job and its generated video file."""
    job = get_cat_job_by_id(job_id)
    if job:
        if job.get("generated_video_path"):
            try:
                p = Path(job["generated_video_path"])
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        delete_cat_job(job_id)
    return {"status": "success", "message": f"Cat job #{job_id} deleted"}


@app.post("/api/upload")
async def upload_direct_video(file: UploadFile = File(...)):
    """Allows dragging and dropping a video directly onto the web interface."""
    Config.ensure_directories()
    safe_filename = Path(file.filename).name
    if not safe_filename or safe_filename.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = Config.WATCH_FOLDER / safe_filename

    with open(file_path, "wb") as f:
        while chunk := await file.read(1024 * 1024 * 5):
            f.write(chunk)

    log_event("INFO", "Web", f"Uploaded video file '{safe_filename}' directly via web dashboard.")
    return {"status": "success", "filename": safe_filename, "path": str(file_path)}


@app.get("/api/logs")
async def get_logs(limit: int = 50):
    return get_recent_logs(limit)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
