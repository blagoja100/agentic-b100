"""
Database management for TubeAgent using SQLite.
Stores video records, states, metadata, and logs.
"""

import sqlite3
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import os

DB_DIR = Path(__file__).resolve().parent / "data"
if not DB_DIR.exists():
    try:
        DB_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        DB_DIR = Path(__file__).resolve().parent

DB_FILE = Path(os.getenv("DB_FILE", str(DB_DIR / "tube_agent.db"))).resolve()


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initializes database tables if they do not exist."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Videos table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filepath TEXT NOT NULL UNIQUE,
                filename TEXT NOT NULL,
                filesize INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'detected',
                title TEXT,
                description TEXT,
                tags TEXT,
                category_id TEXT DEFAULT '28',
                privacy_status TEXT DEFAULT 'private',
                youtube_video_id TEXT,
                youtube_url TEXT,
                upload_progress INTEGER DEFAULT 0,
                error_message TEXT,
                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                uploaded_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                source TEXT NOT NULL,
                message TEXT NOT NULL,
                video_id INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def log_event(level: str, source: str, message: str, video_id: Optional[int] = None):
    """Log an event to the database and print to console."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    color = "\033[0m"
    if level == "INFO":
        color = "\033[36m"
    elif level == "SUCCESS":
        color = "\033[32m"
    elif level == "WARNING":
        color = "\033[33m"
    elif level == "ERROR":
        color = "\033[31m"
        
    print(f"{color}[{ts}] [{source}] [{level}] {message}\033[0m")
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO logs (level, source, message, video_id) VALUES (?, ?, ?, ?)",
            (level, source, message, video_id)
        )
        conn.commit()


def get_recent_logs(limit: int = 50) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_video_by_path(filepath: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM videos WHERE filepath = ?", (filepath,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_video_by_id(video_id: int) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM videos WHERE id = ?", (video_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_all_videos() -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM videos ORDER BY id DESC")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def add_video(filepath: str, filename: str, filesize: int, status: str = "detected") -> int:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO videos (filepath, filename, filesize, status, detected_at, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, (filepath, filename, filesize, status))
        conn.commit()
        return cursor.lastrowid


def update_video_status(video_id: int, status: str, error_message: Optional[str] = None):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE videos
            SET status = ?, error_message = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (status, error_message, video_id))
        conn.commit()


def update_video_metadata(video_id: int, title: str, description: str, tags: str, category_id: str, privacy_status: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE videos
            SET title = ?, description = ?, tags = ?, category_id = ?, privacy_status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (title, description, tags, category_id, privacy_status, video_id))
        conn.commit()


def update_video_progress(video_id: int, progress: int):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE videos
            SET upload_progress = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (progress, video_id))
        conn.commit()


def mark_video_uploaded(video_id: int, youtube_video_id: str, youtube_url: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE videos
            SET status = 'uploaded',
                upload_progress = 100,
                youtube_video_id = ?,
                youtube_url = ?,
                uploaded_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (youtube_video_id, youtube_url, video_id))
        conn.commit()


def delete_video(video_id: int):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM videos WHERE id = ?", (video_id,))
        cursor.execute("DELETE FROM logs WHERE video_id = ?", (video_id,))
        conn.commit()
