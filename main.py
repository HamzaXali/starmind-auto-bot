#!/usr/bin/env python3
"""
StarMind Shorts + Telegram Auto-Publish
Updated version: After building 1080x1920 Short, automatically sends to Telegram channel via sendVideo
Reuses your existing secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID
"""

import os, sys, json, re, hashlib, logging, subprocess, textwrap
from datetime import datetime, timezone
from pathlib import Path
import requests, feedparser
from dateutil import parser as date_parser
from PIL import Image, ImageFilter

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("starmind-shorts-telegram")

SEEN_FILE = Path("seen_articles.json")
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

FEEDS = {
    "tesla": "https://news.google.com/rss/search?q=Tesla+Elon+Musk&hl=en-US&gl=US&ceid=US:en",
    "spacex": "https://news.google.com/rss/search?q=SpaceX+Starship&hl=en-US&gl=US&ceid=US:en",
    "ai_future": "https://news.google.com/rss/search?q=AI+breakthrough+future+technology&hl=en-US&gl=US&ceid=US:en",
    "creators": "https://news.google.com/rss/search?q=MrBeast+YouTube+creator+economy&hl=en-US&gl=US&ceid=US:en",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StarMindDailyShorts/1.0)"}

def load_config():
    logger.info("[1/12] Shorts + Telegram mode")
    yt_id = os.getenv("YOUTUBE_CLIENT_ID")
    yt_secret = os.getenv("YOUTUBE_CLIENT_SECRET")
    yt_refresh = os.getenv("YOUTUBE_REFRESH_TOKEN")
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    tg_channel = os.getenv("TELEGRAM_CHANNEL_ID") or os.getenv("CHANNEL_ID") or "@StarMindDaily"
    
    if not tg_token:
        logger.warning("TELEGRAM_BOT_TOKEN missing - Telegram auto-post disabled")
    else:
        logger.info(f"Telegram: token ***{tg_token[-4:]}, channel {tg_channel}")
    
    has_yt = all([yt_id, yt_secret, yt_refresh])
    if not has_yt:
        logger.warning("YouTube creds missing - will still send to Telegram + artifact")
    
    return {
        "youtube": {"client_id": yt_id, "client_secret": yt_secret, "refresh_token": yt_refresh, "has": has_yt},
        "telegram": {"token": tg_token, "channel": str(tg_channel).strip()}
    }

def fetch_articles():
    logger.info("[3/12] Checking RSS...")
    arts = []
    for topic, url in FEEDS.items():
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            feed = feedparser.parse(r.content)
            for e in feed.entries[:10]:
                try:
                    pub = date_parser.parse(e.published) if hasattr(e, 'published') else datetime.now(timezone.utc)
                except:
                    pub = datetime.now(timezone.utc)
                arts.append({
                    "id": hashlib.sha256((e.get("link","")+e.get("title","")).encode()).hexdigest()[:16],
                    "topic": topic, "title": e.get("title","").strip(),
                    "link": e.get("link","").strip(),
                    "summary": re.sub(r"<[^>]+>", "", e.get("summary",""))[:400],
                    "published": pub
                })
        except Exception as ex:
            logger.error(f"{topic} failed {ex}")
    arts.sort(key=lambda x: x["published"], reverse=True)
    logger.info(f"[4/12] Discovered {len(arts)}")
    return arts

def load_seen():
    if not SEEN_FILE.exists(): return []
    try:
        d = json.loads(SEEN_FILE.read_text())
        return d.get("seen", []) if isinstance(d, dict) else d
    except: return []

def save_seen(s):
    SEEN_FILE.write_text(json.dumps({"seen": s[-500:], "updated_at": datetime.now(timezone.utc).isoformat()}, indent=2))

def filter_eligible(arts, seen):
    logger.info("[5/12] Filtering duplicates...")
    out=[]
    for a in arts:
        h=hashlib.sha256(a["link"].encode()).hexdigest()
        if a["id"] in seen or h in seen or a["link"] in seen: continue
        if len(a["title"])<15: continue
        out.append(a)
    logger.info(f"Eligible {len(out)}/{len(arts)}")
    return out

def generate_script(article):
    logger.info(f"[6/12] Selected: {article['title'][:80]}")
    hook = "Tesla's flying car is REAL and it's not CGI." if "Tesla" in article["title"] else f"{article['title'][:60]}"
    summary = re.sub(r"\s+", " ", article["summary"]).strip()
    tts_text = f"{hook}. {article['title']}. {summary[:220]}. This was unveiled at SpaceX McGregor with cold-gas thrusters. Zero to sixty in under one second. Production targeted for 2028. Would you take it for a spin?"
    tts_text = re.sub(r"[^\w\s.,!?$%\-']", "", tts_text)
    
    seo_title = f"{article['title'][:55]} | Flying Car is REAL! #Shorts"
    hashtags = {"tesla":"#Tesla #ElonMusk #FlyingCar #Shorts", "spacex":"#SpaceX #Shorts", "ai_future":"#AI #FutureTech #Shorts", "creators":"#MrBeast #Shorts"}.get(article["topic"], "#Tech #Shorts")
    desc = f"{article['title']}\n\n{summary}\n\nSource: {article['link']}\n\nWould you drive this? 👇\n\n{hashtags}"
    return {"tts_script": tts_text, "seo_title": seo_title, "description": desc, "hook": hook, "link": article["link"], "topic": article["topic"], "title": article["title"]}

def generate_tts(text, out_path):
    logger.info("[7/12] Generating TTS narration...")
    try:
        import edge_tts, asyncio
        async def _g():
            await edge_tts.Communicate(text, "en-US-AriaNeural").save(str(out_path))
        asyncio.run(_g())
    except Exception as e:
        logger.warning(f"edge-tts failed {e}, using gTTS")
        try:
            from gtts import gTTS
            gTTS(text=text, lang='en').save(str(out_path))
        except:
            subprocess.run(["ffmpeg","-y","-f","lavfi","-i","anullsrc=r=24000:cl=mono","-t","30","-q:a","9","-acodec","libmp3lame",str(out_path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # duration
    try:
        r=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(out_path)], capture_output=True, text=True, check=True)
        dur=float(r.stdout.strip())
    except:
        dur=30.0
    logger.info(f"Audio {dur:.1f}s")
    return dur

def create_bg(image_url, out_path):
    logger.info("[7/12] Creating 1080x1920 background...")
    try:
        resp=requests.get(image_url, timeout=15, headers=HEADERS)
        if resp.status_code==200:
            tmp=OUTPUT_DIR/"temp.jpg"
            tmp.write_bytes(resp.content)
            from PIL import Image
            img=Image.open(tmp).convert("RGB")
        else:
            raise Exception("dl fail")
    except:
        from PIL import Image, ImageDraw
        img=Image.new("RGB",(1080,1920),"#0a0a0a")
        d=ImageDraw.Draw(img)
        for y in range(1920):
            d.line([(0,y),(1080,y)], fill=(10+y//30,10+y//40,20+y//20))
    # resize to 1080x1920
    w,h=img.size
    scale=1080/w
    img_r=img.resize((1080,int(h*scale)), Image.LANCZOS)
    bg=Image.new("RGB",(1080,1920),"#000")
    if img_r.size[1]>=1920:
        top=(img_r.size[1]-1920)//2
        bg=img_r.crop((0,top,1080,top+1920))
    else:
        blurred=img_r.resize((1080,1920), Image.LANCZOS).filter(ImageFilter.GaussianBlur(25))
        bg.paste(blurred,(0,0))
        bg.paste(img_r,(0,(1920-img_r.size[1])//2))
    bg.save(out_path, quality=95)
    return out_path

def create_srt(script, duration, out_path):
    words=script.split()
    chunks=[" ".join(words[i:i+5]) for i in range(0,len(words),5)]
    if not chunks: chunks=["StarMind Daily"]
    cd=duration/len(chunks)
    srt=""
    for i,ch in enumerate(chunks):
        def fmt(t):
            return f"{int(t//3600):02}:{int((t%3600)//60):02}:{int(t%60):02},{int((t-int(t))*1000):03}"
        srt+=f"{i+1}\n{fmt(i*cd)} --> {fmt((i+1)*cd)}\n{ch}\n\n"
    out_path.write_text(srt, encoding="utf-8")
    return out_path

def build_video(bg, audio, srt, out_path, duration):
    logger.info("[8/12] Building Shorts with FFmpeg...")
    if duration>59: duration=59
    srt_esc=str(srt).replace("\\","/").replace(":","\\:")
    filter_c=f"subtitles={srt_esc}:force_style='FontName=Arial,FontSize=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H80000000,BorderStyle=3,Outline=2,Shadow=1,Alignment=2,MarginV=300'"
    cmd=["ffmpeg","-y","-loop","1","-i",str(bg),"-i",str(audio),"-vf",filter_c,"-c:v","libx264","-t",str(duration),"-r","30","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k","-shortest","-movflags","+faststart",str(out_path)]
    try:
        r=subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode!=0:
            logger.warning(f"FFmpeg with subs failed, retry no subs")
            cmd2=["ffmpeg","-y","-loop","1","-i",str(bg),"-i",str(audio),"-c:v","libx264","-t",str(duration),"-r","30","-pix_fmt","yuv420p","-c:a","aac","-shortest","-movflags","+faststart",str(out_path)]
            subprocess.run(cmd2, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info(f"Video ready {out_path} ({out_path.stat().st_size/1e6:.1f} MB)")
        return True
    except Exception as e:
        logger.error(f"Build failed {e}")
        return False

def publish_to_telegram(config, video_path, script_data):
    """
    Sends Shorts video to Telegram channel automatically
    Uses same channel as before: @StarMindDaily
    """
    token = config["telegram"]["token"]
    channel = config["telegram"]["channel"]
    
    if not token:
        logger.warning("[9/12] Telegram token missing - skipping Telegram auto-post")
        return False
    
    logger.info(f"[9/12] Sending Shorts to Telegram {channel} via sendVideo...")
    
    # Caption for Telegram video - max 1024 chars for sendVideo
    tg_caption = f"""🚀 {script_data['title'][:80]}

{script_data['description'][:700]}

▶️ Watch Short: {script_data['link']}

#Shorts #Tesla #ElonMusk #StarMindDaily
"""
    if len(tg_caption) > 1024:
        tg_caption = tg_caption[:1020] + "..."
    
    url = f"https://api.telegram.org/bot{token}/sendVideo"
    
    try:
        with open(video_path, 'rb') as video_file:
            files = {'video': video_file}
            data = {
                'chat_id': channel,
                'caption': tg_caption,
                'parse_mode': 'Markdown',
                'supports_streaming': True,
                'width': 1080,
                'height': 1920,
            }
            resp = requests.post(url, data=data, files=files, timeout=60)
            result = resp.json()
            
            if result.get("ok"):
                msg_id = result["result"]["message_id"]
                logger.info(f"[10/12] Telegram sendVideo SUCCESS: message_id={msg_id} in {channel}")
                return True
            else:
                logger.error(f"[10/12] Telegram sendVideo FAILED: {result}")
                logger.error(f"  Description: {result.get('description')}")
                # Common fixes
                if "chat not found" in result.get("description",""):
                    logger.error(f"  FIX: Channel ID {channel} wrong. Use @StarMindDaily or -100... ID. Bot must be admin.")
                if "not enough rights" in result.get("description","").lower():
                    logger.error(f"  FIX: Bot not admin in {channel}. Add as admin with Post Messages.")
                return False
    except Exception as e:
        logger.error(f"[10/12] Telegram exception: {e}", exc_info=False)
        return False

def main():
    is_test = "--test" in sys.argv
    config = load_config()
    
    seen = load_seen()
    # reuse fetch logic
    import requests as req
    arts = []
    for topic, url in FEEDS.items():
        try:
            r = req.get(url, headers=HEADERS, timeout=15)
            feed = feedparser.parse(r.content)
            for e in feed.entries[:10]:
                arts.append({
                    "id": hashlib.sha256((e.get("link","")+e.get("title","")).encode()).hexdigest()[:16],
                    "topic": topic, "title": e.get("title","").strip(),
                    "link": e.get("link","").strip(),
                    "summary": re.sub(r"<[^>]+>", "", e.get("summary",""))[:400],
                    "published": datetime.now(timezone.utc)
                })
        except Exception as ex:
            logger.error(f"{topic} {ex}")
    arts.sort(key=lambda x: x["published"], reverse=True)
    logger.info(f"[4/12] Found {len(arts)}")
    
    # filter
    eligible=[]
    for a in arts:
        h=hashlib.sha256(a["link"].encode()).hexdigest()
        if a["id"] in seen or h in seen or a["link"] in seen: continue
        eligible.append(a)
    logger.info(f"[5/12] Eligible {len(eligible)}")
    
    if not eligible:
        logger.warning("No new articles")
        sys.exit(0)
    
    selected = eligible[0]
    script_data = generate_script(selected)
    
    # Build video
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    prompt = requests.utils.quote(f"futuristic {selected['topic']} {selected['title'][:80]} cinematic vertical")[0:200]
    img_url = f"https://image.pollinations.ai/prompt/{prompt}?width=1024&height=1920&nologo=true"
    
    bg = OUTPUT_DIR / f"bg_{ts}.jpg"
    audio = OUTPUT_DIR / f"audio_{ts}.mp3"
    srt = OUTPUT_DIR / f"cap_{ts}.srt"
    video = OUTPUT_DIR / f"StarMind_Short_{ts}.mp4"
    
    create_bg(img_url, bg)
    dur = generate_tts(script_data["tts_script"], audio)
    create_srt(script_data["tts_script"], dur, srt)
    ok_build = build_video(bg, audio, srt, video, dur)
    
    if not ok_build:
        logger.error("Build failed")
        sys.exit(5)
    
    # Auto-post to Telegram (same channel)
    tg_ok = publish_to_telegram(config, video, script_data)
    
    # Also try YouTube if creds present (optional)
    yt_ok = False
    if config["youtube"]["has"]:
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
            import google.auth.transport.requests
            creds = Credentials(None, refresh_token=config["youtube"]["refresh_token"], token_uri="https://oauth2.googleapis.com/token", client_id=config["youtube"]["client_id"], client_secret=config["youtube"]["client_secret"], scopes=["https://www.googleapis.com/auth/youtube.upload"])
            creds.refresh(google.auth.transport.requests.Request())
            youtube = build("youtube","v3",credentials=creds)
            body={"snippet":{"title":script_data["seo_title"][:95],"description":script_data["description"],"tags":["Shorts","Tesla"]},"status":{"privacyStatus":"public","selfDeclaredMadeForKids":False}}
            media=MediaFileUpload(str(video), mimetype="video/mp4", resumable=True)
            req=youtube.videos().insert(part="snippet,status",body=body,media_body=media)
            resp=None
            while resp is None:
                _, resp = req.next_chunk()
            logger.info(f"YouTube uploaded: https://youtube.com/shorts/{resp['id']}")
            yt_ok=True
        except Exception as e:
            logger.warning(f"YouTube upload skipped/failed: {e}")
    
    # Mark seen ONLY after at least Telegram or build success
    if ok_build and (tg_ok or not config["telegram"]["token"] or yt_ok):
        h=hashlib.sha256(selected["link"].encode()).hexdigest()
        seen.extend([selected["id"], h, selected["link"]])
        save_seen(seen)
        logger.info("[11/12] Marked seen")
    
    if tg_ok:
        logger.info(f"[12/12] SUCCESS - Short built + sent to Telegram {config['telegram']['channel']}")
    else:
        if ok_build:
            logger.info(f"[12/12] SUCCESS - Short built at {video} (Telegram failed or no token, but video ready)")
        else:
            logger.error("[12/12] FAILED")
            sys.exit(5)

if __name__ == "__main__":
    main()
