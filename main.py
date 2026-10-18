#!/usr/bin/env python3
"""
StarMind Daily - Pro Production Bot
Fixes root cause: workflow green but Telegram not delivered.

Root causes fixed:
1. TELEGRAM API response not validated (ok:false treated as success)
2. seen_articles.json updated BEFORE Telegram confirmed success -> marks as seen even when failed
3. CHANNEL_ID env name mismatch (TELEGRAM_CHANNEL_ID vs CHANNEL_ID) -> chat_id=None
4. previous_count undefined in update_growth_stats() -> crash after post, seen not committed
5. Caption >1024 chars for sendPhoto -> Telegram error 400, no fallback
6. RSS 403 due to missing User-Agent -> 0 articles, silent exit 0
7. Image URL invalid -> sendPhoto fails, no text fallback
8. getChatMemberCount failure swallowed -> hides permission issue

12-stage structured logging implemented.
Only marks published AFTER Telegram ok:true.
"""

import os
import sys
import json
import re
import time
import random
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import feedparser
import requests
from dateutil import parser as date_parser

# ---------- Logging ----------
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S UTC")
logger = logging.getLogger("starmind")
logger.setLevel(logging.INFO)

# Files
SEEN_FILE = Path("seen_articles.json")
GROWTH_FILE = Path("growth_stats.json")

# ---------- Config ----------
FEEDS = {
    "tesla": "https://news.google.com/rss/search?q=Tesla+Elon+Musk&hl=en-US&gl=US&ceid=US:en",
    "spacex": "https://news.google.com/rss/search?q=SpaceX&hl=en-US&gl=US&ceid=US:en",
    "ai_future": "https://news.google.com/rss/search?q=AI+future+technology+breakthrough&hl=en-US&gl=US&ceid=US:en",
    "creators": "https://news.google.com/rss/search?q=MrBeast+creator+economy+YouTube&hl=en-US&gl=US&ceid=US:en",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; StarMindDailyBot/1.0; +https://t.me/StarMindDaily)"
}

HOOKS = [
    "🚀 BREAKING:",
    "🤯 You won't believe this:",
    "⚡️ Future is here:",
    "🔥 Just in:",
    "💡 StarMind Insight:",
    "🌌 This changes everything:",
]

CTAS = [
    "Would you take it for a spin? 👇",
    "Is this the future or too wild? Comment below 👇",
    "Would you invest in this future? 🤔",
    "Drop your take below — future or fantasy? 👇",
    "Save this for when it launches! 📌",
]

HASHTAGS = {
    "tesla": "#Tesla #ElonMusk #ElectricFuture",
    "spacex": "#SpaceX #ElonMusk #Mars",
    "ai_future": "#AI #FutureTech #Innovation",
    "creators": "#CreatorEconomy #YouTube #MrBeast",
}

# ---------- Helpers ----------
def load_config() -> Tuple[str, str]:
    """Stage 2: Configuration validated"""
    logger.info("[2/12] Validating configuration...")
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    # Support both names: README says TELEGRAM_CHANNEL_ID, some code used CHANNEL_ID
    channel = os.getenv("TELEGRAM_CHANNEL_ID") or os.getenv("CHANNEL_ID") or os.getenv("TELEGRAM_CHAT_ID")
    
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN missing in env / GitHub Secrets")
        sys.exit(2)
    
    if not channel:
        logger.warning("CHANNEL_ID not set, defaulting to @StarMindDaily")
        channel = "@StarMindDaily"
    
    # Normalize channel ID
    channel = str(channel).strip()
    # If it's numeric without -100 prefix for channel, keep as is; Telegram accepts -100...
    # If it's username without @ and not numeric, add @
    if not channel.startswith("@") and not channel.startswith("-") and not channel.lstrip("-").isdigit():
        channel = f"@{channel}"
        logger.info(f"Normalized channel to {channel}")

    # Mask token for logs
    logger.info(f"Config OK: bot_token=***{token[-4:]}, channel_id={channel}")
    return token, channel

def load_seen() -> List[str]:
    if not SEEN_FILE.exists():
        logger.info(f"{SEEN_FILE} not found, starting fresh")
        return []
    try:
        data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "seen" in data:
            return data["seen"]
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        logger.warning(f"Failed to load {SEEN_FILE}: {e}, starting fresh")
        return []

def save_seen(seen_list: List[str]):
    # Only call AFTER telegram confirmed success
    payload = {
        "seen": seen_list[-500:],  # keep last 500
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    SEEN_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info(f"[10/12] Marked as published, {SEEN_FILE} updated ({len(payload['seen'])} total)")

def fetch_all_feeds() -> List[Dict]:
    """Stage 3 & 4: RSS feeds checked, Articles discovered"""
    logger.info("[3/12] Checking RSS feeds...")
    all_articles = []
    for topic, url in FEEDS.items():
        try:
            logger.info(f"  -> Fetching {topic}: {url}")
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            if not feed.entries:
                logger.warning(f"  {topic}: 0 entries (feed may be blocked or empty)")
                continue
            for entry in feed.entries[:10]:
                # Parse date
                pub_date = None
                if hasattr(entry, "published"):
                    try:
                        pub_date = date_parser.parse(entry.published)
                    except:
                        pub_date = datetime.now(timezone.utc)
                else:
                    pub_date = datetime.now(timezone.utc)
                
                article = {
                    "id": hashlib.sha256((entry.get("link","") + entry.get("title","")).encode()).hexdigest()[:16],
                    "topic": topic,
                    "title": entry.get("title","").strip(),
                    "link": entry.get("link","").strip(),
                    "summary": re.sub(r"<[^>]+>", "", entry.get("summary",""))[:500],
                    "published": pub_date,
                    "source": entry.get("source", {}).get("title","Google News") if hasattr(entry, "source") else "Google News"
                }
                if article["title"] and article["link"]:
                    all_articles.append(article)
            logger.info(f"  {topic}: {len(feed.entries)} entries")
        except Exception as e:
            logger.error(f"  {topic}: FAILED {e}", exc_info=False)
    # Sort newest first
    all_articles.sort(key=lambda x: x["published"], reverse=True)
    logger.info(f"[4/12] Discovered {len(all_articles)} articles total")
    return all_articles

def filter_eligible(articles: List[Dict], seen: List[str]) -> List[Dict]:
    logger.info("[5/12] Applying duplicate and eligibility filters...")
    eligible = []
    for a in articles:
        # Duplicate check: by link hash and id
        link_hash = hashlib.sha256(a["link"].encode()).hexdigest()
        if a["id"] in seen or link_hash in seen or a["link"] in seen:
            continue
        # Basic quality filters
        if len(a["title"]) < 15:
            continue
        if "google.com" in a["link"] and "/articles/" not in a["link"]:
            # Google News redirect links are okay, but skip if title is generic
            pass
        eligible.append(a)
    logger.info(f"  After filters: {len(eligible)} eligible, {len(articles)-len(eligible)} filtered (duplicates/too short)")
    if not eligible and articles:
        logger.warning(f"  All {len(articles)} articles filtered as duplicates. Seen count: {len(seen)}")
    return eligible

def generate_caption(article: Dict) -> Tuple[str, str]:
    logger.info("[7/12] Preparing image and caption...")
    hook = random.choice(HOOKS)
    cta = random.choice(CTAS)
    hashtag = HASHTAGS.get(article["topic"], "#Future #Tech")
    
    # Clean title
    title = article["title"]
    # Remove source suffix like " - ABC News"
    title = re.sub(r"\s*-\s*[A-Za-z ]+News.*$", "", title).strip()
    
    summary = article["summary"][:280].strip()
    if not summary.endswith("."):
        summary += "."
    
    why = {
        "tesla": "This could accelerate EV adoption and energy storage worldwide.",
        "spacex": "Brings us closer to multiplanetary life and cheaper space access.",
        "ai_future": "AI is reshaping how we work, create, and live — this is a signal of what's next.",
        "creators": "Creator economy is now bigger than Hollywood — this shows where attention is moving."
    }.get(article["topic"], "Why it matters: the future is moving faster than headlines suggest.")

    caption = f"""{hook}

**{title}**

{summary}

💡 Why it matters: {why}

🔗 Source: {article['link']}

{cta}

{hashtag}
"""
    # Telegram limits: 1024 for photo caption, 4096 for message
    # For safety, keep photo caption <= 900 chars
    if len(caption) > 900:
        # Trim summary
        caption = f"""{hook}

**{title}**

{why}

🔗 {article['link']}

{cta}

{hashtag}
"""
        if len(caption) > 900:
            caption = caption[:880] + "..."

    # Image prompt
    image_prompt = f"conceptual editorial square image, {article['topic']} theme, {title}, futuristic, cinematic, 8k"
    # Use Pollinations as primary (free, no key) with fallback
    encoded_prompt = requests.utils.quote(image_prompt[:150])
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
    
    # Alternative image from article if available? feedparser doesn't give image, so use generated
    return caption, image_url

def telegram_api_call(token: str, method: str, payload: Dict, is_test: bool=False) -> Dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        resp = requests.post(url, json=payload, timeout=20)
        data = resp.json()
        # Telegram always returns JSON with ok field
        if not data.get("ok"):
            logger.error(f"Telegram API {method} returned ok=false: {data}")
            logger.error(f"  Error {data.get('error_code')}: {data.get('description')}")
            return {"success": False, "response": data, "status_code": resp.status_code}
        logger.info(f"Telegram API {method} success: message_id={data.get('result',{}).get('message_id')}")
        return {"success": True, "response": data, "status_code": resp.status_code}
    except requests.exceptions.Timeout:
        logger.error(f"Telegram API {method} timeout")
        return {"success": False, "response": {"description": "timeout"}, "status_code": 0}
    except Exception as e:
        logger.error(f"Telegram API {method} exception: {e}", exc_info=True)
        try:
            # Try to get text
            return {"success": False, "response": {"description": str(e), "raw": resp.text if 'resp' in locals() else ""}, "status_code": 0}
        except:
            return {"success": False, "response": {"description": str(e)}, "status_code": 0}

def publish_to_telegram(token: str, channel: str, caption: str, image_url: str, article_link: str, is_test: bool=False) -> bool:
    """Stage 8 & 9: Publishing attempted and validated"""
    logger.info(f"[8/12] Attempting Telegram publishing to {channel}...")
    
    # Try sendPhoto first
    if image_url and not is_test:
        payload = {
            "chat_id": channel,
            "photo": image_url,
            "caption": caption,
            "parse_mode": "Markdown",
        }
        result = telegram_api_call(token, "sendPhoto", payload)
        if result["success"]:
            logger.info("[9/12] Telegram sendPhoto validated: ok=true")
            return True
        else:
            desc = result["response"].get("description","")
            # If photo fails (bad image, too long caption), fallback to text
            logger.warning(f"sendPhoto failed ({desc}), falling back to sendMessage")
    
    # Fallback text post
    # For text, we can use longer caption but keep formatting
    text_payload = {
        "chat_id": channel,
        "text": caption,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }
    result = telegram_api_call(token, "sendMessage", text_payload, is_test=is_test)
    if result["success"]:
        logger.info("[9/12] Telegram sendMessage validated: ok=true")
        return True
    else:
        logger.error("[9/12] Telegram publishing FAILED for both photo and text")
        # Log actual reason for troubleshooting guide
        logger.error(f"  Last error: {result['response']}")
        return False

def update_growth_stats(token: str, channel: str):
    """Stage 11: Growth statistics - FIXED previous_count bug"""
    logger.info("[11/12] Updating growth stats...")
    try:
        # Load existing stats
        if GROWTH_FILE.exists():
            try:
                stats = json.loads(GROWTH_FILE.read_text(encoding="utf-8"))
            except:
                stats = {}
        else:
            stats = {}
        
        # FIX: previous_count was previously undefined - now correctly load from file
        previous_count = stats.get("member_count", 0)
        previous_date = stats.get("last_updated", None)
        
        # Try getChatMemberCount - requires bot admin in channel
        url = f"https://api.telegram.org/bot{token}/getChatMemberCount"
        try:
            resp = requests.post(url, json={"chat_id": channel}, timeout=15)
            data = resp.json()
            if data.get("ok"):
                current_count = data["result"]
                growth = current_count - previous_count if isinstance(previous_count, int) else 0
                stats.update({
                    "member_count": current_count,
                    "previous_count": previous_count,  # FIXED: was undefined before
                    "growth": growth,
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "previous_date": previous_date,
                    "channel": channel
                })
                GROWTH_FILE.write_text(json.dumps(stats, indent=2), encoding="utf-8")
                logger.info(f"  Member count: {previous_count} -> {current_count} (growth {growth:+d})")
            else:
                # Bot may not be admin or channel ID wrong - log but don't crash workflow
                logger.warning(f"  getChatMemberCount failed: {data.get('description')} - bot may not be admin or channel private")
                # Still update timestamp
                stats["last_checked"] = datetime.now(timezone.utc).isoformat()
                stats["last_error"] = data.get("description")
                GROWTH_FILE.write_text(json.dumps(stats, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"  getChatMemberCount exception: {e} (non-critical)")
            # Don't fail workflow for stats
    except Exception as e:
        logger.warning(f"  update_growth_stats failed (non-critical): {e}", exc_info=False)
        # This was the original crash point - now we catch it

def test_telegram_connectivity(token: str, channel: str) -> bool:
    """Safe publishing test - does not post to public channel"""
    logger.info("=== SAFE PUBLISHING TEST ===")
    # 1. getMe
    try:
        resp = requests.post(f"https://api.telegram.org/bot{token}/getMe", timeout=10).json()
        if not resp.get("ok"):
            logger.error(f"getMe failed: {resp}")
            return False
        bot_username = resp["result"]["username"]
        logger.info(f"  getMe OK: @{bot_username}")
    except Exception as e:
        logger.error(f"getMe exception: {e}")
        return False
    
    # 2. getChat
    try:
        resp = requests.post(f"https://api.telegram.org/bot{token}/getChat", json={"chat_id": channel}, timeout=10).json()
        if not resp.get("ok"):
            logger.error(f"getChat failed for {channel}: {resp.get('description')} - CHECK: bot added as admin? channel ID correct? Use @StarMindDaily or -100... ID")
            return False
        logger.info(f"  getChat OK: {resp['result'].get('title')} ({resp['result'].get('type')})")
    except Exception as e:
        logger.error(f"getChat exception: {e}")
        return False
    
    # 3. getChatMemberCount
    try:
        resp = requests.post(f"https://api.telegram.org/bot{token}/getChatMemberCount", json={"chat_id": channel}, timeout=10).json()
        if resp.get("ok"):
            logger.info(f"  getChatMemberCount OK: {resp['result']} members")
        else:
            logger.warning(f"  getChatMemberCount warning: {resp.get('description')} - bot may need admin rights for stats, but can still post")
    except Exception as e:
        logger.warning(f"  getChatMemberCount exception: {e}")
    
    logger.info("=== TEST PASSED: Bot can access channel. Safe to publish ===")
    return True

def main():
    is_test = "--test" in sys.argv
    logger.info("[1/12] Workflow started" + (" (TEST MODE)" if is_test else ""))
    logger.info(f"  Time: {datetime.now(timezone.utc).isoformat()}, Args: {sys.argv}")
    
    token, channel = load_config()
    
    if is_test:
        ok = test_telegram_connectivity(token, channel)
        sys.exit(0 if ok else 3)
    
    seen = load_seen()
    articles = fetch_all_feeds()
    
    if not articles:
        logger.error("No articles fetched from any RSS feed - check network, User-Agent, or feed URLs")
        sys.exit(4)
    
    eligible = filter_eligible(articles, seen)
    
    if not eligible:
        logger.warning("No eligible new articles after filtering. Possible reasons:")
        logger.warning(f"  - All {len(articles)} articles already in seen_articles.json ({len(seen)} seen)")
        logger.warning("  - RSS returned only old/duplicates")
        logger.warning("  - Clear seen_articles.json if you want to retest, or wait for new news")
        # Do NOT mark anything, do NOT fail - this is not an error, just no new content
        # But log clearly so workflow green means 'no new content', not 'failed silently'
        logger.info("[12/12] Workflow completed: no new articles to publish (not an error)")
        # Update growth stats even when no post
        update_growth_stats(token, channel)
        sys.exit(0)
    
    # Select newest
    selected = eligible[0]
    logger.info(f"[6/12] Article selected: [{selected['topic']}] {selected['title'][:80]}...")
    logger.info(f"  Link: {selected['link']}")
    
    caption, image_url = generate_caption(selected)
    
    # Publish - CRITICAL: only mark seen AFTER success
    success = publish_to_telegram(token, channel, caption, image_url, selected["link"])
    
    if not success:
        logger.error("Publishing failed - NOT marking as seen, exiting with error so workflow shows red")
        logger.error("Check troubleshooting guide: bot admin rights, channel ID format, caption length, image URL")
        sys.exit(5)
    
    # ONLY NOW mark as published - FIX for root cause #2
    link_hash = hashlib.sha256(selected["link"].encode()).hexdigest()
    seen.append(selected["id"])
    seen.append(link_hash)
    seen.append(selected["link"])
    save_seen(seen)
    
    update_growth_stats(token, channel)
    
    logger.info("[12/12] Workflow completed SUCCESSFULLY - post delivered and verified")
    sys.exit(0)

if __name__ == "__main__":
    main()