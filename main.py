import os
import random
import requests
import feedparser
from datetime import datetime

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@StarMindDaily")

RSS_FEEDS = {
    "Tesla": "https://news.google.com/rss/search?q=Tesla+future+tech&hl=en-US&gl=US&ceid=US:en",
    "SpaceX": "https://news.google.com/rss/search?q=SpaceX+Elon+Musk&hl=en-US&gl=US&ceid=US:en",
    "MrBeast": "https://news.google.com/rss/search?q=MrBeast&hl=en-US&gl=US&ceid=US:en",
    "Future Tech": "https://news.google.com/rss/search?q=future+technology&hl=en-US&gl=US&ceid=US:en"
}

CAPTION_TEMPLATES = [
    {
        "hook": "BREAKING: {topic} is changing everything 🚀",
        "body": "While everyone is distracted, {topic} is quietly building the future.\n\nThis is not sci-fi anymore. This is NOW.",
        "cta": "Are you ready for what's coming? 👇"
    },
    {
        "hook": "Why {topic} has 800M+ eyes on it 👁️",
        "body": "He didn't post on Instagram.\nHe didn't post on TikTok.\n\nHe knows where the future is being built.",
        "cta": "Would you say YES to this future? 👇"
    },
    {
        "hook": "Future Drop: {topic} just did the impossible 🤯",
        "body": "Most will ignore this.\nSmart people will understand it.\nFuture thinkers will ACT on it.",
        "cta": "Drop a 🚀 if you're building the future"
    }
]

def get_trending():
    try:
        cat = random.choice(list(RSS_FEEDS.keys()))
        feed = feedparser.parse(RSS_FEEDS[cat])
        if feed.entries:
            title = random.choice(feed.entries[:5]).title.split(" - ")[0][:100]
            return cat, title
        return cat, f"{cat} Future Revolution"
    except:
        cat = random.choice(list(RSS_FEEDS.keys()))
        return cat, f"{cat} is Building Tomorrow"

def gen_caption(cat, topic):
    t = random.choice(CAPTION_TEMPLATES)
    cap = f"{t['hook'].format(topic=topic)}\n\n{t['body'].format(topic=topic)}\n\n{t['cta']}\n\n#StarMindDaily #{cat.replace(' ','')} #FutureIsNow"
    return cap[:1024]

def get_image(topic):
    prompt = f"futuristic {topic}, cinematic ultra realistic 8k"
    enc = requests.utils.quote(prompt)
    return f"https://image.pollinations.ai/prompt/{enc}?width=1080&height=1080&nologo=true&seed={random.randint(1,9999)}"

def post(caption, img_url):
    if not BOT_TOKEN:
        print("BOT_TOKEN missing")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    try:
        r = requests.post(url, data={"chat_id": CHANNEL_ID, "caption": caption, "photo": img_url}, timeout=30)
        print(r.text[:500])
        if r.status_code == 200:
            print("✅ POSTED")
            return True
        # fallback text
        r2 = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={"chat_id": CHANNEL_ID, "text": caption}, timeout=30)
        return r2.status_code == 200
    except Exception as e:
        print(e)
        return False

def main():
    print(f"Started {datetime.now()}")
    cat, topic = get_trending()
    print(f"Topic: {cat} - {topic}")
    cap = gen_caption(cat, topic)
    img = get_image(topic)
    post(cap, img)

if __name__ == "__main__":
    main()
