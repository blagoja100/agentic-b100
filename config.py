"""
Configuration module for YouTube Agent.
Loads settings from environment variables and .env file.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

# Load existing .env if present
load_dotenv(ENV_PATH)


class Config:
    BASE_DIR: Path = BASE_DIR
    
    # Data & Credentials Folder
    DATA_DIR: Path = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data"))).resolve()
    
    # Folders
    WATCH_FOLDER: Path = Path(os.getenv("WATCH_FOLDER", str(BASE_DIR / "watch_folder"))).resolve()
    PROCESSED_FOLDER: Path = Path(os.getenv("PROCESSED_FOLDER", str(BASE_DIR / "processed_folder"))).resolve()
    FAILED_FOLDER: Path = Path(os.getenv("FAILED_FOLDER", str(BASE_DIR / "failed_folder"))).resolve()
    
    # YouTube Settings - checks DATA_DIR first, then BASE_DIR
    CLIENT_SECRETS_FILE: Path = Path(os.getenv("CLIENT_SECRETS_FILE", str(BASE_DIR / "data" / "client_secrets.json" if (BASE_DIR / "data" / "client_secrets.json").exists() else BASE_DIR / "client_secrets.json"))).resolve()
    TOKEN_FILE: Path = Path(os.getenv("TOKEN_FILE", str(BASE_DIR / "data" / "token.json" if (BASE_DIR / "data" / "token.json").exists() else BASE_DIR / "token.json"))).resolve()
    DEFAULT_PRIVACY: str = os.getenv("DEFAULT_PRIVACY", "private")  # private, unlisted, public
    DEFAULT_CATEGORY_ID: str = os.getenv("DEFAULT_CATEGORY_ID", "28")  # 28: Science & Technology
    
    # Gemini AI Settings
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    
    # Agent Workflow
    AUTO_UPLOAD: bool = os.getenv("AUTO_UPLOAD", "false").lower() in ("true", "1", "yes")
    STABILITY_CHECK_SECONDS: int = int(os.getenv("STABILITY_CHECK_SECONDS", "3"))
    SCAN_INTERVAL_SECONDS: int = int(os.getenv("SCAN_INTERVAL_SECONDS", "5"))
    
    # Server Settings
    WEB_HOST: str = os.getenv("WEB_HOST", "0.0.0.0")
    WEB_PORT: int = int(os.getenv("WEB_PORT", "8000"))
    
    # Supported Video Extensions
    SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv"}

    @classmethod
    def ensure_directories(cls):
        """Ensure all operational directories exist."""
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        cls.WATCH_FOLDER.mkdir(parents=True, exist_ok=True)
        cls.PROCESSED_FOLDER.mkdir(parents=True, exist_ok=True)
        cls.FAILED_FOLDER.mkdir(parents=True, exist_ok=True)

    @classmethod
    def update_setting(cls, key: str, value: str):
        """Update a setting in memory and in the .env file."""
        os.environ[key] = value
        
        # Read existing .env lines
        lines = []
        if ENV_PATH.exists():
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()
        
        found = False
        new_lines = []
        for line in lines:
            if line.strip().startswith(f"{key}="):
                new_lines.append(f"{key}={value}\n")
                found = True
            else:
                new_lines.append(line)
        
        if not found:
            new_lines.append(f"{key}={value}\n")
            
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
            
        # Re-sync attributes
        if key == "WATCH_FOLDER":
            cls.WATCH_FOLDER = Path(value).resolve()
        elif key == "PROCESSED_FOLDER":
            cls.PROCESSED_FOLDER = Path(value).resolve()
        elif key == "DEFAULT_PRIVACY":
            cls.DEFAULT_PRIVACY = value
        elif key == "GEMINI_API_KEY":
            cls.GEMINI_API_KEY = value
        elif key == "GEMINI_MODEL":
            cls.GEMINI_MODEL = value
        elif key == "AUTO_UPLOAD":
            cls.AUTO_UPLOAD = value.lower() in ("true", "1", "yes")
