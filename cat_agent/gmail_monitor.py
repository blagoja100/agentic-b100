"""
Gmail Monitor for CatAgent.
Connects to Gmail API using OAuth 2.0 (with client_secrets.json) or IMAP fallback,
searches for emails with subject starting with 'Be100 Prod: [title]',
extracts video URLs (Instagram Reels, Facebook Shorts, YouTube Shorts),
and marks processed emails as read.
"""

import os
import re
import base64
import html
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Callable
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import Config
from db import log_event

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.readonly"
]

# Patterns for extracting video links from Instagram, Facebook, and YouTube
VIDEO_URL_PATTERNS = [
    # YouTube Shorts & Videos
    r"https?://(?:www\.)?(?:m\.)?(?:youtube\.com/(?:shorts/|watch\?v=)|youtu\.be/)[a-zA-Z0-9_\-\?=&%]+",
    # Instagram Reels & Posts
    r"https?://(?:www\.)?(?:m\.)?instagram\.com/(?:reel|p|reels)/[a-zA-Z0-9_\-]+/?(?:\?[^\s\"'<>]*)?",
    # Facebook Reels, Videos & Watch
    r"https?://(?:www\.|m\.|web\.)?(?:facebook\.com/(?:reel/|watch/?\?v=|share/v/|.*videos/)|fb\.watch/)[a-zA-Z0-9_\-\?=&%]+",
    # Generic video or social link fallback
    r"https?://(?:www\.)?(?:tiktok\.com/|threads\.net/|x\.com/|twitter\.com/)[^\s\"'<>]+"
]


def get_gmail_service() -> Optional[Any]:
    """
    Retrieves or refreshes Gmail credentials and builds the Gmail API service.
    Returns None if credentials or client_secrets are missing or invalid.
    """
    creds = None
    token_file = Config.GMAIL_TOKEN_FILE
    client_secrets_file = Config.CLIENT_SECRETS_FILE

    if token_file.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file), GMAIL_SCOPES)
        except Exception as e:
            log_event("WARNING", "Gmail", f"Could not load Gmail token file: {e}")
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                log_event("INFO", "Gmail", "Refreshing expired Gmail OAuth credentials...")
                creds.refresh(Request())
                with open(token_file, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
            except Exception as e:
                log_event("ERROR", "Gmail", f"Failed to refresh Gmail token: {e}")
                creds = None
        else:
            return None

    if creds and creds.valid:
        try:
            return build("gmail", "v1", credentials=creds)
        except Exception as e:
            log_event("ERROR", "Gmail", f"Failed to build Gmail service: {e}")
            return None

    return None


def is_gmail_authenticated() -> Tuple[bool, Optional[str]]:
    """
    Checks if Gmail is authenticated.
    Returns (True, user_email) or (False, None).
    """
    service = get_gmail_service()
    if not service:
        return False, None
    try:
        profile = service.users().getProfile(userId="me").execute()
        return True, profile.get("emailAddress")
    except Exception:
        return False, None


def start_gmail_oauth(port: Optional[int] = None, on_success: Optional[Callable] = None) -> Dict[str, Any]:
    """
    Starts unified OAuth flow for Gmail, returning auth_url immediately
    and handling callback without port collisions.
    """
    from oauth_manager import start_oauth_flow
    return start_oauth_flow(
        service_name="Gmail",
        scopes=GMAIL_SCOPES,
        token_file=Config.GMAIL_TOKEN_FILE,
        port=port,
        on_success=on_success
    )


def run_gmail_oauth_flow(port: Optional[int] = None) -> Dict[str, Any]:
    """
    Runs OAuth flow to authenticate Gmail access.
    Saves credentials to Config.GMAIL_TOKEN_FILE.
    """
    return start_gmail_oauth(port=port)


def _extract_body_text_from_payload(payload: Dict[str, Any]) -> str:
    """Recursively extracts plain text and HTML from Gmail message payload."""
    body_parts = []

    def _traverse(part):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data:
            try:
                decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                if "html" in mime:
                    # Clean tags but preserve href links
                    decoded = re.sub(r'<a\s+(?:[^>]*?\s+)?href=["\'](.*?)["\']', r' \1 ', decoded, flags=re.IGNORECASE)
                    decoded = re.sub(r'<[^>]+>', ' ', decoded)
                body_parts.append(html.unescape(decoded))
            except Exception:
                pass
        for sub in part.get("parts", []):
            _traverse(sub)

    _traverse(payload)
    return " \n".join(body_parts)


def parse_video_url_from_text(text: str) -> Optional[Tuple[str, str]]:
    """
    Finds the first supported video link in text.
    Returns (url, platform) or None.
    """
    for pattern in VIDEO_URL_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            url = match.group(0).strip()
            # Clean trailing punctuation that might get grabbed
            url = re.sub(r'[\.,;>\)\]\s]+$', '', url)
            
            platform = "web"
            if "instagram.com" in url:
                platform = "instagram"
            elif "facebook.com" in url or "fb.watch" in url:
                platform = "facebook"
            elif "youtube.com" in url or "youtu.be" in url:
                platform = "youtube"
            elif "tiktok.com" in url:
                platform = "tiktok"
            return url, platform

    # General URL regex fallback
    any_url = re.search(r'https?://[^\s<>"\']+', text)
    if any_url:
        u = any_url.group(0).rstrip('.,;>)')
        return u, "web"

    return None


def parse_title_from_subject(subject: str, prefix: str = "Be100 Prod:") -> str:
    """
    Extracts the title from subject starting with 'Be100 Prod: [title]' or 'Be100 Prod: title'.
    """
    clean_subj = subject.strip()
    idx = clean_subj.lower().find(prefix.lower())
    if idx != -1:
        remainder = clean_subj[idx + len(prefix):].strip()
    else:
        remainder = clean_subj

    # Strip square brackets if formatted as [My Title]
    remainder = re.sub(r"^\[\s*", "", remainder)
    remainder = re.sub(r"\s*\]$", "", remainder)
    return remainder.strip() or "Untitled Video"


def search_for_be100_emails(only_unread: bool = True) -> List[Dict[str, Any]]:
    """
    Queries Gmail inbox for emails matching 'Be100 Prod:' subject.
    Returns list of parsed job candidates:
    [{
        'email_id': str,
        'subject': str,
        'sender': str,
        'title': str,
        'video_url': str,
        'platform': str,
        'body_snippet': str
    }]
    """
    service = get_gmail_service()
    if not service:
        return []

    prefix = Config.GMAIL_SUBJECT_PREFIX.strip()
    query_parts = [f'subject:"{prefix}"']
    if only_unread:
        query_parts.append("is:unread")
    query = " ".join(query_parts)

    try:
        results = service.users().messages().list(userId="me", q=query, maxResults=20).execute()
        messages = results.get("messages", [])
        if not messages:
            return []

        jobs = []
        for m in messages:
            msg_id = m["id"]
            msg_detail = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
            headers = {h["name"].lower(): h["value"] for h in msg_detail.get("payload", {}).get("headers", [])}
            
            subject = headers.get("subject", "")
            sender = headers.get("from", "")
            
            # Check subject prefix match
            if prefix.lower() not in subject.lower():
                continue

            extracted_title = parse_title_from_subject(subject, prefix)
            full_text = _extract_body_text_from_payload(msg_detail.get("payload", {}))
            snippet = msg_detail.get("snippet", "")
            combined_content = f"{snippet}\n{full_text}"

            parsed_url = parse_video_url_from_text(combined_content)
            if not parsed_url:
                log_event("WARNING", "Gmail", f"Email #{msg_id} ('{subject}') matched prefix but contained no video link.")
                continue

            video_url, platform = parsed_url
            jobs.append({
                "email_id": msg_id,
                "subject": subject,
                "sender": sender,
                "title": extracted_title,
                "video_url": video_url,
                "platform": platform,
                "body_snippet": snippet[:200]
            })

        return jobs
    except Exception as e:
        log_event("ERROR", "Gmail", f"Error searching Gmail: {e}")
        return []


def mark_email_as_read(email_id: str) -> bool:
    """Removes UNREAD label from the specified Gmail email message."""
    service = get_gmail_service()
    if not service:
        return False
    try:
        service.users().messages().modify(
            userId="me",
            id=email_id,
            body={"removeLabelIds": ["UNREAD"]}
        ).execute()
        return True
    except Exception as e:
        log_event("WARNING", "Gmail", f"Could not mark email #{email_id} as read: {e}")
        return False
