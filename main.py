import os
import re
import json
import hashlib
import logging
import html
from datetime import datetime, timezone, timedelta
from time import time
from calendar import timegm
from urllib.parse import quote

import requests
import feedparser

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@StarMindDaily").strip()
CHANNEL_LINK = os.getenv("TELEGRAM_CHANNEL_LINK", "").strip()
STATE_FILE = "seen_articles.json"
GROWTH_FILE = "growth_stats.json"
MAX_SEEN = 500
MAX_GROWTH_DAYS = 180
REQUEST_TIMEOUT = 25
MAX_STORY_AGE_HOURS = 72

RSS_FEEDS = {
    "Tesla": "https://news.google.com/rss/search?q=Tesla+OR+robotaxi+OR+Optimus+when:3d&hl=en-US&gl=US&ceid=US:en",
    "SpaceX": "https://news.google.com/rss/search?q=SpaceX+OR+Starship+OR+Starlink+when:3d&hl=en-US&gl=US&ceid=US:en",
    "AI & Future Tech": "https://news.google.com/rss/search?q=artificial+intelligence+OR+future+technology+when:3d&hl=en-US&gl=US&ceid=US:en",
    "Creators": "https://news.google.com/rss/search?q=MrBeast+OR+YouTube+creator+economy+when:3d&hl=en-US&gl=US&ceid=US:en",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
session = requests.Session()
session.headers.update({"User-Agent": "StarMindDailyBot/3.0 (+RSS content curation)"})


def clean_text(value):
    """Remove HTML, decode entities, and normalize whitespace."""
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def save_json(path, data):
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(temp_path, path)


def load_state():
    data = load_json(STATE_FILE, [])
    return set(data if isinstance(data, list) else [])


def save_state(seen):
    # Keep the most recently added keys rather than sorting hashes.
    save_json(STATE_FILE, list(seen)[-MAX_SEEN:])


def entry_key(entry):
    url = (entry.get("link") or "").strip()
    title = clean_text(entry.get("title", "")).lower()
    return hashlib.sha256((url or title).encode("utf-8")).hexdigest()


def get_timestamp(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            return timegm(parsed)
        except (OverflowError, ValueError, TypeError):
            pass
    return 0


def fetch_candidates(seen):
    candidates = []
    cutoff = time() - (MAX_STORY_AGE_HOURS * 3600)

    for category, feed_url in RSS_FEEDS.items():
        try:
            # Pass explicit timeout via requests so a stalled feed cannot hang the run.
            response = session.get(feed_url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            feed = feedparser.parse(response.content)

            if getattr(feed, "bozo", False):
                logging.warning(
                    "RSS parser warning for %s: %s",
                    category,
                    getattr(feed, "bozo_exception", "unknown"),
                )

            for entry in feed.entries[:25]:
                raw_title = clean_text(entry.get("title", ""))
                link = (entry.get("link") or "").strip()
                summary = clean_text(entry.get("summary", ""))
                key = entry_key(entry)
                timestamp = get_timestamp(entry)

                if not raw_title or not link or key in seen:
                    continue
                if timestamp and timestamp < cutoff:
                    continue

                # Google News titles often end with a publisher suffix.
                title = re.sub(r"\s+-\s+[^-]{2,80}$", "", raw_title).strip()
                if not title:
                    continue

                candidates.append({
                    "category": category,
                    "title": title,
                    "link": link,
                    "summary": summary[:700],
                    "key": key,
                    "timestamp": timestamp,
                })
        except Exception:
            logging.exception("Could not read RSS feed for %s", category)

    # Prioritize newest stories. Entries without a date are considered last.
    candidates.sort(key=lambda x: x["timestamp"], reverse=True)
    return candidates


def keyword_phrase(title, category):
    """Create a readable keyword phrase without keyword stuffing."""
    title = re.sub(r"[^\w\s'-]", " ", title, flags=re.UNICODE)
    words = [w for w in re.split(r"\s+", title) if w]
    return " ".join(words[:8]).strip() or category


def hashtags_for(category):
    return {
        "Tesla": "#Tesla #EV #Robotaxi #AutonomousDriving",
        "SpaceX": "#SpaceX #Starship #Space #Starlink",
        "AI & Future Tech": "#AI #FutureTech #Technology #Innovation",
        "Creators": "#CreatorEconomy #YouTube #DigitalMedia #Creators",
    }.get(category, "#FutureTech #Innovation #Technology")


def get_channel_link():
    if CHANNEL_LINK:
        return CHANNEL_LINK
    if CHANNEL_ID.startswith("@"):
        return f"https://t.me/{CHANNEL_ID[1:]}"
    return ""


def build_caption(item):
    category = item["category"]
    title = item["title"].rstrip(" .!?")
    keyword = keyword_phrase(title, category)

    hook_templates = [
        f"🚨 FUTURE TECH UPDATE: {title}",
        f"👀 WHAT HAPPENS NEXT? {title}",
        f"⚡ THE LATEST IN {category.upper()}: {title}",
        f"🤯 WHY THIS STORY MATTERS: {title}",
        f"🚀 FUTURE WATCH: {title}",
        f"📡 JUST IN: {title}",
    ]
    hook = hook_templates[int(item["key"][:8], 16) % len(hook_templates)]

    summary = item.get("summary", "")
    if summary and len(summary) > 35:
        body = summary[:440].rstrip()
        if len(summary) > 440:
            body = body.rsplit(" ", 1)[0] + "…"
    else:
        body = (
            f"A developing story in {category} is drawing attention. "
            f"The important details to watch are what has actually changed, "
            f"what it could mean next, and whether it leads to real-world results."
        )

    hashtags = hashtags_for(category)
    link = get_channel_link()
    channel_label = CHANNEL_ID if CHANNEL_ID.startswith("@") else "our channel"
    join_line = f"📲 Follow {channel_label} for more updates: {link}" if link else (
        "📲 Follow our channel for more technology and creator-economy updates."
    )

    caption = (
        f"{hook}\n\n"
        f"{body}\n\n"
        f"🔎 WHY IT MATTERS\n"
        f"This story connects to {keyword} and the wider {category.lower()} landscape. "
        f"Watch for verified updates as more details emerge.\n\n"
        f"💬 YOUR TAKE\n"
        f"Breakthrough, hype, or somewhere in between? Share your view—and forward this "
        f"post to someone who follows {category.lower()}.\n\n"
        f"📰 Source: {item['link']}\n\n"
        f"{join_line}\n\n"
        f"#StarMindDaily {hashtags}"
    )

    # Telegram photo captions are limited to 1024 characters.
    if len(caption) > 1000:
        body_limit = max(160, 1000 - (len(caption) - len(body)))
        body = body[:body_limit].rsplit(" ", 1)[0].rstrip() + "…"
        caption = (
            f"{hook}\n\n{body}\n\n"
            f"🔎 Why it matters: Follow verified updates on {category.lower()}.\n\n"
            f"💬 Breakthrough or hype? Share your take and forward this post.\n\n"
            f"📰 Source: {item['link']}\n\n"
            f"{join_line}\n\n#StarMindDaily {hashtags}"
        )
    if len(caption) > 1024:
        caption = caption[:990].rsplit(" ", 1)[0] + "…"
    return caption


def image_url(item):
    """Generate a photorealistic editorial-style image for the news topic.

    This is AI-generated artwork, not proof that the pictured event actually happened.
    """
    topic = clean_text(f"{item['category']}: {item['title']}")
    prompt = (
        f"Create a highly photorealistic editorial news photograph illustrating this topic: {topic}. "
        "Looks like a real photo captured by a professional photojournalist on a modern full-frame camera, "
        "natural realistic lighting, physically accurate materials, believable scale and perspective, "
        "authentic documentary photography, subtle natural imperfections, crisp subject, realistic depth of field. "
        "Show one clear main subject relevant to the story. Avoid fantasy, illustration, cartoon, painting, "
        "3D render, CGI, plastic textures, oversaturated colors, impossible geometry, distorted vehicles, "
        "extra wheels, malformed objects, fake writing, watermarks, captions, and logos. Square composition."
    )
    seed = int(item["key"][:8], 16) % 100000
    return (
        "https://image.pollinations.ai/prompt/"
        f"{quote(prompt)}?width=1080&height=1080&seed={seed}&nologo=true"
    )


def telegram_api(method, payload=None):
    if not BOT_TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN GitHub secret.")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    response = session.post(url, data=payload or {}, timeout=REQUEST_TIMEOUT)
    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Telegram returned non-JSON response for {method}.") from exc
    if not response.ok or not result.get("ok"):
        raise RuntimeError(
            f"Telegram {method} failed: {result.get('description', response.status_code)}"
        )
    return result["result"]


def telegram_post(item, caption):
    if not CHANNEL_ID:
        raise RuntimeError("Missing TELEGRAM_CHANNEL_ID GitHub secret.")

    photo = image_url(item)
    try:
        result = telegram_api(
            "sendPhoto",
            {"chat_id": CHANNEL_ID, "caption": caption, "photo": photo},
        )
        logging.info("Posted image + caption: %s (message_id=%s)", item["title"], result.get("message_id"))
        return True
    except Exception:
        logging.exception("Photo post failed; trying text-only fallback.")

    result = telegram_api(
        "sendMessage",
        {
            "chat_id": CHANNEL_ID,
            "text": caption,
            "disable_web_page_preview": "false",
        },
    )
    logging.info("Posted text-only fallback: %s (message_id=%s)", item["title"], result.get("message_id"))
    return True


def update_growth_stats():
    """Record daily member counts when Telegram makes the count available."""
    try:
        result = telegram_api("getChatMemberCount", {"chat_id": CHANNEL_ID})
        count = int(result)
    except Exception as exc:
        logging.warning("Could not retrieve channel member count: %s", exc)
        return

    stats = load_json(GROWTH_FILE, {})
    if not isinstance(stats, dict):
        stats = {}

    today = datetime.now(timezone.utc).date().isoformat()
    previous = stats.get(today, {})
    first_count = int(previous.get("first_members", count))
    stats[today] = {
        "first_members": first_count,
        "members": count,
        "change_since_first_check_today": count - first_count,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    # Retain only the latest MAX_GROWTH_DAYS daily entries.
    for old_day in sorted(stats)[:-MAX_GROWTH_DAYS]:
        stats.pop(old_day, None)

    save_json(GROWTH_FILE, stats)
    logging.info("Channel members: %s; today's change since first check: %s", count, count - int(previous_count))


def main():
    logging.info("StarMind Growth Engine started at %s", datetime.now(timezone.utc).isoformat())

    # Capture current count before posting, so each workflow run updates the growth log.
    update_growth_stats()

    seen = load_state()
    candidates = fetch_candidates(seen)

    if not candidates:
        logging.info("No fresh unseen stories found within %s hours. Skipping to avoid duplicate posts.", MAX_STORY_AGE_HOURS)
        return

    # One post per scheduled run; avoid flooding the channel.
    item = candidates[0]
    caption = build_caption(item)
    logging.info("Selected category=%s title=%s", item["category"], item["title"])

    if telegram_post(item, caption):
        seen.add(item["key"])
        save_state(seen)
        logging.info("Success. Caption length: %s", len(caption))

    # Refresh count after posting; member count may not change during this run.
    update_growth_stats()


if __name__ == "__main__":
    main()
