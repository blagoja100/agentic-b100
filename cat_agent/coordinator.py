"""
Cat Agent Coordinator.
Orchestrates the autonomous lifecycle:
Gmail Polling -> Video Downloading -> Gemini Transcribing & Cat Scripting -> Veo Generation -> Local File Archival.
"""

import os
import time
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable

from config import Config
from db import (
    log_event,
    add_cat_job,
    update_cat_job,
    get_cat_job_by_id,
    get_cat_job_by_email_id,
    get_all_cat_jobs
)
from .gmail_monitor import (
    search_for_be100_emails,
    mark_email_as_read,
    is_gmail_authenticated
)
from .video_downloader import download_short_video, cleanup_temp_video
from .script_generator import generate_cat_explanation
from .veo_generator import generate_veo_cat_video


class CatEventEmitter:
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


class CatAgent:
    def __init__(self):
        self.events = CatEventEmitter()
        self._running: bool = False
        self._poll_thread: Optional[threading.Thread] = None
        self._active_jobs: Dict[int, threading.Thread] = {}

    def start(self):
        """Starts background Gmail polling thread."""
        if self._running:
            return
        self._running = True
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        log_event("SUCCESS", "CatAgent", "Be100 Gmail Cat Explainer Agent started.")

    def stop(self):
        """Stops background Gmail polling."""
        self._running = False
        log_event("INFO", "CatAgent", "Cat Explainer Agent stopped.")

    def _poll_loop(self):
        """Continuous polling loop."""
        while self._running:
            try:
                self.check_now()
            except Exception as e:
                log_event("ERROR", "CatAgent", f"Error during polling cycle: {e}")
            
            # Sleep in 1-second chunks for clean shutdown
            interval = max(5, Config.GMAIL_POLL_INTERVAL_SECONDS)
            for _ in range(interval):
                if not self._running:
                    break
                time.sleep(1)

    def check_now(self) -> List[Dict[str, Any]]:
        """
        Manually checks Gmail inbox for Be100 emails and starts processing them.
        Returns list of newly discovered jobs.
        """
        is_auth, email_addr = is_gmail_authenticated()
        if not is_auth:
            return []

        emails = search_for_be100_emails(only_unread=Config.GMAIL_AUTO_MARK_READ)
        new_jobs = []

        for item in emails:
            email_id = item["email_id"]
            existing = get_cat_job_by_email_id(email_id)
            if existing:
                continue

            log_event("INFO", "CatAgent", f"Discovered Be100 email: '{item['subject']}' with link: {item['video_url']}")
            
            job_id = self.process_url(
                url=item["video_url"],
                title=item["title"],
                email_id=email_id,
                email_subject=item["subject"],
                email_sender=item["sender"],
                video_platform=item["platform"]
            )

            # Mark email as read so it isn't repeatedly ingested
            if Config.GMAIL_AUTO_MARK_READ:
                mark_email_as_read(email_id)

            new_jobs.append(get_cat_job_by_id(job_id))

        return new_jobs

    def process_url(
        self,
        url: str,
        title: Optional[str] = None,
        email_id: Optional[str] = None,
        email_subject: Optional[str] = None,
        email_sender: Optional[str] = None,
        video_platform: Optional[str] = None
    ) -> int:
        """
        Enqueues and launches end-to-end cat video pipeline for a given URL.
        Can be called by Gmail watcher or directly from the UI / CLI.
        """
        clean_title = title or "Short Explainer"
        
        job_id = add_cat_job(
            source_url=url,
            title=clean_title,
            email_id=email_id,
            email_subject=email_subject or f"Manual: {clean_title}",
            email_sender=email_sender or "User",
            video_platform=video_platform or "web",
            status="detected"
        )

        job_data = get_cat_job_by_id(job_id)
        self.events.emit("cat_job_created", job_data)
        log_event("INFO", "CatAgent", f"Enqueued Cat Video Job #{job_id}: '{clean_title}'", job_id)

        # Launch pipeline in background thread
        thread = threading.Thread(
            target=self._run_pipeline,
            args=(job_id, url, clean_title),
            daemon=True
        )
        self._active_jobs[job_id] = thread
        thread.start()

        return job_id

    def _run_pipeline(self, job_id: int, url: str, title: str):
        downloaded_path = None
        try:
            # Step 1: Download Video
            update_cat_job(job_id, status="downloading", progress=15)
            self.events.emit("cat_job_updated", get_cat_job_by_id(job_id))
            log_event("INFO", "CatAgent", f"Downloading source video from {url}...", job_id)

            dl_result = download_short_video(url, job_id=job_id)
            if not dl_result.get("success"):
                raise RuntimeError(dl_result.get("error", "Download failed"))

            downloaded_path = dl_result.get("filepath")
            actual_title = dl_result.get("title") or title
            update_cat_job(
                job_id,
                title=actual_title,
                downloaded_video_path=str(downloaded_path) if downloaded_path else None,
                progress=35
            )

            # Step 2: Gemini Analysis & Cat Script
            update_cat_job(job_id, status="transcribing", progress=45)
            self.events.emit("cat_job_updated", get_cat_job_by_id(job_id))
            log_event("INFO", "CatAgent", "Analyzing video dialogue & generating 10s cat script...", job_id)

            script_data = generate_cat_explanation(
                video_path=downloaded_path,
                title=actual_title,
                job_id=job_id
            )

            cat_script = script_data.get("cat_script", "")
            transcription = script_data.get("transcription", "")
            veo_prompt = script_data.get("veo_prompt", "")

            update_cat_job(
                job_id,
                transcription_text=transcription,
                cat_script=cat_script,
                video_prompt=veo_prompt,
                progress=65
            )

            # Step 3: Google Veo / Cat Video Generation
            update_cat_job(job_id, status="generating_video", progress=70)
            self.events.emit("cat_job_updated", get_cat_job_by_id(job_id))
            log_event("INFO", "CatAgent", "Rendering 10-second cat explainer video...", job_id)

            gen_result = generate_veo_cat_video(
                prompt=veo_prompt,
                script_text=cat_script,
                title=actual_title,
                job_id=job_id
            )

            if not gen_result.get("success"):
                raise RuntimeError(gen_result.get("error", "Video generation failed"))

            final_video_path = gen_result.get("filepath")

            # Step 4: Completion & Archival
            update_cat_job(
                job_id,
                status="completed",
                progress=100,
                generated_video_path=str(final_video_path),
                completed_at=time.strftime("%Y-%m-%d %H:%M:%S")
            )
            completed_job = get_cat_job_by_id(job_id)
            self.events.emit("cat_job_completed", completed_job)
            log_event("SUCCESS", "CatAgent", f"Cat Explainer Video #{job_id} successfully created: '{Path(final_video_path).name}'", job_id)

        except Exception as err:
            err_msg = str(err)
            log_event("ERROR", "CatAgent", f"Job #{job_id} failed: {err_msg}", job_id)
            update_cat_job(job_id, status="failed", error_message=err_msg)
            self.events.emit("cat_job_failed", get_cat_job_by_id(job_id))

        finally:
            # Clean up intermediate downloaded short video to save space
            if downloaded_path:
                cleanup_temp_video(downloaded_path)


cat_agent_instance = CatAgent()
