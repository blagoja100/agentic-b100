"""
AI Metadata Generator using Google Gemini.
Analyzes video content or filenames to generate high-CTR titles,
SEO descriptions, tags, and category recommendations.
"""

import os
import re
import time
import json
from pathlib import Path
from typing import Dict, Any, Optional
from config import Config
from db import log_event


YOUTUBE_CATEGORIES = {
    "1": "Film & Animation",
    "2": "Autos & Vehicles",
    "10": "Music",
    "15": "Pets & Animals",
    "17": "Sports",
    "19": "Travel & Events",
    "20": "Gaming",
    "22": "People & Blogs",
    "23": "Comedy",
    "24": "Entertainment",
    "25": "News & Politics",
    "26": "Howto & Style",
    "27": "Education",
    "28": "Science & Technology",
    "29": "Nonprofits & Activism",
}


def clean_filename_to_title(stem: str) -> str:
    """Converts a raw filename like 'my_cool_video-final-v2' to a human title."""
    cleaned = re.sub(r"[_\-\.]+", " ", stem)
    cleaned = re.sub(r"(final|v\d+|render|export|hd|4k|1080p)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.title() if cleaned else "Untitled Video"


def get_companion_notes(video_path: Path) -> Optional[str]:
    """Looks for sidecar notes such as video_name.txt or video_name.json in the same folder."""
    candidates = [
        video_path.with_suffix(".txt"),
        video_path.with_suffix(".notes"),
        video_path.with_suffix(".json"),
        video_path.parent / "notes.txt"
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            try:
                with open(c, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:
                pass
    return None


def generate_fallback_metadata(video_path: Path, notes: Optional[str] = None) -> Dict[str, Any]:
    """Generates clean metadata without calling external API."""
    title = clean_filename_to_title(video_path.stem)
    description = f"{title}\n\n"
    if notes:
        description += f"Notes:\n{notes}\n\n"
    description += "Uploaded automatically by TubeAgent.\n\n#video #content"
    
    tags = ["video", "content", video_path.stem.lower().replace(" ", "_")]
    return {
        "title": title[:100],
        "description": description,
        "tags": ", ".join(tags),
        "category_id": Config.DEFAULT_CATEGORY_ID,
        "privacy_status": Config.DEFAULT_PRIVACY,
        "reasoning": "Generated from filename and companion notes (Gemini API key not configured or fallback used)."
    }


def generate_video_metadata(video_path: Path, video_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Analyzes video using Google Gemini API to generate title, description, tags, and category.
    Falls back gracefully if API key is missing or video upload exceeds quota.
    """
    notes = get_companion_notes(video_path)
    
    if not Config.GEMINI_API_KEY:
        log_event("WARNING", "Gemini", "No GEMINI_API_KEY found in config. Using fallback metadata generator.", video_id)
        return generate_fallback_metadata(video_path, notes)
    
    try:
        from google import genai
        from google.genai import types

        log_event("INFO", "Gemini", f"Initializing Gemini client with model '{Config.GEMINI_MODEL}'...", video_id)
        client = genai.Client(api_key=Config.GEMINI_API_KEY)
        
        file_size_mb = video_path.stat().st_size / (1024 * 1024)
        gemini_file = None
        
        # If video is within reasonable upload size (under 1.5GB)
        if file_size_mb <= 1500:
            try:
                log_event("INFO", "Gemini", f"Uploading video ({file_size_mb:.1f} MB) to Gemini Files API for multimodal analysis...", video_id)
                gemini_file = client.files.upload(file=str(video_path))
                
                # Wait for video processing in Gemini
                log_event("INFO", "Gemini", "Waiting for video file processing in Gemini...", video_id)
                max_wait = 120
                start_time = time.time()
                while gemini_file.state.name == "PROCESSING":
                    if time.time() - start_time > max_wait:
                        log_event("WARNING", "Gemini", "Gemini video processing timed out, proceeding with metadata prompt.", video_id)
                        break
                    time.sleep(3)
                    gemini_file = client.files.get(name=gemini_file.name)
                    
                if gemini_file.state.name == "ACTIVE":
                    log_event("SUCCESS", "Gemini", "Gemini video processing complete. Generating metadata...", video_id)
                else:
                    log_event("WARNING", "Gemini", f"Gemini file state: {gemini_file.state.name}", video_id)
            except Exception as e:
                log_event("WARNING", "Gemini", f"Direct video upload to Gemini failed: {e}. Falling back to prompt analysis.", video_id)
                gemini_file = None

        prompt = f"""
You are an expert YouTube content strategist, SEO specialist, and thumbnail/title copywriter.
Analyze the provided video (or filename and context if video preview is limited) and generate high-performing YouTube metadata.

Video Filename: {video_path.name}
File Size: {file_size_mb:.2f} MB
Additional Creator Notes: {notes if notes else 'None provided'}

Generate a JSON object with the following fields:
1. "title": A catchy, high-CTR YouTube title (max 95 characters, captivating, natural, no clickbait lying).
2. "description": A structured, engaging YouTube description (include an exciting 2-3 sentence overview, timestamps/chapters if appropriate, social call-to-actions, and 3-5 relevant hashtags).
3. "tags": A comma-separated string of 10-15 highly relevant keyword tags for YouTube search.
4. "category_id": The best numeric YouTube Category ID (28 for Science/Tech, 27 for Education, 24 for Entertainment, 20 for Gaming, 22 for People & Blogs, 26 for Howto, etc.).
5. "reasoning": A brief 1-2 sentence explanation of your title & hook strategy.

CRITICAL: Return ONLY raw, valid JSON with keys: "title", "description", "tags", "category_id", "reasoning". Do not wrap in markdown code blocks if possible.
"""

        contents = []
        if gemini_file and gemini_file.state.name == "ACTIVE":
            contents.append(gemini_file)
        contents.append(prompt)

        response = client.models.generate_content(
            model=Config.GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        
        # Clean up uploaded file on Gemini server to save storage
        if gemini_file:
            try:
                client.files.delete(name=gemini_file.name)
            except Exception:
                pass

        raw_text = response.text.strip()
        # Parse JSON
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```(?:json)?\n?", "", raw_text)
            raw_text = re.sub(r"\n?```$", "", raw_text)
            
        data = json.loads(raw_text)
        
        title = data.get("title", clean_filename_to_title(video_path.stem))[:100]
        description = data.get("description", f"Uploaded by TubeAgent\n\nFilename: {video_path.name}")
        tags = data.get("tags", "youtube, video")
        if isinstance(tags, list):
            tags = ", ".join(tags)
        category_id = str(data.get("category_id", Config.DEFAULT_CATEGORY_ID))
        if category_id not in YOUTUBE_CATEGORIES:
            category_id = Config.DEFAULT_CATEGORY_ID
            
        log_event("SUCCESS", "Gemini", f"Generated Title: '{title}' (Category {category_id}: {YOUTUBE_CATEGORIES.get(category_id, 'Other')})", video_id)
        
        return {
            "title": title,
            "description": description,
            "tags": tags,
            "category_id": category_id,
            "privacy_status": Config.DEFAULT_PRIVACY,
            "reasoning": data.get("reasoning", "Generated by Gemini")
        }

    except Exception as e:
        log_event("ERROR", "Gemini", f"Error generating metadata with Gemini: {e}", video_id)
        return generate_fallback_metadata(video_path, notes)
