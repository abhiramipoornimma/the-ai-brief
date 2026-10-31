CREATE TABLE IF NOT EXISTS public.telegram_users (
    telegram_user_id BIGINT PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    is_approved BOOLEAN NOT NULL DEFAULT FALSE,
    is_subscribed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.sent_stories (
    story_hash TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source TEXT,
    article_url TEXT,
    published_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.telegram_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sent_stories ENABLE ROW LEVEL SECURITY;