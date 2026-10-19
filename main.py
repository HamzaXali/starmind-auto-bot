#!/usr/bin/env python3
"""
StarMind Shorts - REALISTIC VIDEO + TELEGRAM AUTO-POST (FINAL FIX)
Fixes Video nok (1 color screen):
- Multi-source realistic images (Unsplash real photos, not gradient)
- Ken Burns zoom motion so static becomes video
- Cleans &nbsp; and repetition bug (MrBeast x3)

Audio ok, Video now ok
"""

import os, sys, json, re, hashlib, logging, subprocess, random, html
from datetime import datetime, timezone
from pathlib import Path
import requests, feedparser
from dateutil import parser as date_parser
from PIL import Image, ImageFilter, ImageDraw

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("starmind-final")

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)
SEEN_FILE = Path("seen_articles.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (StarMindDaily/1.0)"}
FEEDS = {
    "tesla": "https://news.google.com/rss/search?q=Tesla+Elon+Musk&hl=en-US&gl=US&ceid=US:en",
    "spacex": "https://news.google.com/rss/search?q=SpaceX+Starship&hl=en-US&gl=US&ceid=US:en",
    "ai_future": "https://news.google.com/rss/search?q=AI+breakthrough+future+technology&hl=en-US&gl=US&ceid=US:en",
    "creators": "https://news.google.com/rss/search?q=MrBeast+YouTube+creator+economy&hl=en-US&gl=US&ceid=US:en",
}

def clean_text(t):
    t = html.unescape(t)
    t = re.sub(r"&[a-z]+;", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # dedup sentences
    parts = t.split(". ")
    seen=set(); uniq=[]
    for p in parts:
        low=p.strip().lower()
        if low not in seen and len(low)>10:
            seen.add(low); uniq.append(p.strip())
    return ". ".join(uniq)

def load_config():
    logger.info("[1/12] Realistic Shorts + Telegram")
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    tg_channel = os.getenv("TELEGRAM_CHANNEL_ID") or os.getenv("CHANNEL_ID") or "@StarMindDaily"
    logger.info(f"Channel {tg_channel}, token ***{tg_token[-4:] if tg_token else 'MISSING'}")
    return {"telegram":{"token":tg_token, "channel":str(tg_channel).strip()}, "youtube":{"has":False}}

def fetch_articles():
    arts=[]
    for topic,url in FEEDS.items():
        try:
            r=requests.get(url, headers=HEADERS, timeout=15)
            feed=feedparser.parse(r.content)
            for e in feed.entries[:10]:
                arts.append({"id":hashlib.sha256((e.get("link","")+e.get("title","")).encode()).hexdigest()[:16],
                             "topic":topic,"title":clean_text(e.get("title","")),"link":e.get("link","").strip(),
                             "summary":clean_text(e.get("summary",""))[:400],"published":datetime.now(timezone.utc)})
        except Exception as ex:
            logger.error(f"{topic} {ex}")
    arts.sort(key=lambda x: x["published"], reverse=True)
    logger.info(f"[4/12] Found {len(arts)}")
    return arts

def load_seen():
    if not SEEN_FILE.exists(): return []
    try:
        d=json.loads(SEEN_FILE.read_text()); return d.get("seen",[]) if isinstance(d,dict) else d
    except: return []
def save_seen(s):
    SEEN_FILE.write_text(json.dumps({"seen":s[-500:],"updated_at":datetime.now(timezone.utc).isoformat()},indent=2))

def generate_script(article):
    title = clean_text(article["title"])
    title = re.sub(r"\s*-\s*.*Tech.*$","",title).strip()
    title = re.sub(r"\s*-\s*.*Buzz.*$","",title).strip()
    summary = clean_text(article["summary"])
    # Fix repetition - take only first 2 sentences of summary
    summary_sent = ". ".join(summary.split(". ")[:2])
    hook = f"Breaking: {title[:70]}" if len(title)>10 else "This changes everything"
    script = f"{hook}. {title}. {summary_sent}. This development is reshaping the tech industry. Production and impact are unfolding now. Would you take it for a spin?"
    words=script.split()
    if len(words)>135:
        script=" ".join(words[:135])+"."
    tts = re.sub(r"[^\w\s.,!?$%\-']","",script)
    tts = re.sub(r"\s+"," ",tts).strip()
    seo_title = f"{title[:55]} #Shorts"
    desc = f"{title}\n\n{summary}\n\nSource: {article['link']}\n\n#Shorts #Tesla #ElonMusk"
    return {"tts_script":tts,"full_script":script,"seo_title":seo_title,"description":desc,"title":title,"link":article["link"],"topic":article["topic"]}

def download_realistic_image(topic, title, out_path):
    """Realistic photos, not gradient"""
    queries = {"tesla":"tesla,car","spacex":"spacex,rocket","ai_future":"ai,technology","creators":"youtube,creator"}
    q = queries.get(topic,"technology")
    sources = [
        f"https://source.unsplash.com/1080x1920/?{q}",  # REAL PHOTO - most reliable
        f"https://picsum.photos/1080/1920?random={random.randint(1,10000)}",
        f"https://image.pollinations.ai/prompt/{requests.utils.quote(f'{q} realistic photo')[:80]}?width=1080&height=1920&nologo=true",
    ]
    for i,url in enumerate(sources):
        try:
            logger.info(f"  Trying image source {i+1}: {url[:70]}...")
            r=requests.get(url, headers=HEADERS, timeout=25, allow_redirects=True)
            if r.status_code==200 and len(r.content)>15000:
                out_path.write_bytes(r.content)
                logger.info(f"  Image OK {len(r.content)/1024:.0f}KB from source {i+1}")
                return True
        except Exception as e:
            logger.warning(f"  Source {i+1} fail {e}")
    return False

def create_realistic_bg(topic, title, out_path):
    logger.info("[7/12] Creating REALISTIC 1080x1920 background...")
    tmp = OUTPUT_DIR / "temp_real.jpg"
    ok = download_realistic_image(topic, title, tmp)
    if not ok or not tmp.exists():
        logger.warning("All sources failed, creating textured tech bg (not solid)")
        img=Image.new("RGB",(1080,1920),"#0a0e1a")
        d=ImageDraw.Draw(img)
        for y in range(0,1920,40):
            d.line([(0,y),(1080,y)], fill=(20,25,45))
        for x in range(0,1080,40):
            d.line([(x,0),(x,1920)], fill=(20,25,45))
        img.save(out_path, quality=95)
        return out_path
    try:
        img=Image.open(tmp).convert("RGB")
        w,h=img.size
        scale=max(1080/w,1920/h)
        img_r=img.resize((int(w*scale), int(h*scale)), Image.LANCZOS)
        left=(img_r.size[0]-1080)//2
        top=(img_r.size[1]-1920)//2
        bg=img_r.crop((left,top,left+1080,top+1920))
        # Vignette for text
        vignette=Image.new("L",(1080,1920),0)
        dv=ImageDraw.Draw(vignette)
        for y in range(1920):
            a=0
            if y<300: a=int(160*(1-y/300))
            elif y>1620: a=int(160*((y-1620)/300))
            if a>0: dv.line([(0,y),(1080,y)], fill=a)
        dark=Image.new("RGB",(1080,1920),(0,0,0))
        bg=Image.composite(dark, bg, vignette)
        bg.save(out_path, quality=95)
        logger.info(f"Realistic bg created: {out_path}")
        return out_path
    except Exception as e:
        logger.error(f"Bg processing {e}")
        if tmp.exists():
            try:
                img=Image.open(tmp).convert("RGB").resize((1080,1920), Image.LANCZOS)
                img.save(out_path, quality=95)
                return out_path
            except: pass
        return create_realistic_bg(topic, title, out_path)

def generate_tts(text, out_path):
    logger.info("[7/12] TTS narration...")
    try:
        import edge_tts, asyncio
        async def _g():
            await edge_tts.Communicate(text, "en-US-AriaNeural").save(str(out_path))
        asyncio.run(_g())
    except:
        try:
            from gtts import gTTS
            gTTS(text=text, lang='en').save(str(out_path))
        except:
            subprocess.run(["ffmpeg","-y","-f","lavfi","-i","anullsrc=r=24000:cl=mono","-t","30","-q:a","9","-acodec","libmp3lame",str(out_path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        r=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(out_path)], capture_output=True, text=True, check=True)
        dur=float(r.stdout.strip())
    except:
        dur=30.0
    logger.info(f"Audio {dur:.1f}s")
    return dur

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

def build_video_motion(bg, audio, srt, out_path, duration):
    logger.info("[8/12] Building video WITH MOTION (Ken Burns)...")
    if duration>59: duration=59
    srt_esc=str(srt).replace("\\","/").replace(":","\\:")
    # Ken Burns slow zoom 1.0 -> 1.15 makes static photo feel like real video
    filt=f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,zoompan=z='min(zoom+0.0015,1.15)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',subtitles={srt_esc}:force_style='FontName=Arial,FontSize=26,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H80000000,BorderStyle=3,Outline=2,Shadow=1,Alignment=2,MarginV=280'"
    cmd=["ffmpeg","-y","-loop","1","-i",str(bg),"-i",str(audio),"-vf",filt,"-c:v","libx264","-t",str(duration),"-r","30","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k","-shortest","-movflags","+faststart",str(out_path)]
    try:
        r=subprocess.run(cmd, capture_output=True, text=True, timeout=150)
        if r.returncode!=0:
            logger.warning(f"Motion failed, retry simple: {r.stderr[-400:]}")
            filt2=f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,subtitles={srt_esc}:force_style='FontName=Arial,FontSize=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H80000000,BorderStyle=3,Outline=2,Alignment=2,MarginV=300'"
            cmd2=["ffmpeg","-y","-loop","1","-i",str(bg),"-i",str(audio),"-vf",filt2,"-c:v","libx264","-t",str(duration),"-r","30","-pix_fmt","yuv420p","-c:a","aac","-shortest","-movflags","+faststart",str(out_path)]
            subprocess.run(cmd2, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info(f"Video OK {out_path} {out_path.stat().st_size/1e6:.1f}MB")
        return True
    except Exception as e:
        logger.error(f"Build fail {e}")
        return False

def publish_telegram(config, video_path, script_data):
    token=config["telegram"]["token"]
    channel=config["telegram"]["channel"]
    if not token:
        logger.warning("No TG token, skip")
        return False
    logger.info(f"[9/12] Sending to Telegram {channel}...")
    caption=f"🚀 {script_data['title']}\n\n{script_data['description'][:700]}\n\n#Shorts #StarMindDaily"
    if len(caption)>1024: caption=caption[:1020]+"..."
    url=f"https://api.telegram.org/bot{token}/sendVideo"
    try:
        with open(video_path,'rb') as vf:
            files={'video':vf}
            data={'chat_id':channel,'caption':caption,'parse_mode':'Markdown','supports_streaming':True,'width':1080,'height':1920}
            resp=requests.post(url, data=data, files=files, timeout=60)
            res=resp.json()
            if res.get("ok"):
                logger.info(f"[10/12] Telegram SUCCESS msg_id={res['result']['message_id']}")
                return True
            else:
                logger.error(f"[10/12] Telegram FAIL {res}")
                return False
    except Exception as e:
        logger.error(f"Telegram ex {e}")
        return False

def main():
    is_test="--test" in sys.argv
    config=load_config()
    seen=load_seen()
    arts=fetch_articles()
    eligible=[]
    for a in arts:
        h=hashlib.sha256(a["link"].encode()).hexdigest()
        if a["id"] in seen or h in seen or a["link"] in seen: continue
        eligible.append(a)
    logger.info(f"[5/12] Eligible {len(eligible)}/{len(arts)}")
    if not eligible:
        logger.warning("No new articles")
        sys.exit(0)
    selected=eligible[0]
    script=generate_script(selected)
    logger.info(f"[6/12] Script: {script['full_script'][:100]}...")
    
    ts=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    bg=OUTPUT_DIR/f"bg_{ts}.jpg"
    audio=OUTPUT_DIR/f"audio_{ts}.mp3"
    srt=OUTPUT_DIR/f"cap_{ts}.srt"
    video=OUTPUT_DIR/f"StarMind_Short_{ts}.mp4"
    
    create_realistic_bg(selected["topic"], selected["title"], bg)
    dur=generate_tts(script["tts_script"], audio)
    create_srt(script["tts_script"], dur, srt)
    ok=build_video_motion(bg, audio, srt, video, dur)
    
    if not ok:
        logger.error("Build failed")
        sys.exit(5)
    
    tg_ok=False
    if not is_test:
        tg_ok=publish_telegram(config, video, script)
    else:
        logger.info("[9/12] Test mode - skip Telegram")
        tg_ok=True
    
    if ok:
        h=hashlib.sha256(selected["link"].encode()).hexdigest()
        seen.extend([selected["id"],h,selected["link"]])
        save_seen(seen)
        logger.info("[11/12] Marked seen")
    
    if tg_ok and ok:
        logger.info(f"[12/12] SUCCESS - Realistic video + Telegram {config['telegram']['channel']}")
    else:
        logger.info(f"[12/12] Video built at {video} (Telegram {'ok' if tg_ok else 'failed'})")
        if not tg_ok and not is_test:
            sys.exit(5)

if __name__=="__main__":
    main()
