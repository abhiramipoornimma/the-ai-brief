import os

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

_supabase = None


def get_supabase():
    """Create and reuse the backend Supabase client."""
    global _supabase

    if _supabase is None:
        url = os.getenv("SUPABASE_URL")
        secret_key = os.getenv("SUPABASE_SECRET_KEY")

        if not url or not secret_key:
            raise RuntimeError("Supabase URL or secret key is missing.")

        _supabase = create_client(url, secret_key)

    return _supabase


def register_user(user_id, username=None, first_name=None):
    """Register, approve, and subscribe a Telegram user."""
    return (
        get_supabase()
        .table("telegram_users")
        .upsert(
            {
                "telegram_user_id": user_id,
                "username": username,
                "first_name": first_name,
                "is_approved": True,
                "is_subscribed": True,
            },
            on_conflict="telegram_user_id",
        )
        .execute()
    )


def get_user(user_id):
    result = (
        get_supabase()
        .table("telegram_users")
        .select("*")
        .eq("telegram_user_id", user_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def set_subscription(user_id, subscribed):
    return (
        get_supabase()
        .table("telegram_users")
        .update({"is_subscribed": subscribed})
        .eq("telegram_user_id", user_id)
        .eq("is_approved", True)
        .execute()
    )


def get_subscribers():
    result = (
        get_supabase()
        .table("telegram_users")
        .select("telegram_user_id")
        .eq("is_approved", True)
        .eq("is_subscribed", True)
        .execute()
    )
    return [row["telegram_user_id"] for row in result.data]


def get_seen_story_hashes():
    result = (
        get_supabase()
        .table("sent_stories")
        .select("story_hash")
        .range(0, 999)
        .execute()
    )
    return {row["story_hash"] for row in result.data}


def mark_stories_as_seen(stories):
    if not stories:
        return None

    records = []
    for story in stories:
        records.append({
            "story_hash": story["story_hash"],
            "title": story.get("title", "Untitled"),
            "source": story.get("source"),
            "article_url": story.get("link"),
            "published_at": story.get("published") or None,
        })

    return (
        get_supabase()
        .table("sent_stories")
        .upsert(records, on_conflict="story_hash")
        .execute()
    )
