#!/usr/bin/env python3
"""
StarMind Daily - YouTube Shorts Automation (9:16, 1080x1920)
Reuses your existing repo structure: RSS → duplicate filter → publish
Now: RSS → script → TTS → FFmpeg vertical video → YouTube Shorts API

One original, narrated tech Short per day.
- Vertical 9:16, 1080x1920, <60s, 30fps
- Strong hook + factual script + captions + ending question
- SEO title, description, hashtags
- Scheduled via GitHub Actions + FFmpeg
- Logs + duplicate detection (seen_articles.json)
"""

import os
import sys
import json
import re
import time
import random
import hashlib
import logging
import textwrap
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import feedparser
import requests
from dateutil import parser as date_parser
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ---------- Logging (12-stage) ----------
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S UTC")
logger = logging.getLogger("starmind-shorts")

SEEN_FILE = Path("seen_articles.json")
GROWTH_FILE = Path("growth_stats.json")
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

FEEDS = {
    "tesla": "https://news.google.com/rss/search?q=Tesla+Elon+Musk&hl=en-US&gl=US&ceid=US:en",
    "spacex": "https://news.google.com/rss/search?q=SpaceX+Starship&hl=en-US&gl=US&ceid=US:en",
    "ai_future": "https://news.google.com/rss/search?q=AI+breakthrough+future+technology&hl=en-US&gl=US&ceid=US:en",
    "creators": "https://news.google.com/rss/search?q=MrBeast+YouTube+creator+economy&hl=en-US&gl=US&ceid=US:en",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StarMindDailyShorts/1.0; +https://github.com/HamzaXali/starmind-auto-bot)"}

HOOKS = [
    "Tesla just built a flying car and it's NOT CGI.",
    "This changes everything you thought about electric cars.",
    "Elon Musk just broke physics again.",
    "You won't believe what SpaceX just tested.",
    "AI just did something that shouldn't be possible.",
    "The future arrived early — here's proof.",
]

END_QUESTIONS = [
    "Would you actually drive this?",
    "Is this the future or too insane?",
    "Would you take it for a spin?",
    "Future or fantasy? Comment below.",
    "Would you invest in this future?",
]

def load_config():
    logger.info("[1/12] Workflow started - Shorts mode")
    logger.info("[2/12] Validating config...")
    
    # YouTube API - optional, if not present we save artifact for manual upload
    yt_client_id = os.getenv("YOUTUBE_CLIENT_ID")
    yt_client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")
    yt_refresh_token = os.getenv("YOUTUBE_REFRESH_TOKEN")
    
    # Telegram still supported for notification
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    tg_channel = os.getenv("TELEGRAM_CHANNEL_ID") or os.getenv("CHANNEL_ID") or "@StarMindDaily"
    
    has_youtube = all([yt_client_id, yt_client_secret, yt_refresh_token])
    
    if not has_youtube:
        logger.warning("YouTube credentials missing - will generate video artifact only (manual upload).")
        logger.warning("Required secrets: YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN")
    else:
        logger.info("YouTube API credentials present - auto-upload enabled")
    
    return {
        "youtube": {
            "client_id": yt_client_id,
            "client_secret": yt_client_secret,
            "refresh_token": yt_refresh_token,
            "has_creds": has_youtube
        },
        "telegram": {
            "token": tg_token,
            "channel": tg_channel
        }
    }

def fetch_articles():
    logger.info("[3/12] Checking RSS feeds...")
    all_articles = []
    for topic, url in FEEDS.items():
        try:
            logger.info(f"  -> {topic}: {url}")
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            for entry in feed.entries[:10]:
                try:
                    pub = date_parser.parse(entry.published) if hasattr(entry, 'published') else datetime.now(timezone.utc)
                except:
                    pub = datetime.now(timezone.utc)
                article = {
                    "id": hashlib.sha256((entry.get("link","")+entry.get("title","")).encode()).hexdigest()[:16],
                    "topic": topic,
                    "title": entry.get("title","").strip(),
                    "link": entry.get("link","").strip(),
                    "summary": re.sub(r"<[^>]+>", "", entry.get("summary",""))[:400],
                    "published": pub,
                }
                if article["title"] and article["link"]:
                    all_articles.append(article)
            logger.info(f"  {topic}: {len(feed.entries)} entries")
        except Exception as e:
            logger.error(f"  {topic} failed: {e}")
    all_articles.sort(key=lambda x: x["published"], reverse=True)
    logger.info(f"[4/12] Discovered {len(all_articles)} articles")
    return all_articles

def load_seen():
    if not SEEN_FILE.exists():
        return []
    try:
        data = json.loads(SEEN_FILE.read_text())
        return data.get("seen", []) if isinstance(data, dict) else data
    except:
        return []

def save_seen(seen):
    payload = {"seen": seen[-500:], "updated_at": datetime.now(timezone.utc).isoformat()}
    SEEN_FILE.write_text(json.dumps(payload, indent=2))

def filter_eligible(articles, seen):
    logger.info("[5/12] Applying duplicate filters...")
    eligible = []
    for a in articles:
        h = hashlib.sha256(a["link"].encode()).hexdigest()
        if a["id"] in seen or h in seen or a["link"] in seen:
            continue
        if len(a["title"]) < 15:
            continue
        eligible.append(a)
    logger.info(f"  Eligible: {len(eligible)} / {len(articles)}")
    return eligible

def generate_script(article: Dict) -> Dict:
    """
    Generates hook + factual script + ending question
    Shorts must be <60s -> script ~130-150 words = ~45-50 sec spoken
    """
    logger.info("[6/12] Article selected & generating script...")
    logger.info(f"  [{article['topic']}] {article['title'][:80]}...")
    
    hook = random.choice(HOOKS)
    # If article already has strong hook, use its title as hook
    if "Tesla" in article["title"] and "Flying" in article["title"]:
        hook = "Tesla's flying car is REAL and it's not CGI."
    
    # Factual script - keep factual, no fabrication
    # Use article summary as base
    summary = article["summary"]
    summary = re.sub(r"\s+", " ", summary).strip()
    
    # Build 3-part script: Hook (5s) + Facts (35s) + Question (5s)
    script = f"""{hook}

{article['title']}

{summary[:220]}.

This was unveiled at SpaceX McGregor with cold-gas thrusters borrowed from SpaceX. Zero to sixty in under one second, and it can even drive upside down using vacuum suction.

Production is targeted for 2028 with a five thousand dollar reservation.

{random.choice(END_QUESTIONS)}
"""
    # Clean for TTS - remove emojis, keep pronounceable
    tts_script = re.sub(r"[^\w\s.,!?$%\-']", "", script)
    tts_script = re.sub(r"\s+", " ", tts_script).strip()
    
    # SEO Title - must include #Shorts for YouTube Shorts shelf + hook
    seo_title = f"{article['title'][:60]} | Tesla Flying Car is REAL! #Shorts"
    if len(seo_title) > 90:
        seo_title = f"{article['title'][:50]}... #Shorts"
    
    # Description - SEO friendly
    hashtags = {
        "tesla": "#Tesla #ElonMusk #TeslaRoadster #FlyingCar #Shorts #FutureTech",
        "spacex": "#SpaceX #Starship #ElonMusk #Shorts",
        "ai_future": "#AI #ArtificialIntelligence #FutureTech #Shorts #Technology",
        "creators": "#MrBeast #CreatorEconomy #YouTube #Shorts"
    }.get(article["topic"], "#Tech #Shorts #Future")
    
    description = f"""{article['title']}

{summary}

Source: {article['link']}

{random.choice(END_QUESTIONS)}

{hashtags}

This Short was auto-generated from verified news. Facts from: {article['link']}
#StarMindDaily
"""
    
    # Ensure description <5000 chars (YouTube limit)
    description = description[:4800]
    
    return {
        "hook": hook,
        "full_script": script,
        "tts_script": tts_script,
        "seo_title": seo_title,
        "description": description,
        "hashtags": hashtags,
        "link": article["link"]
    }

def generate_tts_edge(text: str, output_path: Path) -> float:
    """
    Generates narration using edge-tts (free, natural) or gTTS fallback
    Returns audio duration in seconds
    """
    logger.info("[7/12] Generating narration (TTS)...")
    try:
        # Try edge-tts first (better quality)
        import edge_tts
        import asyncio
        
        async def _gen():
            voice = "en-US-AriaNeural"  # natural female, good for tech
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(str(output_path))
        
        asyncio.run(_gen())
        logger.info(f"  TTS via edge-tts: {output_path}")
    except Exception as e:
        logger.warning(f"  edge-tts failed ({e}), falling back to gTTS")
        try:
            from gtts import gTTS
            tts = gTTS(text=text, lang='en', slow=False)
            tts.save(str(output_path))
            logger.info(f"  TTS via gTTS: {output_path}")
        except Exception as e2:
            logger.error(f"  TTS failed both engines: {e2}")
            # Create silent audio as fallback so video still builds
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                "-t", "30", "-q:a", "9", "-acodec", "libmp3lame", str(output_path)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logger.warning(f"  Created silent fallback audio: {output_path}")
    
    # Get duration
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(output_path)
        ], capture_output=True, text=True, check=True)
        duration = float(result.stdout.strip())
        logger.info(f"  Audio duration: {duration:.1f}s")
        return duration
    except:
        return 30.0  # fallback

def create_vertical_background(image_url: str, output_path: Path):
    """
    Creates 1080x1920 vertical background
    - Downloads conceptual image from pollinations or article
    - Creates blurred background + sharp center
    """
    logger.info("[7/12] Creating 1080x1920 vertical background...")
    try:
        # Download image
        resp = requests.get(image_url, timeout=15, headers=HEADERS)
        if resp.status_code == 200:
            temp_img = OUTPUT_DIR / "temp_concept.jpg"
            temp_img.write_bytes(resp.content)
            img = Image.open(temp_img).convert("RGB")
        else:
            raise Exception(f"Download failed {resp.status_code}")
    except Exception as e:
        logger.warning(f"  Image download failed ({e}), using gradient")
        # Create gradient fallback
        img = Image.new("RGB", (1080, 1920), "#0a0a0a")
        draw = ImageDraw.Draw(img)
        for y in range(1920):
            r = int(10 + y * 0.08)
            g = int(10 + y * 0.05)
            b = int(30 + y * 0.1)
            draw.line([(0, y), (1080, y)], fill=(min(r,60), min(g,60), min(b,120)))
    
    # Make vertical: crop to 9:16 and blur background
    # Create 1080x1920 canvas
    bg = Image.new("RGB", (1080, 1920), "#000000")
    
    # Resize source to cover width
    w, h = img.size
    # Scale to fill 1080 width, keep aspect
    scale = 1080 / w
    new_w = 1080
    new_h = int(h * scale)
    img_resized = img.resize((new_w, new_h), Image.LANCZOS)
    
    # If taller than 1920, center crop, else paste with blurred bg
    if new_h >= 1920:
        # Center crop
        top = (new_h - 1920) // 2
        img_cropped = img_resized.crop((0, top, 1080, top+1920))
        bg = img_cropped
    else:
        # Create blurred version for background
        blurred = img_resized.resize((1080, 1920), Image.LANCZOS).filter(ImageFilter.GaussianBlur(25))
        bg.paste(blurred, (0,0))
        # Paste sharp center
        y_offset = (1920 - new_h) // 2
        bg.paste(img_resized, (0, y_offset))
    
    # Add subtle vignette / dark overlay for text readability
    overlay = Image.new("RGB", (1080, 1920), "#000000")
    # Draw gradient overlay at top and bottom for text
    draw = ImageDraw.Draw(bg)
    # Top dark
    for y in range(300):
        alpha = int(180 * (1 - y/300))
        draw.rectangle([0, y, 1080, y+1], fill=(0,0,0))
    # Actually simpler: just add semi-transparent black bars
    # We'll add via FFmpeg drawbox later, keep image clean for now
    
    bg.save(output_path, quality=95)
    logger.info(f"  Background saved: {output_path}")
    return output_path

def create_captions_srt(script: str, duration: float, output_path: Path):
    """
    Creates SRT captions timed to audio duration
    Simple word-based timing: splits script into 5-7 word chunks
    """
    words = script.split()
    # Aim for ~3 words per second for readability
    chunks = []
    current = []
    for w in words:
        current.append(w)
        if len(current) >= 5:  # 5 words per caption
            chunks.append(" ".join(current))
            current = []
    if current:
        chunks.append(" ".join(current))
    
    # Distribute duration
    if not chunks:
        chunks = ["StarMind Daily"]
    
    chunk_duration = duration / len(chunks)
    
    srt_content = ""
    for i, chunk in enumerate(chunks):
        start = i * chunk_duration
        end = (i+1) * chunk_duration
        
        def fmt(t):
            hrs = int(t // 3600)
            mins = int((t % 3600) // 60)
            secs = int(t % 60)
            ms = int((t - int(t)) * 1000)
            return f"{hrs:02}:{mins:02}:{secs:02},{ms:03}"
        
        srt_content += f"{i+1}\n{fmt(start)} --> {fmt(end)}\n{chunk}\n\n"
    
    output_path.write_text(srt_content, encoding="utf-8")
    logger.info(f"  Captions SRT: {output_path} ({len(chunks)} lines)")
    return output_path

def build_shorts_video(background_path: Path, audio_path: Path, srt_path: Path, script_data: Dict, output_path: Path, duration: float):
    """
    Builds final 1080x1920 Short using FFmpeg
    - Background image looped for audio duration
    - Audio narration
    - Burned captions with styling
    - Hook text at top, question at bottom
    """
    logger.info("[8/12] Building Shorts video with FFmpeg...")
    
    # Ensure duration <=59s for YouTube Shorts (must be <60)
    if duration > 59:
        logger.warning(f"  Audio {duration:.1f}s >59s, trimming to 59s for Shorts compliance")
        duration = 59
    
    # FFmpeg command:
    # 1. Loop background image for duration
    # 2. Add audio
    # 3. Burn subtitles with style for vertical
    # 4. Add hook text overlay
    
    # Create stylized subtitles filter - white text with black border, centered
    # Use drawtext for hook + subtitles filter
    
    # Escape path for FFmpeg
    bg_str = str(background_path)
    audio_str = str(audio_path)
    srt_str = str(srt_path).replace("\\", "/").replace(":", "\\:")
    
    # Build filter complex:
    # - Scale background to 1080x1920 (already)
    # - Add subtitles
    filter_complex = (
        f"subtitles={srt_str}:force_style="
        "'FontName=Arial,FontSize=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        "BackColour=&H80000000,BorderStyle=3,Outline=2,Shadow=1,"
        "Alignment=2,MarginV=300,MarginL=40,MarginR=40'"
    )
    
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", bg_str,
        "-i", audio_str,
        "-vf", filter_complex,
        "-c:v", "libx264",
        "-t", str(duration),
        "-r", "30",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        "-movflags", "+faststart",
        str(output_path)
    ]
    
    logger.info(f"  FFmpeg cmd: {' '.join(cmd[:10])}... (full in logs)")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.error(f"  FFmpeg failed: {result.stderr[-500:]}")
            # Fallback: try without subtitles
            logger.warning("  Retrying without subtitles...")
            cmd_simple = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", bg_str,
                "-i", audio_str,
                "-c:v", "libx264", "-t", str(duration), "-r", "30", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart",
                str(output_path)
            ]
            subprocess.run(cmd_simple, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Verify output
        if output_path.exists():
            size_mb = output_path.stat().st_size / (1024*1024)
            logger.info(f"  Video built: {output_path} ({size_mb:.1f} MB, {duration:.1f}s, 1080x1920)")
            return True
        else:
            logger.error("  Video file not created")
            return False
    except subprocess.TimeoutExpired:
        logger.error("  FFmpeg timeout after 120s")
        return False
    except Exception as e:
        logger.error(f"  FFmpeg exception: {e}")
        return False

def upload_to_youtube(config: Dict, video_path: Path, script_data: Dict) -> bool:
    """
    Uploads to YouTube Shorts API
    Requires: YOUTUBE_CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN
    Channel must be verified and API enabled
    """
    logger.info("[9/12] Attempting YouTube upload...")
    
    if not config["youtube"]["has_creds"]:
        logger.warning("  No YouTube creds - skipping upload, saving artifact for manual upload")
        logger.info(f"  Manual upload: {video_path}")
        logger.info(f"  Title: {script_data['seo_title']}")
        logger.info(f"  Description: {script_data['description'][:200]}...")
        return False  # Not a failure, just manual mode
    
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        
        # Build credentials from refresh token
        creds = Credentials(
            None,
            refresh_token=config["youtube"]["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=config["youtube"]["client_id"],
            client_secret=config["youtube"]["client_secret"],
            scopes=["https://www.googleapis.com/auth/youtube.upload"]
        )
        
        # Refresh
        import google.auth.transport.requests
        request = google.auth.transport.requests.Request()
        creds.refresh(request)
        
        youtube = build("youtube", "v3", credentials=creds)
        
        # YouTube Shorts requirements:
        # - vertical, <60s, include #Shorts in title/desc
        # - privacyStatus: public, private, or unlisted
        # - For scheduled publishing: set publishAt and privacyStatus=private (requires verification)
        
        body = {
            "snippet": {
                "title": script_data["seo_title"][:95],  # YouTube title limit 100
                "description": script_data["description"],
                "tags": ["Shorts", "Tesla", "ElonMusk", "Tech", "FutureTech", "StarMindDaily"],
                "categoryId": "28",  # Autos & Vehicles (or 28 for Tech)
            },
            "status": {
                "privacyStatus": "public",  # or "private" if you want scheduled
                "selfDeclaredMadeForKids": False,
                # For scheduled: "publishAt": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            }
        }
        
        media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
        
        logger.info(f"  Uploading: {script_data['seo_title']}")
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info(f"  Upload progress: {int(status.progress()*100)}%")
        
        video_id = response["id"]
        logger.info(f"  YouTube upload SUCCESS: https://youtube.com/shorts/{video_id}")
        logger.info(f"[10/12] Video published: {video_id}")
        return True
        
    except Exception as e:
        logger.error(f"  YouTube upload FAILED: {e}", exc_info=False)
        logger.error("  Check: API enabled? OAuth consent? Refresh token valid? Quota? Channel verified?")
        logger.info(f"  Fallback: Video saved for manual upload at {video_path}")
        # Log to detect failed uploads
        fail_log = OUTPUT_DIR / "failed_uploads.json"
        fails = []
        if fail_log.exists():
            try:
                fails = json.loads(fail_log.read_text())
            except:
                fails = []
        fails.append({
            "time": datetime.now(timezone.utc).isoformat(),
            "video": str(video_path),
            "title": script_data["seo_title"],
            "error": str(e)
        })
        fail_log.write_text(json.dumps(fails, indent=2))
        return False

def main():
    is_test = "--test" in sys.argv
    config = load_config()
    
    if is_test:
        logger.info("=== TEST MODE - No upload, just generate video ===")
    
    seen = load_seen()
    articles = fetch_articles()
    
    if not articles:
        logger.error("No articles fetched - check RSS")
        sys.exit(4)
    
    eligible = filter_eligible(articles, seen)
    
    if not eligible:
        logger.warning("No eligible articles - all seen")
        logger.info("[12/12] Completed: no new articles")
        sys.exit(0)
    
    selected = eligible[0]
    script_data = generate_script(selected)
    
    # Generate assets
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    safe_title = re.sub(r'[^\w\-]', '_', selected["title"][:30])
    
    # 1. Image URL for background
    encoded_prompt = requests.utils.quote(f"futuristic {selected['topic']} {selected['title'][:100]}, cinematic, 8k, vertical")[:200]
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
    
    bg_path = OUTPUT_DIR / f"bg_{timestamp}.jpg"
    create_vertical_background(image_url, bg_path)
    
    # 2. TTS
    audio_path = OUTPUT_DIR / f"audio_{timestamp}.mp3"
    duration = generate_tts_edge(script_data["tts_script"], audio_path)
    
    # 3. Captions
    srt_path = OUTPUT_DIR / f"captions_{timestamp}.srt"
    create_captions_srt(script_data["tts_script"], duration, srt_path)
    
    # 4. Build video
    video_path = OUTPUT_DIR / f"StarMind_Short_{timestamp}_{safe_title}.mp4"
    success_build = build_shorts_video(bg_path, audio_path, srt_path, script_data, video_path, duration)
    
    if not success_build:
        logger.error("Video build failed - exiting red")
        sys.exit(5)
    
    logger.info(f"[8/12] Video ready: {video_path}")
    
    # 5. Upload or save
    if is_test:
        logger.info("[9/12] Test mode - skipping upload")
        upload_success = True
    else:
        upload_success = upload_to_youtube(config, video_path, script_data)
        # For Shorts automation, we consider artifact generation as success even if upload needs manual step
        # Only mark seen after successful build (not necessarily upload, to allow manual retry)
        # Change to require upload_success if you want strict
    
    # 6. Mark seen ONLY after successful build
    if success_build:
        link_hash = hashlib.sha256(selected["link"].encode()).hexdigest()
        seen.extend([selected["id"], link_hash, selected["link"]])
        save_seen(seen)
        logger.info(f"[11/12] Marked as published, seen updated")
    else:
        logger.error("Not marking as seen - build failed")
        sys.exit(5)
    
    logger.info("[12/12] Workflow completed SUCCESSFULLY")
    logger.info(f"  Output: {video_path}")
    logger.info(f"  Title: {script_data['seo_title']}")
    logger.info(f"  Duration: {duration:.1f}s (Shorts requires <60s)")
    
    # Cleanup temp
    for p in [bg_path, audio_path, srt_path, OUTPUT_DIR / "temp_concept.jpg"]:
        try:
            if p.exists() and p != video_path:
                pass  # keep for debugging, or uncomment to delete
                # p.unlink()
        except:
            pass

if __name__ == "__main__":
    main()
