"""
Folder Watcher module using Watchdog and polling fallback.
Safely detects new video files once file writing/copying has completed.
"""

import time
import shutil
import threading
from pathlib import Path
from typing import Callable, Optional, Set
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from config import Config
from db import log_event, get_video_by_path, add_video


def is_file_stable(file_path: Path, check_seconds: int = 3) -> bool:
    """
    Checks if a file has finished being written by comparing file sizes over an interval
    and checking if the file can be opened.
    """
    if not file_path.exists() or not file_path.is_file():
        return False

    try:
        size1 = file_path.stat().st_size
        if size1 == 0:
            return False
            
        time.sleep(check_seconds)
        
        if not file_path.exists():
            return False
            
        size2 = file_path.stat().st_size
        if size1 != size2:
            return False

        # Attempt to open file for read
        with open(file_path, "rb") as f:
            f.read(1024)
        return True
    except (PermissionError, OSError):
        return False


class VideoFolderHandler(FileSystemEventHandler):
    def __init__(self, on_video_ready: Callable[[Path], None]):
        super().__init__()
        self.on_video_ready = on_video_ready
        self.processing_paths: Set[str] = set()

    def process_file_candidate(self, file_path: Path):
        path_str = str(file_path.resolve())
        if path_str in self.processing_paths:
            return

        if file_path.suffix.lower() not in Config.SUPPORTED_EXTENSIONS:
            return

        self.processing_paths.add(path_str)

        def worker():
            try:
                log_event("INFO", "Watcher", f"Detected potential video file: {file_path.name}. Checking stability...")
                
                # Retry stability check up to 10 times
                stable = False
                for _ in range(10):
                    if is_file_stable(file_path, Config.STABILITY_CHECK_SECONDS):
                        stable = True
                        break
                    time.sleep(2)

                if not stable:
                    log_event("WARNING", "Watcher", f"File '{file_path.name}' is still in use or unstable. Will retry later.")
                    self.processing_paths.discard(path_str)
                    return

                # File is confirmed ready
                self.on_video_ready(file_path)
            except Exception as e:
                log_event("ERROR", "Watcher", f"Error evaluating file '{file_path.name}': {e}")
            finally:
                self.processing_paths.discard(path_str)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    def on_created(self, event):
        if not event.is_directory:
            self.process_file_candidate(Path(event.src_path))

    def on_moved(self, event):
        if not event.is_directory:
            self.process_file_candidate(Path(event.dest_path))


class FolderWatcher:
    def __init__(self, on_video_ready: Callable[[Path], None]):
        self.on_video_ready = on_video_ready
        self.observer: Optional[Observer] = None
        self._running = False
        self._polling_thread: Optional[threading.Thread] = None

    def start(self):
        Config.ensure_directories()
        self._running = True

        # Watchdog observer
        handler = VideoFolderHandler(self.on_video_ready)
        self.observer = Observer()
        self.observer.schedule(handler, str(Config.WATCH_FOLDER), recursive=False)
        self.observer.start()

        # Polling thread for redundancy and catching files already present at launch
        self._polling_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._polling_thread.start()

        log_event("INFO", "Watcher", f"Watching folder: {Config.WATCH_FOLDER}")

    def scan_once(self):
        """Immediately scans the watch folder for any unhandled videos."""
        if not Config.WATCH_FOLDER.exists():
            return

        for item in Config.WATCH_FOLDER.iterdir():
            if item.is_file() and item.suffix.lower() in Config.SUPPORTED_EXTENSIONS:
                existing = get_video_by_path(str(item.resolve()))
                if not existing or existing.get("status") in ["detected", "failed"]:
                    if is_file_stable(item, check_seconds=1):
                        self.on_video_ready(item)

    def _poll_loop(self):
        # Initial scan on startup
        time.sleep(1)
        self.scan_once()

        while self._running:
            time.sleep(Config.SCAN_INTERVAL_SECONDS)
            try:
                self.scan_once()
            except Exception as e:
                log_event("WARNING", "Watcher", f"Error in watch polling scan: {e}")

    def stop(self):
        self._running = False
        if self.observer:
            self.observer.stop()
            self.observer.join()
        log_event("INFO", "Watcher", "Folder watcher stopped.")
