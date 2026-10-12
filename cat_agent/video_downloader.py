"""
Video Downloader for CatAgent.
Uses yt-dlp to download Instagram Reels, Facebook Shorts, and YouTube Shorts
directly to a temporary working directory using bundled ffmpeg.
"""

import os
import re
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional
import yt_dlp
import imageio_ffmpeg

from config import Config
from db import log_event

TEMP_DOWNLOAD_DIR = Config.BASE_DIR / "cat_agent" / "temp"
TEMP_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


def download_short_video(url: str, job_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Downloads a video from YouTube Shorts, Instagram Reels, or Facebook Reels.
    Returns:
        {
            "success": bool,
            "filepath": Path,
            "title": str,
            "duration": float,
            "error": Optional[str]
        }
    """
    TEMP_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    import shutil
    ffmpeg_exe = shutil.which("ffmpeg")
    if not ffmpeg_exe:
        try:
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg_exe = "ffmpeg"

    out_prefix = f"job_{job_id or 'test'}_"
    out_template = str(TEMP_DOWNLOAD_DIR / f"{out_prefix}%(id)s.%(ext)s")

    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "outtmpl": out_template,
        "ffmpeg_location": ffmpeg_exe,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "socket_timeout": 30,
        # Allow generic extractors for social media
        "ignoreerrors": False,
    }

    log_event("INFO", "Downloader", f"Starting download for URL: {url}", job_id)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                raise ValueError("No video metadata returned from link.")

            # Find downloaded file
            video_id = info.get("id", "unknown")
            expected_file = TEMP_DOWNLOAD_DIR / f"{out_prefix}{video_id}.mp4"
            
            if not expected_file.exists():
                # Search for any file matching prefix
                matching = list(TEMP_DOWNLOAD_DIR.glob(f"{out_prefix}*.*"))
                if matching:
                    expected_file = matching[0]
                else:
                    raise FileNotFoundError("Downloaded video file could not be located on disk.")

            log_event(
                "SUCCESS",
                "Downloader",
                f"Video downloaded successfully: '{expected_file.name}' ({expected_file.stat().st_size / (1024*1024):.2f} MB)",
                job_id
            )

            return {
                "success": True,
                "filepath": expected_file,
                "title": info.get("title", ""),
                "duration": info.get("duration", 0),
                "error": None
            }

    except Exception as e:
        error_msg = str(e)
        log_event("ERROR", "Downloader", f"Failed to download video from {url}: {error_msg}", job_id)
        return {
            "success": False,
            "filepath": None,
            "title": "",
            "duration": 0,
            "error": error_msg
        }


def cleanup_temp_video(filepath: Optional[Path]):
    """Safely removes a temporary downloaded video file."""
    if filepath and Path(filepath).exists():
        try:
            Path(filepath).unlink()
        except Exception:
            pass
