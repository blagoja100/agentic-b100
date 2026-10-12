"""
Core AI Agent Coordinator.
Manages the end-to-end lifecycle:
Detection -> Gemini AI Analysis -> Approval / Auto-Upload -> YouTube Upload -> File Archival.
"""

import os
import shutil
import asyncio
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable

from config import Config
from db import (
    log_event,
    get_video_by_path,
    get_video_by_id,
    get_all_videos,
    add_video,
    update_video_status,
    update_video_metadata,
    update_video_progress,
    mark_video_uploaded
)
import ai_generator
import youtube_uploader


class AgentEventEmitter:
    def __init__(self):
        self.subscribers: List[Callable[[Dict[str, Any]], None]] = []

    def subscribe(self, callback: Callable[[Dict[str, Any]], None]):
        if callback not in self.subscribers:
            self.subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[Dict[str, Any]], None]):
        if callback in self.subscribers:
            self.subscribers.remove(callback)

    def emit(self, event_type: str, data: Any):
        payload = {"event": event_type, "data": data}
        for cb in list(self.subscribers):
            try:
                cb(payload)
            except Exception:
                pass


class TubeAgent:
    def __init__(self):
        self.events = AgentEventEmitter()
        self._active_jobs: Dict[int, threading.Thread] = {}

    def on_video_detected(self, video_path: Path):
        """Called by the folder watcher when a stable video file is found."""
        path_str = str(video_path.resolve())
        record = get_video_by_path(path_str)

        if record:
            status = record.get("status")
            if status in ["uploaded", "analyzing", "uploading"]:
                # Already processed or currently processing
                return
            video_id = record["id"]
        else:
            filesize = video_path.stat().st_size
            video_id = add_video(
                filepath=path_str,
                filename=video_path.name,
                filesize=filesize,
                status="detected"
            )
            log_event("INFO", "Agent", f"Registered new video job #{video_id}: '{video_path.name}'", video_id)
            self.events.emit("video_created", get_video_by_id(video_id))

        # Launch processing pipeline in background worker
        self._dispatch_processing(video_id, video_path)

    def _dispatch_processing(self, video_id: int, video_path: Path):
        if video_id in self._active_jobs and self._active_jobs[video_id].is_alive():
            return

        thread = threading.Thread(
            target=self._run_pipeline,
            args=(video_id, video_path),
            daemon=True
        )
        self._active_jobs[video_id] = thread
        thread.start()

    def _run_pipeline(self, video_id: int, video_path: Path):
        try:
            # 1. AI Analysis Phase
            update_video_status(video_id, "analyzing")
            self.events.emit("video_updated", get_video_by_id(video_id))
            log_event("INFO", "Agent", f"Analyzing video #{video_id} ('{video_path.name}') with Gemini AI...", video_id)

            metadata = ai_generator.generate_video_metadata(video_path, video_id)

            update_video_metadata(
                video_id=video_id,
                title=metadata["title"],
                description=metadata["description"],
                tags=metadata["tags"],
                category_id=metadata["category_id"],
                privacy_status=metadata["privacy_status"]
            )

            # 2. Upload Decision Phase
            if Config.AUTO_UPLOAD:
                log_event("INFO", "Agent", f"Auto-upload enabled. Initiating YouTube upload for #{video_id}...", video_id)
                self._execute_upload(video_id, video_path, metadata)
            else:
                update_video_status(video_id, "review_ready")
                log_event("SUCCESS", "Agent", f"Video #{video_id} is ready for review in dashboard before upload.", video_id)
                self.events.emit("video_updated", get_video_by_id(video_id))

        except Exception as e:
            update_video_status(video_id, "failed", str(e))
            log_event("ERROR", "Agent", f"Pipeline failed for video #{video_id}: {e}", video_id)
            self.events.emit("video_updated", get_video_by_id(video_id))

    def _execute_upload(self, video_id: int, video_path: Path, metadata: Dict[str, Any]):
        """Executes the YouTube upload and moves file to processed folder on success."""
        # Check authentication first
        channel_info = youtube_uploader.get_channel_info()
        if not channel_info.get("authenticated"):
            err_msg = "YouTube account is not connected. Authenticate in dashboard or CLI."
            update_video_status(video_id, "failed", err_msg)
            log_event("WARNING", "Agent", f"Cannot upload #{video_id}: {err_msg}", video_id)
            self.events.emit("video_updated", get_video_by_id(video_id))
            return

        update_video_status(video_id, "uploading")
        self.events.emit("video_updated", get_video_by_id(video_id))

        def progress_cb(percent: int, bytes_uploaded: int, total_bytes: int):
            update_video_progress(video_id, percent)
            self.events.emit("upload_progress", {
                "id": video_id,
                "progress": percent,
                "bytes_uploaded": bytes_uploaded,
                "total_bytes": total_bytes
            })

        try:
            result = youtube_uploader.upload_video_to_youtube(
                video_path=video_path,
                title=metadata["title"],
                description=metadata["description"],
                tags=metadata["tags"],
                category_id=metadata["category_id"],
                privacy_status=metadata.get("privacy_status", Config.DEFAULT_PRIVACY),
                progress_callback=progress_cb,
                video_id_record=video_id
            )

            youtube_id = result["video_id"]
            youtube_url = result["youtube_url"]
            mark_video_uploaded(video_id, youtube_id, youtube_url)

            # Move file to processed folder
            self._archive_file(video_id, video_path)

            self.events.emit("video_updated", get_video_by_id(video_id))
            log_event("SUCCESS", "Agent", f"Successfully completed job for #{video_id}! Link: {youtube_url}", video_id)

        except Exception as e:
            update_video_status(video_id, "failed", str(e))
            log_event("ERROR", "Agent", f"Upload failed for video #{video_id}: {e}", video_id)
            self.events.emit("video_updated", get_video_by_id(video_id))

    def _archive_file(self, video_id: int, original_path: Path):
        """Moves video file and any sidecar notes to PROCESSED_FOLDER."""
        try:
            Config.PROCESSED_FOLDER.mkdir(parents=True, exist_ok=True)
            target_path = Config.PROCESSED_FOLDER / original_path.name
            
            # If target exists, add counter
            counter = 1
            while target_path.exists():
                target_path = Config.PROCESSED_FOLDER / f"{original_path.stem}_{counter}{original_path.suffix}"
                counter += 1

            shutil.move(str(original_path), str(target_path))
            
            # Also move sidecar notes if present
            for ext in [".txt", ".notes", ".json"]:
                sidecar = original_path.with_suffix(ext)
                if sidecar.exists():
                    target_sidecar = target_path.with_suffix(ext)
                    shutil.move(str(sidecar), str(target_sidecar))

            # Update DB with new filepath
            from db import get_db_connection
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE videos SET filepath = ? WHERE id = ?", (str(target_path.resolve()), video_id))
                conn.commit()

            log_event("INFO", "Agent", f"Moved completed file to '{target_path.name}' in processed folder.", video_id)
        except Exception as e:
            log_event("WARNING", "Agent", f"Could not move file to processed folder: {e}", video_id)

    def trigger_approval(self, video_id: int):
        """Manually approve and trigger upload for a video."""
        record = get_video_by_id(video_id)
        if not record:
            raise ValueError(f"Video #{video_id} not found.")

        video_path = Path(record["filepath"])
        if not video_path.exists():
            raise FileNotFoundError(f"Video file missing at '{video_path}'")

        metadata = {
            "title": record.get("title") or video_path.stem,
            "description": record.get("description") or "",
            "tags": record.get("tags") or "",
            "category_id": record.get("category_id") or Config.DEFAULT_CATEGORY_ID,
            "privacy_status": record.get("privacy_status") or Config.DEFAULT_PRIVACY
        }

        thread = threading.Thread(
            target=self._execute_upload,
            args=(video_id, video_path, metadata),
            daemon=True
        )
        self._active_jobs[video_id] = thread
        thread.start()

    def retry_pipeline(self, video_id: int):
        """Re-runs the entire pipeline from analysis to upload."""
        record = get_video_by_id(video_id)
        if not record:
            raise ValueError(f"Video #{video_id} not found.")

        video_path = Path(record["filepath"])
        if not video_path.exists():
            raise FileNotFoundError(f"Video file missing at '{video_path}'")

        self._dispatch_processing(video_id, video_path)


# Singleton agent instance
agent_instance = TubeAgent()
