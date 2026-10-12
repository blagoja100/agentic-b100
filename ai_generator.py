"""
AI Metadata Generator using Google Gemini.
Analyzes video content or filenames to generate high-CTR titles,
SEO descriptions, tags, and category recommendations dynamically.
"""

import os
import re
import time
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
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

STOPWORDS = {
    "the", "and", "or", "for", "with", "from", "of", "in", "at", "to", "by",
    "a", "an", "is", "it", "this", "that", "on", "into", "as", "be", "are",
    "was", "were", "my", "your", "our", "all", "any", "how", "what", "why",
    "when", "where", "who", "which", "there", "their", "so", "up", "out", "no",
    "then", "some", "more", "also", "just", "very", "too", "over", "than"
}

# Domain vocabulary for inferring category ONLY (no video-specific titles)
CATEGORY_DOMAIN_KEYWORDS = {
    "15": ["cat", "dog", "puppy", "kitten", "pet", "pets", "animal", "animals", "wildlife", "bird", "feline", "canine", "hamster", "rabbit", "fish", "zoo", "rescue"],
    "10": ["music", "song", "dance", "dancing", "beat", "remix", "audio", "track", "rap", "hip hop", "singer", "guitar", "piano", "cover", "lyrics", "acoustic", "concert", "orchestra", "instrumental"],
    "20": ["gaming", "game", "gameplay", "walkthrough", "playthrough", "boss", "speedrun", "roblox", "minecraft", "fortnite", "gta", "rpg", "fps", "stream", "clutch", "esports", "mod"],
    "28": ["code", "coding", "programming", "python", "javascript", "developer", "software", "tech", "technology", "ai", "artificial intelligence", "gemini", "robot", "docker", "cloud", "api", "framework", "database", "linux"],
    "26": ["how to", "howto", "tutorial", "guide", "diy", "recipe", "cooking", "bake", "baking", "craft", "tips", "tricks", "style", "makeup", "fitness", "workout", "routine", "kitchen"],
    "23": ["funny", "hilarious", "comedy", "laugh", "meme", "memes", "joke", "prank", "humor", "blooper", "fails", "fail", "lol", "parody"],
    "17": ["sport", "sports", "football", "soccer", "basketball", "tennis", "gym", "match", "goal", "highlights", "tournament", "athlete", "boxing", "ufc"],
    "19": ["travel", "trip", "tour", "vacation", "flight", "destination", "explore", "city", "country", "adventure", "hotel"],
    "1": ["animation", "anime", "cartoon", "cgi", "cinema", "movie", "film", "trailer", "short film"],
    "2": ["car", "truck", "motorcycle", "auto", "vehicle", "racing", "drive", "drifting", "exhaust", "supercar", "automotive"],
    "22": ["vlog", "daily vlog", "storytime", "interview", "podcast", "reaction", "life", "conversation"],
    "24": ["entertainment", "show", "viral", "celebrity", "magic", "talent", "acting", "tiktok", "trend", "challenge"]
}


def infer_category_id(text: str) -> str:
    """Infers the most appropriate YouTube category ID dynamically from text clues."""
    text_lower = text.lower()
    scores = {}
    for cat_id, keywords in CATEGORY_DOMAIN_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in text_lower:
                score += len(kw.split()) * 2
        if score > 0:
            scores[cat_id] = score
    if scores:
        return max(scores.items(), key=lambda x: x[1])[0]
    return Config.DEFAULT_CATEGORY_ID


def clean_filename_to_title(stem: str) -> str:
    """Converts any raw filename to a natural, well-formatted YouTube title."""
    cleaned = re.sub(r"[_\-\.]+", " ", stem)
    cleaned = re.sub(r"\b(final|v\d+|render|export|hd|4k|1080p|720p|x264|x265|hevc|h264|aac|mp3|mp4)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[.*?\]|\(.*?\)", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    words = cleaned.split()
    title_words = []
    special_cases = {
        "mc": "MC",
        "dj": "DJ",
        "ai": "AI",
        "tv": "TV",
        "hd": "HD",
        "4k": "4K",
        "cant": "Can't",
        "dont": "Don't",
        "wont": "Won't",
        "im": "I'm",
        "its": "It's",
        "youre": "You're",
        "vs": "vs.",
    }
    lowercase_words = {"a", "an", "the", "and", "but", "or", "for", "nor", "on", "at", "to", "by", "of", "in"}

    for i, w in enumerate(words):
        w_lower = w.lower()
        if w_lower in special_cases:
            title_words.append(special_cases[w_lower])
        elif i > 0 and w_lower in lowercase_words:
            title_words.append(w_lower)
        else:
            title_words.append(w.capitalize())

    return " ".join(title_words) if title_words else "Untitled Video"


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


def generate_smart_tags(title: str, category_id: str = "24", notes: Optional[str] = None, base_tags: Optional[List[str]] = None) -> List[str]:
    """
    Dynamically generates 15-18 highly relevant YouTube tags based purely on
    the video's filename/title and content tokens. No video-specific hardcoding.
    """
    tags_pool = []

    # 1. Include any pre-existing or user-provided base tags
    if base_tags:
        for b in base_tags:
            b_clean = re.sub(r"^[#\s]+", "", str(b)).strip().lower()
            if b_clean and b_clean not in tags_pool:
                tags_pool.append(b_clean)

    # 2. Extract content tokens from title
    title_clean = re.sub(r"[^\w\s]", " ", title).lower()
    raw_words = [w for w in title_clean.split() if len(w) >= 2]
    content_tokens = [w for w in raw_words if w not in STOPWORDS and not w.isdigit()]

    # 3. Full title phrase (if reasonable length)
    full_phrase = " ".join(raw_words)
    if full_phrase and len(full_phrase) < 60 and full_phrase not in tags_pool:
        tags_pool.append(full_phrase)

    # 4. Bigrams (two-word phrases from title)
    bigrams = []
    for i in range(len(content_tokens) - 1):
        bg = f"{content_tokens[i]} {content_tokens[i+1]}"
        if bg not in tags_pool:
            tags_pool.append(bg)
        bigrams.append(bg)

    # 5. Trigrams (three-word phrases from title)
    for i in range(len(content_tokens) - 2):
        tg = f"{content_tokens[i]} {content_tokens[i+1]} {content_tokens[i+2]}"
        if tg not in tags_pool:
            tags_pool.append(tg)

    # 6. Individual significant tokens
    for tok in content_tokens:
        if len(tok) >= 3 and tok not in tags_pool:
            tags_pool.append(tok)

    # 7. Extract primary subjects (bigrams + significant keywords)
    subjects = []
    for bg in bigrams:
        if bg not in subjects:
            subjects.append(bg)
    for tok in content_tokens:
        if len(tok) >= 3 and tok not in subjects:
            subjects.append(tok)

    # 8. Dynamic domain modifiers (combines the ACTUAL filename tokens with search intent modifiers)
    mods_by_cat = {
        "15": ["cute {s}", "funny {s}", "{s} video", "{s} moments", "best {s}", "{s} clips"],
        "10": ["{s} music", "{s} song", "{s} audio", "{s} performance", "{s} live", "{s} rhythm"],
        "20": ["{s} gameplay", "{s} walkthrough", "{s} highlights", "{s} clips", "{s} boss fight"],
        "28": ["{s} tutorial", "{s} guide", "learn {s}", "{s} coding", "{s} course", "how to use {s}"],
        "26": ["how to make {s}", "{s} recipe", "{s} tutorial", "{s} guide", "easy {s}", "{s} tips"],
        "23": ["funny {s}", "{s} comedy", "{s} meme", "{s} moments", "hilarious {s}"],
        "17": ["{s} highlights", "{s} training", "{s} workout", "{s} match", "{s} sports"],
        "19": ["{s} travel", "{s} tour", "{s} vlog", "exploring {s}", "visit {s}"],
        "24": ["{s} video", "best {s}", "{s} moments", "watch {s}", "{s} compilation", "viral {s}"],
    }

    cat_mods = mods_by_cat.get(category_id, mods_by_cat["24"])
    for subj in subjects:
        subj_words = subj.split()
        for pattern in cat_mods:
            if len(tags_pool) >= 18:
                break
            # Avoid duplicate words like 'recipe recipe' or 'tutorial tutorial'
            mod_suffix = pattern.replace("{s}", "").strip()
            if any(w in mod_suffix for w in subj_words):
                continue
            d = pattern.format(s=subj)
            if d not in tags_pool and len(d) < 50:
                tags_pool.append(d)

    # 9. Universal discoverability modifiers if still under 15
    univ_mods = ["{s} video", "{s} highlights", "{s} clips", "best of {s}", "trending {s}"]
    for subj in subjects:
        subj_words = subj.split()
        for pattern in univ_mods:
            if len(tags_pool) >= 18:
                break
            mod_suffix = pattern.replace("{s}", "").strip()
            if any(w in mod_suffix for w in subj_words):
                continue
            d = pattern.format(s=subj)
            if d not in tags_pool and len(d) < 50:
                tags_pool.append(d)

    # 10. Fallback discoverability tags if filename was too short (e.g. 'v1.mp4')
    if len(tags_pool) < 12:
        general_discovery = ["viral video", "trending", "must watch", "entertainment", "best clips", "explore", "popular"]
        for gd in general_discovery:
            if len(tags_pool) >= 15:
                break
            if gd not in tags_pool:
                tags_pool.append(gd)

    return tags_pool[:18]


def generate_dynamic_hashtags(title: str, category_id: str = "24") -> str:
    """Generates 5-7 relevant hashtags dynamically from title words and category."""
    clean = re.sub(r"[^\w\s]", "", title)
    words = [w.capitalize() for w in clean.split() if len(w) >= 3 and w.lower() not in STOPWORDS and not w.isdigit()]

    hashtags = []
    # Compound tag from first 2 content words
    if len(words) >= 2:
        hashtags.append(f"#{words[0]}{words[1]}")

    for w in words[:4]:
        hashtags.append(f"#{w}")

    cat_tags = {
        "15": ["#Pets", "#Animals"],
        "10": ["#Music", "#Dance"],
        "20": ["#Gaming", "#Gameplay"],
        "28": ["#Tech", "#Coding", "#Tutorial"],
        "26": ["#HowTo", "#Tutorial"],
        "23": ["#Comedy", "#Funny"],
        "17": ["#Sports", "#Fitness"],
        "19": ["#Travel", "#Vlog"],
        "24": ["#Entertainment", "#Viral"]
    }
    hashtags.extend(cat_tags.get(category_id, ["#Entertainment", "#Viral"]))
    hashtags.extend(["#Trending", "#YouTube"])

    seen = set()
    unique = []
    for h in hashtags:
        hl = h.lower()
        if hl not in seen:
            seen.add(hl)
            unique.append(h)
            if len(unique) >= 7:
                break
    return " ".join(unique)


def generate_rich_description(title: str, category_id: str = "24", notes: Optional[str] = None, tags: Optional[List[str]] = None) -> str:
    """Generates a structured, engaging, high-retention YouTube video description dynamically tailored to the video topic."""
    sections = []

    # Category-specific dynamic templates
    hooks = {
        "28": (
            f"💻 Dive into {title}!\n\n"
            f"Welcome! In this video, we break down {title} step by step. "
            f"Whether you're looking to build practical skills, understand key concepts, or streamline your workflow, "
            f"this guide is designed to give you clear, actionable takeaways you can apply right away."
        ),
        "27": (
            f"📚 Learn {title}!\n\n"
            f"Welcome to this educational breakdown of {title}. "
            f"We explore the essential insights, core principles, and practical examples to help you master this topic with confidence."
        ),
        "20": (
            f"🎮 Epic Highlights: {title}!\n\n"
            f"Welcome to this action-packed session of {title}! "
            f"From clutch plays and tactical maneuvers to intense moments, check out the top highlights and gameplay captured in this video."
        ),
        "15": (
            f"🐾 Adorable Moments: {title}!\n\n"
            f"Get ready to smile! Watch {title} — packed with wholesome antics, heartwarming energy, and unforgettable scenes. "
            f"This clip is guaranteed to brighten your day and bring some joy to your feed."
        ),
        "10": (
            f"🎵 Turn Up the Volume: {title}!\n\n"
            f"Experience {title}! Featuring captivating sound, unforgettable rhythm, and standout performances, "
            f"this showcase delivers high energy and great vibes from start to finish."
        ),
        "26": (
            f"✨ Step-by-Step Guide: {title}!\n\n"
            f"Welcome! In this walkthrough, we're exploring {title}. "
            f"Follow along as we cover the technique, essential tips, and simple steps to achieve great results."
        ),
        "23": (
            f"😂 Get Ready to Laugh: {title}!\n\n"
            f"Check out {title} for non-stop laughs and hilarious moments! "
            f"Packed with unexpected humor and great entertainment, this clip is guaranteed to put a smile on your face."
        ),
        "17": (
            f"⚡ High-Energy Highlights: {title}!\n\n"
            f"Witness standout athletic performance and high-intensity moments in {title}. "
            f"From top plays to memorable highlights, experience the full energy of the action."
        ),
        "19": (
            f"✈️ Travel & Discover: {title}!\n\n"
            f"Join the adventure in {title}! Explore scenic views, local atmospheres, and unforgettable sights "
            f"captured along this incredible journey."
        ),
        "2": (
            f"🚗 Automotive Showcase: {title}!\n\n"
            f"Check out {title}! Featuring great sound, power, and standout automotive details, "
            f"dive into the full review and walkaround."
        ),
        "24": (
            f"🎉 Watch: {title}!\n\n"
            f"Get ready for pure entertainment! In {title}, enjoy standout highlights, great moments, and non-stop energy. "
            f"From start to finish, this video is designed to keep you entertained and smiling."
        ),
    }

    bullet_points = {
        "28": (
            "✨ What You'll Learn in This Video:\n"
            "• Clear, step-by-step breakdown of core concepts\n"
            "• Best practices, practical tips, and implementation guidance\n"
            "• Key takeaways designed for real-world projects"
        ),
        "27": (
            "✨ Key Takeaways:\n"
            "• Comprehensive overview of essential concepts\n"
            "• Practical examples and intuitive explanations\n"
            "• Actionable knowledge you can use right away"
        ),
        "20": (
            "✨ What to Watch For:\n"
            "• Clutch plays, tactical decisions, and top gameplay moments\n"
            "• Exciting strategies and high-stakes encounters\n"
            "• Non-stop action and memorable highlights"
        ),
        "15": (
            "✨ What You'll Love:\n"
            "• Heartwarming antics and adorable moments\n"
            "• Pure wholesome energy to make you smile\n"
            "• Amazing replay value to share with friends and family"
        ),
        "10": (
            "✨ Musical Highlights:\n"
            "• Captivating rhythm, beats, and standout performance\n"
            "• Great audio vibes that make you want to listen on repeat\n"
            "• Unforgettable moments and musical energy"
        ),
        "26": (
            "✨ Inside This Guide:\n"
            "• Easy-to-follow, step-by-step instructions\n"
            "• Pro tips and practical recommendations for best results\n"
            "• Everything you need to master this successfully"
        ),
        "23": (
            "✨ Comedy Highlights:\n"
            "• Hilarious scenes and unexpected funny moments\n"
            "• Try-not-to-laugh clips that deliver pure fun\n"
            "• Great entertainment to share with your friends"
        ),
        "17": (
            "✨ Highlights:\n"
            "• Peak athletic moments and intense plays\n"
            "• Standout performance and competitive spirit\n"
            "• Electrifying moments from the session"
        ),
        "19": (
            "✨ Travel Highlights:\n"
            "• Stunning sights and local ambiance\n"
            "• Memorable travel experiences and recommendations\n"
            "• A firsthand look at incredible destinations"
        ),
        "24": (
            "✨ What You'll Love in This Video:\n"
            "• High energy and memorable moments from start to finish\n"
            "• Perfect entertainment for your daily dose of fun\n"
            "• Great replay value that you'll want to watch again"
        )
    }

    ctas = {
        "28": "💬 Have questions or suggestions? Drop a comment below! What would you like to see covered next?",
        "20": "💬 What was your favorite play or moment in this session? Let us know in the comments below!",
        "15": "💬 Did this brighten your day? Tell us in the comments and share your favorite pet stories!",
        "10": "💬 What did you think of this track/performance? Drop your favorite moment in the comments below!",
        "26": "💬 Tried this out or have tips of your own? Let us know in the comments how it went!",
        "23": "💬 What part made you laugh the hardest? Drop a comment below!",
        "19": "💬 Have you been here or is it on your bucket list? Let us know in the comments below!",
        "24": "💬 What was your absolute favorite moment in this video? Let us know in the comments below!"
    }

    # 1. Hook
    hook = hooks.get(category_id, hooks["24"])
    sections.append(hook)

    # 2. Highlights
    bullets = bullet_points.get(category_id, bullet_points["24"])
    sections.append(bullets)

    # 3. Creator notes
    if notes and notes.strip():
        sections.append(f"📌 Creator Notes & Details:\n{notes.strip()}")

    # 4. Community CTA
    cta_q = ctas.get(category_id, ctas["24"])
    sections.append(
        f"{cta_q}\n\n"
        "👍 Enjoyed the video? Give it a THUMBS UP and share it with friends!\n"
        "🔔 SUBSCRIBE and hit the notification bell so you never miss another upload!"
    )

    # 5. Dynamic Hashtags
    hashtags = generate_dynamic_hashtags(title, category_id)
    sections.append(hashtags)
    sections.append("Uploaded automatically by TubeAgent.")

    return "\n\n".join(sections)


def generate_fallback_metadata(video_path: Path, notes: Optional[str] = None) -> Dict[str, Any]:
    """Generates comprehensive, dynamic metadata based on the video filename without calling external API."""
    title = clean_filename_to_title(video_path.stem)
    category_id = infer_category_id(f"{video_path.stem} {notes or ''}")
    tags_list = generate_smart_tags(title, category_id, notes)
    description = generate_rich_description(title, category_id, notes, tags_list)

    return {
        "title": title[:100],
        "description": description,
        "tags": ", ".join(tags_list),
        "category_id": category_id,
        "privacy_status": Config.DEFAULT_PRIVACY,
        "reasoning": f"Dynamically derived from filename tokens (Category {category_id}: {YOUTUBE_CATEGORIES.get(category_id, 'Other')}, {len(tags_list)} keywords)."
    }


def generate_video_metadata(video_path: Path, video_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Analyzes video using Google Gemini API to generate title, rich description, 15-20 tags, and category.
    Includes automated fallback across models (gemini-3.8-flash, gemini-2.0-flash, etc.) and
    seamless fallback to dynamic local metadata if API is offline.
    """
    notes = get_companion_notes(video_path)

    if not Config.GEMINI_API_KEY:
        log_event("WARNING", "Gemini", "No GEMINI_API_KEY configured. Using dynamic filename metadata generator (15+ keywords).", video_id)
        return generate_fallback_metadata(video_path, notes)

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=Config.GEMINI_API_KEY)
        file_size_mb = video_path.stat().st_size / (1024 * 1024)
        gemini_file = None

        # Upload for multimodal analysis if size is within reasonable limit (< 1.5GB)
        if file_size_mb <= 1500:
            try:
                log_event("INFO", "Gemini", f"Uploading video ({file_size_mb:.1f} MB) to Gemini Files API for multimodal analysis...", video_id)
                gemini_file = client.files.upload(file=str(video_path))

                log_event("INFO", "Gemini", "Waiting for video file processing in Gemini...", video_id)
                max_wait = 120
                start_time = time.time()
                while gemini_file.state.name == "PROCESSING":
                    if time.time() - start_time > max_wait:
                        log_event("WARNING", "Gemini", "Gemini video processing timed out, proceeding with prompt analysis.", video_id)
                        break
                    time.sleep(3)
                    gemini_file = client.files.get(name=gemini_file.name)

                if gemini_file.state.name == "ACTIVE":
                    log_event("SUCCESS", "Gemini", "Gemini video processing complete. Generating metadata...", video_id)
                else:
                    log_event("WARNING", "Gemini", f"Gemini file state: {gemini_file.state.name}", video_id)
            except Exception as e:
                log_event("WARNING", "Gemini", f"Direct video upload to Gemini failed: {e}. Proceeding with prompt analysis.", video_id)
                gemini_file = None

        prompt = f"""
You are an expert YouTube content strategist, viral video creator, and SEO specialist.
Analyze the provided video (or filename and context if video preview is limited) and generate top-tier, high-performing YouTube metadata tailored specifically to this video's exact subject.

Video Filename: {video_path.name}
File Size: {file_size_mb:.2f} MB
Additional Creator Notes: {notes if notes else 'None provided'}

Generate a JSON object with the following fields:
1. "title": A catchy, high-CTR YouTube title (max 95 characters, captivating, natural, no misleading clickbait, based on the video filename and content).
2. "description": A comprehensive, high-retention YouTube description tailored strictly to this specific video topic. You MUST include:
   - An engaging 2-3 paragraph overview describing the video storyline/context based on the filename/content.
   - A bulleted list of 3-4 key highlights or moments to watch for.
   - A strong Community Call to Action (asking an engaging question for the comments, reminders to Like and Subscribe).
   - 5 to 8 relevant, high-traffic YouTube hashtags at the bottom derived strictly from the topic and keywords.
3. "tags": A comma-separated string of AT LEAST 15-20 highly targeted keyword tags for YouTube search derived directly from this video's subject matter (combining exact phrases, broad keywords, synonyms, and long-tail search queries). NEVER provide fewer than 12 tags.
4. "category_id": The best numeric YouTube Category ID (e.g., 15 for Pets, 10 for Music, 23 for Comedy, 24 for Entertainment, 20 for Gaming, 28 for Science/Tech, 26 for Howto, 22 for People & Blogs, 17 for Sports, 19 for Travel).
5. "reasoning": A brief 1-2 sentence explanation of your title & hook strategy.

CRITICAL: Return ONLY raw, valid JSON with keys: "title", "description", "tags", "category_id", "reasoning". Do not wrap in markdown code blocks if possible.
"""

        contents = []
        if gemini_file and gemini_file.state.name == "ACTIVE":
            contents.append(gemini_file)
        contents.append(prompt)

        # Model fallback chain: try configured model, then standard models
        candidate_models = []
        for m in [Config.GEMINI_MODEL, "gemini-3.8-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]:
            if m and m not in candidate_models:
                candidate_models.append(m)

        response = None
        last_error = None

        for model_name in candidate_models:
            try:
                log_event("INFO", "Gemini", f"Querying Gemini model '{model_name}'...", video_id)
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )
                if response and response.text:
                    log_event("SUCCESS", "Gemini", f"Received metadata response from model '{model_name}'.", video_id)
                    break
            except Exception as model_err:
                last_error = model_err
                log_event("WARNING", "Gemini", f"Model '{model_name}' error: {model_err}. Trying fallback model...", video_id)

        # Clean up uploaded file on Gemini server to save storage
        if gemini_file:
            try:
                client.files.delete(name=gemini_file.name)
            except Exception:
                pass

        if not response or not response.text:
            raise RuntimeError(f"All Gemini models failed. Last error: {last_error}")

        raw_text = response.text.strip()
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```(?:json)?\n?", "", raw_text)
            raw_text = re.sub(r"\n?```$", "", raw_text)

        data = json.loads(raw_text)

        title = data.get("title", clean_filename_to_title(video_path.stem))[:100]
        category_id = str(data.get("category_id", infer_category_id(title)))
        if category_id not in YOUTUBE_CATEGORIES:
            category_id = infer_category_id(title)

        # Parse tags
        raw_tags = data.get("tags", "")
        if isinstance(raw_tags, list):
            tag_items = [str(t).strip() for t in raw_tags if str(t).strip()]
        elif isinstance(raw_tags, str):
            tag_items = [t.strip() for t in raw_tags.split(",") if t.strip()]
        else:
            tag_items = []

        # Ensure at least 15 tags by enriching with dynamic tags derived from title
        if len(tag_items) < 12:
            tag_items = generate_smart_tags(title, category_id, notes, base_tags=tag_items)

        tags_str = ", ".join(tag_items)

        # Ensure rich description
        description = data.get("description", "").strip()
        if len(description) < 120 or "#" not in description:
            description = generate_rich_description(title, category_id, notes, tag_items)

        log_event("SUCCESS", "Gemini", f"Generated Title: '{title}' (Category {category_id}: {YOUTUBE_CATEGORIES.get(category_id, 'Other')}, {len(tag_items)} tags)", video_id)

        return {
            "title": title,
            "description": description,
            "tags": tags_str,
            "category_id": category_id,
            "privacy_status": Config.DEFAULT_PRIVACY,
            "reasoning": data.get("reasoning", "Generated by Gemini AI")
        }

    except Exception as e:
        log_event("ERROR", "Gemini", f"Error generating metadata with Gemini: {e}. Using dynamic filename generator.", video_id)
        return generate_fallback_metadata(video_path, notes)
