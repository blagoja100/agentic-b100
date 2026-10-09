"""
YouTube Data API v3 uploader and OAuth2 authentication manager.
Handles channel authentication, channel profile retrieval, and resumable video uploads.
"""

import os
import time
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from config import Config
from db import log_event

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]


def get_authenticated_service() -> Optional[Any]:
    """
    Retrieves or refreshes YouTube credentials and builds the YouTube service.
    Returns None if client_secrets or tokens are missing or invalid.
    """
    creds = None
    token_file = Config.TOKEN_FILE
    client_secrets_file = Config.CLIENT_SECRETS_FILE

    if token_file.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        except Exception as e:
            log_event("WARNING", "YouTube", f"Could not load token file: {e}")
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                log_event("INFO", "YouTube", "Refreshing expired YouTube OAuth credentials...")
                creds.refresh(Request())
                with open(token_file, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
            except Exception as e:
                log_event("ERROR", "YouTube", f"Failed to refresh YouTube token: {e}")
                creds = None
        else:
            return None

    if creds and creds.valid:
        try:
            return build("youtube", "v3", credentials=creds)
        except Exception as e:
            log_event("ERROR", "YouTube", f"Failed to build YouTube service: {e}")
            return None
    return None


def run_oauth_flow(port: int = 8088) -> Dict[str, Any]:
    """
    Runs local webserver OAuth flow to authenticate YouTube account.
    Supports binding to 0.0.0.0 inside Docker while redirecting to localhost.
    """
    client_secrets_file = Config.CLIENT_SECRETS_FILE
    if not client_secrets_file.exists():
        raise FileNotFoundError(
            f"Client secrets file not found at '{client_secrets_file}'. "
            "Please download your client_secrets.json from Google Cloud Console."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_file), SCOPES)
    bind_addr = os.getenv("OAUTH_BIND_ADDR", "0.0.0.0")
    oauth_host = os.getenv("OAUTH_HOST", "localhost")

    try:
        creds = flow.run_local_server(
            host=oauth_host,
            bind_addr=bind_addr,
            port=port,
            prompt="consent",
            access_type="offline",
            open_browser=True
        )
    except Exception as e:
        log_event("INFO", "YouTube", f"Falling back to non-browser open flow: {e}")
        creds = flow.run_local_server(
            host=oauth_host,
            bind_addr=bind_addr,
            port=port,
            prompt="consent",
            access_type="offline",
            open_browser=False
        )

    # Ensure parent directory for token file exists
    Config.TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(Config.TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    log_event("SUCCESS", "YouTube", "Successfully authenticated with YouTube!")
    return get_channel_info()


def get_channel_info() -> Dict[str, Any]:
    """
    Fetches information about the currently authenticated YouTube channel.
    """
    youtube = get_authenticated_service()
    if not youtube:
        return {
            "authenticated": False,
            "has_client_secrets": Config.CLIENT_SECRETS_FILE.exists(),
            "message": "Not authenticated. Connect your YouTube account."
        }

    try:
        response = youtube.channels().list(mine=True, part="snippet,statistics").execute()
        items = response.get("items", [])
        if not items:
            return {
                "authenticated": True,
                "has_client_secrets": True,
                "title": "Unknown Channel",
                "custom_url": "",
                "channel_id": "",
                "avatar_url": "",
                "subscribers": 0,
                "videos": 0
            }

        item = items[0]
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})

        return {
            "authenticated": True,
            "has_client_secrets": True,
            "channel_id": item.get("id"),
            "title": snippet.get("title"),
            "description": snippet.get("description", ""),
            "custom_url": snippet.get("customUrl", ""),
            "avatar_url": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
            "subscribers": stats.get("subscriberCount", "0"),
            "videos": stats.get("videoCount", "0"),
            "views": stats.get("viewCount", "0")
        }
    except Exception as e:
        log_event("ERROR", "YouTube", f"Error getting channel info: {e}")
        return {
            "authenticated": False,
            "has_client_secrets": Config.CLIENT_SECRETS_FILE.exists(),
            "error": str(e)
        }


def upload_video_to_youtube(
    video_path: Path,
    title: str,
    description: str,
    tags: str,
    category_id: str,
    privacy_status: str,
    progress_callback: Optional[Callable[[int, int, int], None]] = None,
    video_id_record: Optional[int] = None
) -> Dict[str, Any]:
    """
    Uploads a video to YouTube using resumable upload chunks.
    Reports progress via progress_callback(percentage, bytes_uploaded, total_bytes).
    """
    youtube = get_authenticated_service()
    if not youtube:
        raise RuntimeError("YouTube service is not authenticated. Please complete OAuth login.")

    if not video_path.exists():
        raise FileNotFoundError(f"Video file does not exist: {video_path}")

    # Format tags list
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tag_list,
            "categoryId": str(category_id)
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False
        }
    }

    total_size = video_path.stat().st_size
    log_event("INFO", "YouTube", f"Starting upload for '{video_path.name}' ({total_size / (1024*1024):.2f} MB)...", video_id_record)

    # 5MB chunk size for reliable upload
    chunk_size = 5 * 1024 * 1024
    media = MediaFileUpload(
        str(video_path),
        chunksize=chunk_size,
        resumable=True
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    response = None
    retry_count = 0
    max_retries = 5

    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                percent = int(status.progress() * 100)
                bytes_uploaded = int(status.progress() * total_size)
                if progress_callback:
                    progress_callback(percent, bytes_uploaded, total_size)
                if percent % 20 == 0 or percent == 100:
                    log_event("INFO", "YouTube", f"Upload progress: {percent}%", video_id_record)
        except HttpError as e:
            if e.resp.status in [500, 502, 503, 504]:
                retry_count += 1
                if retry_count > max_retries:
                    raise
                wait_time = 2 ** retry_count
                log_event("WARNING", "YouTube", f"Transient HTTP error ({e.resp.status}). Retrying in {wait_time}s...", video_id_record)
                time.sleep(wait_time)
            else:
                raise

    video_id = response.get("id")
    youtube_url = f"https://youtu.be/{video_id}"
    studio_url = f"https://studio.youtube.com/video/{video_id}/edit"

    log_event("SUCCESS", "YouTube", f"Video uploaded successfully! ID: {video_id} - URL: {youtube_url}", video_id_record)

    return {
        "video_id": video_id,
        "youtube_url": youtube_url,
        "studio_url": studio_url,
        "title": title,
        "privacy_status": privacy_status
    }
