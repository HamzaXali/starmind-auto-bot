
def update_growth_stats():
    """Record daily Telegram channel member counts safely."""
    try:
        result = telegram_api(
            "getChatMemberCount",
            {"chat_id": CHANNEL_ID}
        )
        count = int(result)
    except Exception as exc:
        logging.warning(
            "Could not retrieve channel member count: %s", exc
        )
        return

    stats = load_json(GROWTH_FILE, {})
    if not isinstance(stats, dict):
        stats = {}

    today = datetime.now(timezone.utc).date().isoformat()
    previous = stats.get(today)

    # Handle missing or malformed daily records safely.
    if not isinstance(previous, dict):
        previous = {}

    first_check_today = "first_members" not in previous

    try:
        first_count = int(previous.get("first_members", count))
    except (TypeError, ValueError):
        first_count = count
        first_check_today = True

    # Save today's first count and the latest count.
    stats[today] = {
        "first_members": first_count,
        "members": count,
        "change_since_first_check_today": count - first_count,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    # Retain only the latest MAX_GROWTH_DAYS daily entries.
    for old_day in sorted(stats)[:-MAX_GROWTH_DAYS]:
        stats.pop(old_day, None)

    try:
        save_json(GROWTH_FILE, stats)
    except OSError:
        logging.exception("Could not save channel growth statistics")
        return

    if first_check_today:
        logging.info(
            "Channel members: %s; today's change: unavailable "
            "(first count recorded today)",
            count
        )
    else:
        logging.info(
            "Channel members: %s; today's change since first check: %s",
            count,
            count - first_count
        )
