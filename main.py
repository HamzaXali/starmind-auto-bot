import os
import re
import json
import hashlib
import logging
from datetime import datetime, timezone
from urllib.parse import quote

import requests
import feedparser

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@StarMindDaily").strip()
STATE_FILE = "seen_articles.json"
MAX_SEEN = 500
REQUEST_TIMEOUT = 25

# Topic-specific feeds help the bot find relevant, recent stories.
RSS_FEEDS = {
    "Tesla": "https://news.google.com/rss/search?q=Tesla+OR+robotaxi+OR+Optimus+when:2d&hl=en-US&gl=US&ceid=US:en",
    "SpaceX": "https://news.google.com/rss/search?q=SpaceX+OR+Starship+OR+Starlink+when:2d&hl=en-US&gl=US&ceid=US:en",
    "AI & Future Tech": "https://news.google.com/rss/search?q=artificial+intelligence+OR+future+technology+when:2d&hl=en-US&gl=US&ceid=US:en",
    "Creators": "https://news.google.com/rss/search?q=MrBeast+OR+YouTube+creator+economy+when:2d&hl=en-US&gl=US&ceid=US:en",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
session = requests.Session()
session.headers.update({"User-Agent": "StarMindDailyBot/2.0 (+RSS content curation)"})


def clean_text(value):
    """Remove HTML and normalize whitespace in RSS fields."""
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = re.sub(r"&amp;", "&", value)
    value = re.sub(r"&quot;", '"', value)
    value = re.sub(r"&#39;|&apos;", "'", value)
    value = re.sub(r"&lt;", "<", value)
    value = re.sub(r"&gt;", ">", value)
    return re.sub(r"\s+", " ", value).strip()


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data if isinstance(data, list) else [])
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_state(seen):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen)[-MAX_SEEN:], f, indent=2, ensure_ascii=False)


def entry_key(entry):
    url = (entry.get("link") or "").strip()
    title = clean_text(entry.get("title", "")).lower()
    return hashlib.sha256((url or title).encode("utf-8")).hexdigest()


def get_timestamp(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            from time import mktime
            return mktime(parsed)
        except (OverflowError, ValueError, TypeError):
            pass
    return 0


def fetch_candidates(seen):
    candidates = []
    for category, feed_url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(feed_url)
            if getattr(feed, "bozo", False):
                logging.warning("RSS parser warning for %s: %s", category, getattr(feed, "bozo_exception", "unknown"))
            for entry in feed.entries[:20]:
                title = clean_text(entry.get("title", ""))
                link = (entry.get("link") or "").strip()
                summary = clean_text(entry.get("summary", ""))
                key = entry_key(entry)
                if not title or not link or key in seen:
                    continue
                # Google News titles often end with a publisher suffix.
                title = re.sub(r"\s+-\s+[^-]{2,80}$", "", title).strip()
                candidates.append({
                    "category": category,
                    "title": title,
                    "link": link,
                    "summary": summary[:400],
                    "key": key,
                    "timestamp": get_timestamp(entry),
                })
        except Exception:
            logging.exception("Could not read RSS feed for %s", category)
    candidates.sort(key=lambda x: x["timestamp"], reverse=True)
    return candidates


def keyword_phrase(title, category):
    """Create a readable keyword phrase without keyword stuffing."""
    title = re.sub(r"[^\w\s'-]", " ", title, flags=re.UNICODE)
    words = [w for w in re.split(r"\s+", title) if w]
    phrase = " ".join(words[:8]).strip()
    return phrase or category


def build_caption(item):
    category = item["category"]
    title = item["title"].rstrip(" .!?")
    keyword = keyword_phrase(title, category)

    hook_templates = [
        f"🚨 THE FUTURE IS MOVING: {title}",
        f"👀 This could change what happens next: {title}",
        f"⚡ FUTURE WATCH: {title}",
        f"🤯 Here’s why people are watching this: {title}",
        f"🚀 What this new development could mean: {title}",
    ]
    # Stable rotation avoids the same hook being selected unpredictably on reruns.
    hook = hook_templates[int(item["key"][:8], 16) % len(hook_templates)]

    summary = item.get("summary", "")
    if summary and len(summary) > 30:
        body = summary[:340].rstrip()
        if len(summary) > 340:
            body = body.rsplit(" ", 1)[0] + "…"
    else:
        body = (
            f"A new development in {category} is drawing attention. "
            "The key question is what happens next—and whether this moves the technology "
            "closer to real-world use."
        )

    hashtags = {
        "Tesla": "#Tesla #EV #AutonomousDriving",
        "SpaceX": "#SpaceX #Space #Starship",
        "AI & Future Tech": "#AI #FutureTech #Technology",
        "Creators": "#CreatorEconomy #YouTube #DigitalMedia",
    }.get(category, "#FutureTech #Innovation")

    caption = (
        f"{hook}\n\n"
        f"{body}\n\n"
        f"🔎 WHY IT MATTERS\n"
        f"This is worth watching for anyone following {category.lower()} and emerging technology.\n\n"
        f"💬 Your take: breakthrough, hype, or a bit of both?\n\n"
        f"Source: {item['link']}\n\n"
        f"#{'StarMindDaily'} {hashtags}"
    )

    # Telegram photo captions are limited to 1024 characters.
    if len(caption) > 1000:
        caption = caption[:970].rsplit(" ", 1)[0] + "…\n\n" + hashtags + " #StarMindDaily"
    return caption


def image_url(item):
    # Prompt describes a conceptual editorial visual, not a claim that the image is real.
    prompt = (
        f"premium futuristic editorial illustration about {item['category']}: {item['title']}; "
        "cinematic lighting, polished composition, realistic materials, no text, no logos, square format"
    )
    seed = int(item["key"][:8], 16) % 100000
    return f"https://image.pollinations.ai/prompt/{quote(prompt)}?width=1080&height=1080&seed={seed}&nologo=true"


def telegram_post(item, caption):
    if not BOT_TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN GitHub secret.")
    if not CHANNEL_ID:
        raise RuntimeError("Missing TELEGRAM_CHANNEL_ID GitHub secret.")

    api = f"https://api.telegram.org/bot{BOT_TOKEN}"
    photo = image_url(item)
    try:
        response = session.post(
            f"{api}/sendPhoto",
            data={"chat_id": CHANNEL_ID, "caption": caption, "photo": photo},
            timeout=REQUEST_TIMEOUT,
        )
        result = response.json()
        if response.ok and result.get("ok"):
            logging.info("Posted image + caption: %s", item["title"])
            return True
        logging.warning("Photo post failed (%s): %s", response.status_code, result.get("description", "unknown"))
    except (requests.RequestException, ValueError):
        logging.exception("Photo post request failed; trying text-only fallback.")

    # A text fallback means a temporary image-provider failure won't waste the post.
    response = session.post(
        f"{api}/sendMessage",
        data={"chat_id": CHANNEL_ID, "text": caption, "disable_web_page_preview": "false"},
        timeout=REQUEST_TIMEOUT,
    )
    result = response.json()
    if response.ok and result.get("ok"):
        logging.info("Posted text-only fallback: %s", item["title"])
        return True
    raise RuntimeError(f"Telegram send failed: {result.get('description', response.status_code)}")


def main():
    logging.info("StarMind Pro Bot started at %s", datetime.now(timezone.utc).isoformat())
    seen = load_state()
    candidates = fetch_candidates(seen)

    if not candidates:
        logging.info("No fresh RSS stories found. Skipping this run to avoid duplicate/spam posts.")
        return

    # One post per scheduled run. The newest unseen story is preferred.
    item = candidates[0]
    caption = build_caption(item)
    logging.info("Selected category=%s title=%s", item["category"], item["title"])

    if telegram_post(item, caption):
        seen.add(item["key"])
        save_state(seen)
        logging.info("Success. Caption length: %s", len(caption))


if __name__ == "__main__":
    main()
