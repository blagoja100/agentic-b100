"""
Cat Script and Prompt Generator using Google Gemini.
Analyzes the downloaded short video (speech, visual events, humor, message)
and creates:
1. Exact summary / transcription of what was said in the video.
2. A punchy, 10-second script for an adorable cat explaining it (~25-35 words).
3. A cinematographic prompt for Google Veo video generation.
"""

import os
import re
import time
import json
from pathlib import Path
from typing import Dict, Any, Optional
from config import Config
from db import log_event


def generate_cat_explanation(
    video_path: Optional[Path],
    title: str,
    job_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Analyzes video content using Gemini and produces:
    - transcription_summary
    - cat_script (10-second explanation)
    - veo_prompt (Veo 2.0 prompt)
    """
    if not Config.GEMINI_API_KEY:
        log_event("WARNING", "Gemini", "No GEMINI_API_KEY set; using dynamic rule-based cat script.", job_id)
        return _generate_fallback_cat_script(title)

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=Config.GEMINI_API_KEY)
        gemini_file = None

        if video_path and video_path.exists():
            file_size_mb = video_path.stat().st_size / (1024 * 1024)
            if file_size_mb <= 200:
                try:
                    log_event("INFO", "Gemini", f"Uploading video ({file_size_mb:.2f} MB) to Gemini for multimodal understanding...", job_id)
                    gemini_file = client.files.upload(file=str(video_path))
                    
                    # Wait for processing
                    start_time = time.time()
                    while gemini_file.state.name == "PROCESSING":
                        if time.time() - start_time > 60:
                            break
                        time.sleep(2)
                        gemini_file = client.files.get(name=gemini_file.name)

                    if gemini_file.state.name == "ACTIVE":
                        log_event("SUCCESS", "Gemini", "Video processed by Gemini multimodal engine.", job_id)
                except Exception as upload_err:
                    log_event("WARNING", "Gemini", f"Gemini video upload skipped: {upload_err}", job_id)
                    gemini_file = None

        system_instruction = (
            "You are the world's most charismatic, witty, viral AI Cat Explainer. "
            "Your job is to watch short-form videos (Reels, TikToks, Shorts) and explain what was said "
            "in an entertaining, crystal-clear 10-second monologue delivered by a talking cat."
        )

        prompt = f"""
Analyze this video (or title/context: "{title}").

Your goals:
1. Provide a concise 2-sentence summary/transcription of whatever was said or happened in the video.
2. Write a 10-SECOND CAT EXPLANATION SCRIPT (strictly between 25 and 35 words so it fits exactly in 10 seconds).
   - Persona: A smart, sassy, expressive cat talking directly to humans.
   - Start with a fun cat hook (e.g. "Meow! Listen up humans,", "Purr-fect timing! Here's the tea:", "Pause your scrolls, hairless apes!").
   - Deliver the actual facts or message of the video with funny cat humor.
3. Write a high-definition prompt for Google Veo (Veo 2.0 text-to-video model) that will generate an expressive 10-second video of this cat talking.
   - Describe the cat breed (e.g. fluffy ginger tabby with round reading glasses, or a tuxedo cat in a tiny tie).
   - Setting: News desk / podcast studio / cozy library.
   - Action: Cat speaking animatedly straight to camera, expressive mouth movement, whiskers twitching, cinematic lighting, vertical 9:16 format, hyper-realistic fur textures, 4k resolution.

Return ONLY a valid JSON object with keys:
- "transcription": "...",
- "cat_script": "...",
- "veo_prompt": "...",
- "cat_character": "..."
"""

        contents = []
        if gemini_file and gemini_file.state.name == "ACTIVE":
            contents.append(gemini_file)
        contents.append(prompt)

        candidate_models = [Config.GEMINI_MODEL, "gemini-3.8-flash", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
        chosen_response = None

        for model in candidate_models:
            if not model:
                continue
            try:
                log_event("INFO", "Gemini", f"Generating cat script with model '{model}'...", job_id)
                response = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json"
                    )
                )
                if response and response.text:
                    chosen_response = response.text
                    break
            except Exception as err:
                log_event("WARNING", "Gemini", f"Model {model} failed: {err}", job_id)

        # Cleanup file on Gemini servers
        if gemini_file:
            try:
                client.files.delete(name=gemini_file.name)
            except Exception:
                pass

        if chosen_response:
            data = json.loads(chosen_response)
            log_event("SUCCESS", "Gemini", f"Cat Script Generated: \"{data.get('cat_script', '')[:60]}...\"", job_id)
            return {
                "transcription": data.get("transcription", f"Summary of {title}"),
                "cat_script": data.get("cat_script", ""),
                "veo_prompt": data.get("veo_prompt", ""),
                "cat_character": data.get("cat_character", "Ginger Tabby Explainer")
            }

    except Exception as e:
        log_event("ERROR", "Gemini", f"Cat script generation error: {e}. Falling back to default script.", job_id)

    return _generate_fallback_cat_script(title)


def _generate_fallback_cat_script(title: str) -> Dict[str, Any]:
    """Generates a dynamic fallback 10-second cat script without external API."""
    clean_title = re.sub(r"[_\-]+", " ", title).strip()
    
    cat_script = (
        f"Meow! Listen up humans! In this video about {clean_title}, "
        f"the main takeaway is super simple: pay close attention, take smart notes, "
        f"and never let your treats get cold! Purr-fect advice!"
    )
    
    veo_prompt = (
        f"Cinematic vertical 9:16 video of a cute, fluffy ginger tabby cat wearing tiny round spectacles "
        f"sitting at a miniature wooden desk with a microphone. The cat is speaking animatedly directly to the camera, "
        f"mouth moving naturally as if talking, blinking, expressive head gestures, explaining {clean_title}. "
        f"Warm studio key lighting, depth of field, photorealistic 4k fur texture, 10 seconds."
    )

    return {
        "transcription": f"Video discussing '{clean_title}'. Highlights essential tips and insights.",
        "cat_script": cat_script,
        "veo_prompt": veo_prompt,
        "cat_character": "Ginger Tabby Explainer"
    }
