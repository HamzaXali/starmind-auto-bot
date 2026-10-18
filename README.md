StarMind Auto Bot — Pro upgrade
What changed
Selects the newest unseen story from four RSS topic feeds.
Uses a varied hook, a short story summary, a “why it matters” line, CTA, source link and topic hashtags.
Generates a conceptual square editorial image URL.
Falls back to a text post if the image post fails.
Tracks posted stories in seen_articles.json to reduce duplicate posts.
Adds logs, request timeouts, concurrency protection and a manual run button.
Install
Replace main.py with the upgraded file.
Replace .github/workflows/daily-post.yml with the workflow in this package.
In GitHub, open Settings → Secrets and variables → Actions and confirm:
TELEGRAM_BOT_TOKEN
TELEGRAM_CHANNEL_ID
Open Settings → Actions → General → Workflow permissions and allow Read and write permissions so the workflow can save seen_articles.json.
Go to Actions → StarMind Pro - 6 Daily Posts → Run workflow to test.
Important notes
GitHub Actions cron is UTC, not London time. UK and US daylight-saving changes mean local posting times move seasonally.
The bot posts to Telegram; it does not automatically publish to Facebook, Instagram, TikTok, or X.
This is SEO-aware Telegram content formatting, not a guarantee of search rankings or virality.
RSS titles and summaries may contain errors. Review important or sensitive claims before relying on them.
The image provider is external and may be slow or unavailable; the bot has a text-only fallback.
permissions: contents: write and repository workflow permissions are needed for duplicate history persistence.

# starmind-auto-bot
![Status](https://github.com/HamzaXali/starmind-auto-bot/actions/workflows/daily-post.yml/badge.svg)

