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
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
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
    log_event
)
from agent import agent_instance
from watcher import FolderWatcher
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


@app.on_event("startup")
async def startup_event():
    Config.ensure_directories()
    watcher_instance.start()
    log_event("SUCCESS", "System", "TubeAgent system started successfully.")


@app.on_event("shutdown")
async def shutdown_event():
    watcher_instance.stop()


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

    def oauth_worker():
        try:
            channel = youtube_uploader.run_oauth_flow(port=8088)
            agent_instance.events.emit("auth_success", channel)
        except Exception as e:
            log_event("ERROR", "YouTube", f"OAuth flow failed: {e}")
            agent_instance.events.emit("auth_error", {"error": str(e)})

    thread = threading.Thread(target=oauth_worker, daemon=True)
    thread.start()

    return {
        "status": "started",
        "message": "OAuth browser window opening. Complete sign-in with your YouTube account."
    }


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

    Config.ensure_directories()
    return {"status": "success", "message": "Settings updated"}


@app.post("/api/upload")
async def upload_direct_video(file: UploadFile = File(...)):
    """Allows dragging and dropping a video directly onto the web interface."""
    Config.ensure_directories()
    # Sanitize filename to prevent path traversal
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
            # Respond to ping
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
