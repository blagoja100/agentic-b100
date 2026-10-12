"""
OAuth Manager for TubeAgent & CatAgent.
Handles Google OAuth2 authentication for YouTube and Gmail in both
local desktop and Docker containerized environments.
"""

import os
import sys
import json
import socket
import logging
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable
from urllib.parse import urlparse
import wsgiref.simple_server

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import Config
from db import log_event

logger = logging.getLogger(__name__)

# Reusable WSGI server that sets SO_REUSEADDR to avoid [Errno 98] Address already in use
class ReusableWSGIServer(wsgiref.simple_server.WSGIServer):
    allow_reuse_address = True


class _OAuthRedirectApp:
    def __init__(self, service_title: str):
        self.service_title = service_title
        self.last_request_uri = None

    def __call__(self, environ, start_response):
        # Extract full request URI
        host = environ.get("HTTP_HOST", "localhost")
        path = environ.get("PATH_INFO", "")
        query = environ.get("QUERY_STRING", "")
        self.last_request_uri = f"http://{host}{path}"
        if query:
            self.last_request_uri += f"?{query}"

        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{self.service_title} Connected</title>
    <style>
        body {{
            background: #0f172a;
            color: #f8fafc;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100vh;
            margin: 0;
        }}
        .card {{
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 16px;
            padding: 40px;
            text-align: center;
            max-width: 480px;
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5);
        }}
        h1 {{ color: #10b981; font-size: 24px; margin-bottom: 12px; }}
        p {{ color: #94a3b8; font-size: 15px; line-height: 1.6; margin-bottom: 24px; }}
        .btn {{
            display: inline-block;
            background: #3b82f6;
            color: #ffffff;
            padding: 10px 24px;
            border-radius: 8px;
            text-decoration: none;
            font-weight: 500;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div style="font-size: 48px; margin-bottom: 16px;">🎉</div>
        <h1>{self.service_title} Authenticated!</h1>
        <p>Google account authorization was successful. You can safely close this browser window and return to the TubeAgent dashboard.</p>
        <a href="javascript:window.close()" class="btn">Close Window</a>
    </div>
</body>
</html>"""
        return [html.encode("utf-8")]


class ActiveOAuthSession:
    def __init__(self, service: str, auth_url: str, server: wsgiref.simple_server.WSGIServer, port: int):
        self.service = service
        self.auth_url = auth_url
        self.server = server
        self.port = port
        self.thread: Optional[threading.Thread] = None

    def close(self):
        try:
            if self.server:
                self.server.server_close()
        except Exception:
            pass
        # Wake up the thread waiting on handle_request
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.3)
                probe.connect(("127.0.0.1", self.port))
        except Exception:
            pass
        if self.thread and self.thread != threading.current_thread() and self.thread.is_alive():
            self.thread.join(timeout=1.0)


_active_session_lock = threading.Lock()
_current_active_session: Optional[ActiveOAuthSession] = None


def detect_registered_redirect_port(default_port: int = 8088) -> int:
    """
    Detects the redirect port registered in client_secrets.json.
    Defaults to 8088 if not found or if env OAUTH_PORT is not set.
    """
    env_port = os.getenv("OAUTH_PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            pass

    client_secrets = Config.CLIENT_SECRETS_FILE
    if client_secrets.exists():
        try:
            with open(client_secrets, "r", encoding="utf-8") as f:
                data = json.load(f)
            client_info = data.get("web") or data.get("installed") or {}
            for uri in client_info.get("redirect_uris", []):
                parsed = urlparse(uri)
                if parsed.port:
                    return parsed.port
        except Exception as e:
            logger.warning(f"Could not parse redirect URIs from client_secrets.json: {e}")

    return default_port


def start_oauth_flow(
    service_name: str,
    scopes: List[str],
    token_file: Path,
    port: Optional[int] = None,
    on_success: Optional[Callable[[Credentials, Dict[str, Any]], None]] = None,
    on_error: Optional[Callable[[Exception], None]] = None,
) -> Dict[str, Any]:
    """
    Initiates an OAuth2 flow:
    - Derives port from client_secrets.json redirect_uris (or given port)
    - Generates Google OAuth authorization URL (with prompt='select_account consent'
      so user can select between multiple logged-in accounts)
    - Starts reusable redirect server on host
    - Returns authorization URL immediately for browser opening
    - Handles token exchange in background and saves to token_file
    """
    global _current_active_session

    client_secrets = Config.CLIENT_SECRETS_FILE
    if not client_secrets.exists():
        raise FileNotFoundError(
            f"Client secrets file not found at '{client_secrets}'. "
            "Please upload client_secrets.json via the dashboard."
        )

    target_port = port or detect_registered_redirect_port()
    bind_addr = os.getenv("OAUTH_BIND_ADDR", "0.0.0.0")
    oauth_host = os.getenv("OAUTH_HOST", "localhost")

    with _active_session_lock:
        # If an active session is already running on the same port
        if _current_active_session is not None:
            if _current_active_session.service == service_name:
                log_event("INFO", service_name, f"Reusing active OAuth session on port {_current_active_session.port}")
                return {
                    "status": "ready",
                    "auth_url": _current_active_session.auth_url,
                    "port": _current_active_session.port,
                    "message": f"Authorization session for {service_name} is active."
                }
            else:
                log_event("INFO", service_name, f"Closing previous OAuth session for {_current_active_session.service}")
                _current_active_session.close()
                _current_active_session = None

        flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), scopes)
        flow.redirect_uri = f"http://{oauth_host}:{target_port}/"

        # prompt='select_account consent' allows users with multiple browser accounts
        # to explicitly pick which Google account to authenticate!
        auth_url, _ = flow.authorization_url(prompt="select_account consent", access_type="offline")

        wsgi_app = _OAuthRedirectApp(service_name)
        local_server = None
        for attempt in range(5):
            try:
                local_server = wsgiref.simple_server.make_server(
                    bind_addr,
                    target_port,
                    wsgi_app,
                    server_class=ReusableWSGIServer
                )
                break
            except OSError as e:
                if attempt < 4:
                    import time
                    time.sleep(0.2)
                else:
                    log_event("ERROR", service_name, f"Failed to bind OAuth server to {bind_addr}:{target_port}: {e}")
                    raise OSError(f"Could not bind to port {target_port}: {e}")

        session = ActiveOAuthSession(service_name, auth_url, local_server, target_port)
        _current_active_session = session

        def _worker():
            global _current_active_session
            try:
                log_event("INFO", service_name, f"Waiting for OAuth authorization callback on port {target_port}...")
                local_server.timeout = 180  # 3 minute timeout
                local_server.handle_request()

                if not wsgi_app.last_request_uri:
                    raise TimeoutError(f"OAuth authorization timed out for {service_name}.")

                # OAuth2 exchange requires HTTPS in the authorization_response string
                auth_response = wsgi_app.last_request_uri.replace("http://", "https://")
                flow.fetch_token(authorization_response=auth_response)
                creds = flow.credentials

                token_file.parent.mkdir(parents=True, exist_ok=True)
                with open(token_file, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())

                log_event("SUCCESS", service_name, f"OAuth credentials saved to {token_file.name}")

                extra_info = {}
                if service_name == "Gmail":
                    try:
                        service = build("gmail", "v1", credentials=creds)
                        profile = service.users().getProfile(userId="me").execute()
                        extra_info["email"] = profile.get("emailAddress")
                    except Exception as ex:
                        logger.warning(f"Could not fetch Gmail profile: {ex}")

                if on_success:
                    on_success(creds, extra_info)

            except Exception as ex:
                log_event("ERROR", service_name, f"OAuth callback failed: {ex}")
                if on_error:
                    on_error(ex)
            finally:
                session.close()
                with _active_session_lock:
                    if _current_active_session == session:
                        _current_active_session = None

        thread = threading.Thread(target=_worker, daemon=True)
        session.thread = thread
        thread.start()

        return {
            "status": "ready",
            "auth_url": auth_url,
            "port": target_port,
            "message": f"Authorization URL generated for {service_name}."
        }
