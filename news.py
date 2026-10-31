import hashlib
import logging
import re
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import feedparser
import httpx

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent / "news.db"

SOURCES = {
    "MIT Technology Review": "https://www.technologyreview.com/feed/",
    "OpenAI News": "https://openai.com/news/rss.xml",
    "Google AI": "https://blog.google/technology/ai/rss/",
    "Google DeepMind": "https://deepmind.google/blog/rss.xml",
    "The Verge AI": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
}

REQUEST_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

NEWS_MAX_AGE_DAYS = 7

MIN_AI_RELEVANCE_SCORE = 4


# --------------------------------------------------
# AI KEYWORD DETECTION
# --------------------------------------------------

# Strong AI-related phrases.
# These receive more weight when they appear in headlines.

AI_KEYWORDS = {
    "artificial intelligence": 6,
    "generative ai": 7,
    "machine learning": 6,
    "deep learning": 6,
    "large language model": 7,
    "large language models": 7,
    "language model": 6,
    "language models": 6,
    "frontier model": 7,
    "frontier models": 7,
    "foundation model": 7,
    "foundation models": 7,
    "ai model": 7,
    "ai models": 7,
    "ai agent": 7,
    "ai agents": 7,
    "agentic ai": 7,
    "ai assistant": 6,
    "ai assistants": 6,
    "ai chatbot": 6,
    "ai chatbots": 6,
    "ai research": 7,
    "ai security": 7,
    "ai safety": 7,
    "ai generated": 6,
    "ai-generated": 6,
    "ai powered": 6,
    "ai-powered": 6,
    "computer vision": 5,
    "natural language processing": 6,
    "neural network": 5,
    "neural networks": 5,
    "diffusion model": 6,
    "diffusion models": 6,
    "image generation": 6,
    "video generation": 6,
    "text-to-image": 5,
    "text-to-video": 5,
    "speech recognition": 5,
    "voice cloning": 5,
    "model training": 5,
    "model inference": 5,
    "fine-tuning": 5,
    "retrieval augmented generation": 6,
    "retrieval-augmented generation": 6,
    "large reasoning model": 6,
    "reasoning model": 6,
}

# AI companies and products.
# These help detect stories whose headlines mention product names
# instead of explicitly saying "artificial intelligence".

AI_BRANDS = {
    "openai": 5,
    "chatgpt": 6,
    "anthropic": 5,
    "claude": 6,
    "gemini": 6,
    "deepmind": 5,
    "copilot": 5,
    "perplexity": 5,
    "midjourney": 5,
    "sora": 5,
    "grok": 5,
    "character.ai": 5,
    "mistral": 5,
    "hugging face": 5,
    "stability ai": 6,
    "runway": 4,
    "elevenlabs": 5,
}

# Short or model-specific terms that need word boundaries.
AI_PATTERNS = [
    r"\bai\b",
    r"\bllm(?:s)?\b",
    r"\brag\b",
    r"\bgpt(?:-\d+(?:\.\d+)?(?:-[a-z0-9]+)*)?\b",
    r"\bgemini(?:\s+\d+(?:\.\d+)?)?\b",
    r"\bclaude(?:\s+\d+(?:\.\d+)?)?\b",
    r"\bgrok(?:\s+\d+(?:\.\d+)?)?\b",
    r"\bdeepseek\b",
    r"\bqwen\b",
    r"\blama\s*\d*\b",
    r"\bphi-\d+\b",
    r"\bcommand-r\b",
    r"\bagi\b",
    r"\bsynthetic data\b",
    r"\bmodel alignment\b",
    r"\bmodel misalignment\b",
]


# --------------------------------------------------
# NEWSLETTER FILTERING
# --------------------------------------------------

NEWSLETTER_PREFIXES = [
    r"^the download\s*:",
    r"^the algorithm\s*:",
    r"^the ai briefing\s*:",
    r"^the daily briefing\s*:",
]


def is_general_newsletter(story):

    title = story.get("title", "").strip().lower()

    for pattern in NEWSLETTER_PREFIXES:

        if re.search(pattern, title, re.IGNORECASE):
            return True

    return False


# --------------------------------------------------
# DATABASE
# --------------------------------------------------

def initialize_database():

    with sqlite3.connect(DB_PATH) as connection:

        connection.execute("""
            CREATE TABLE IF NOT EXISTS seen_stories (
                title_hash TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        connection.commit()


# --------------------------------------------------
# NORMALIZATION
# --------------------------------------------------

def normalize_title(title):

    title = (title or "").lower().strip()

    title = re.sub(r"https?://\S+", "", title)

    title = re.sub(r"[^a-z0-9]+", " ", title)

    return " ".join(title.split())


def title_hash(title):

    normalized = normalize_title(title)

    return hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()


# --------------------------------------------------
# RSS HELPERS
# --------------------------------------------------

def _entry_text(entry, *keys):

    for key in keys:

        value = entry.get(key)

        if value:

            if isinstance(value, list):

                value = " ".join(
                    str(item.get("value", ""))
                    for item in value
                )

            return str(value).strip()

    return ""


def _published(entry):

    raw = entry.get("published") or entry.get("updated") or ""

    parsed = (
        entry.get("published_parsed")
        or entry.get("updated_parsed")
    )

    if parsed:

        try:

            return datetime(
                *parsed[:6],
                tzinfo=timezone.utc
            ).isoformat()

        except (TypeError, ValueError):
            pass

    if raw:

        try:

            dt = parsedate_to_datetime(raw)

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            return dt.astimezone(timezone.utc).isoformat()

        except (TypeError, ValueError, OverflowError):
            return ""

    return ""


# --------------------------------------------------
# CHECK NEWS FRESHNESS
# --------------------------------------------------

def is_recent_story(story):

    published = story.get("published", "")

    if not published:
        return False

    try:

        published_date = datetime.fromisoformat(
            published.replace("Z", "+00:00")
        )

        if published_date.tzinfo is None:

            published_date = published_date.replace(
                tzinfo=timezone.utc
            )

        published_date = published_date.astimezone(
            timezone.utc
        )

        age = datetime.now(timezone.utc) - published_date

        return (
            timedelta(0) <= age <=
            timedelta(days=NEWS_MAX_AGE_DAYS)
        )

    except (ValueError, TypeError, OverflowError):

        return False


# --------------------------------------------------
# CALCULATE AI RELEVANCE
# --------------------------------------------------

def calculate_ai_relevance(story):

    title = story.get("title", "").lower()
    summary = story.get("summary", "").lower()

    title_score = 0
    summary_score = 0

    # Strong AI-related phrases.
    for keyword, weight in AI_KEYWORDS.items():

        if keyword in title:
            title_score += weight

        if keyword in summary:
            summary_score += max(1, weight // 3)

    # AI company and product names.
    for keyword, weight in AI_BRANDS.items():

        pattern = rf"\b{re.escape(keyword)}\b"

        if re.search(pattern, title):
            title_score += weight

        if re.search(pattern, summary):
            summary_score += max(1, weight // 3)

    # AI model names and abbreviations.
    for pattern in AI_PATTERNS:

        if re.search(pattern, title, re.IGNORECASE):
            title_score += 5

        if re.search(pattern, summary, re.IGNORECASE):
            summary_score += 2

    return title_score + summary_score


# --------------------------------------------------
# FILTER AI-RELEVANT STORIES
# --------------------------------------------------

def filter_ai_relevant_stories(stories):

    relevant_stories = []
    rejected_count = 0
    newsletter_count = 0

    for story in stories:

        # Exclude general newsletter roundups.
        if is_general_newsletter(story):

            newsletter_count += 1

            logger.info(
                "Excluded newsletter roundup: %s",
                story.get("title", "Untitled")
            )

            continue

        relevance_score = calculate_ai_relevance(story)

        if relevance_score >= MIN_AI_RELEVANCE_SCORE:

            story["ai_relevance_score"] = relevance_score

            relevant_stories.append(story)

        else:

            rejected_count += 1

            logger.info(
                "Excluded non-AI story: %s",
                story.get("title", "Untitled")
            )

    logger.info(
        "AI filter results: %s relevant, %s unrelated, "
        "%s newsletters excluded",
        len(relevant_stories),
        rejected_count,
        newsletter_count
    )

    return relevant_stories


# --------------------------------------------------
# FETCH ONE RSS SOURCE
# --------------------------------------------------

def fetch_source(source_name, feed_url):

    try:

        response = httpx.get(
            feed_url,
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
            headers={
                "User-Agent": "The-AI-Brief/1.0 (RSS news reader)"
            },
        )

        response.raise_for_status()

        feed = feedparser.parse(response.text)

        if feed.bozo and not feed.entries:

            raise ValueError(
                f"RSS parsing failed: {feed.bozo_exception}"
            )

        stories = []

        for entry in feed.entries:

            title = _entry_text(entry, "title")

            link = _entry_text(entry, "link")

            summary = _entry_text(
                entry,
                "summary",
                "description"
            )

            if not title or not link:
                continue

            stories.append({
                "title": title,
                "link": link,
                "summary": re.sub(
                    r"<[^>]+>",
                    " ",
                    summary
                ).strip(),
                "source": source_name,
                "published": _published(entry),
            })

        logger.info(
            "%s: fetched %s stories",
            source_name,
            len(stories)
        )

        return stories

    except Exception:

        logger.exception(
            "Could not fetch source: %s",
            source_name
        )

        return []


# --------------------------------------------------
# FETCH ALL SOURCES CONCURRENTLY
# --------------------------------------------------

def fetch_all_sources():

    all_stories = []

    logger.info("Starting parallel news collection.")

    with ThreadPoolExecutor(max_workers=5) as executor:

        futures = {
            executor.submit(
                fetch_source,
                source_name,
                feed_url
            ): source_name

            for source_name, feed_url in SOURCES.items()
        }

        for future in as_completed(futures):

            source_name = futures[future]

            try:

                stories = future.result()

                all_stories.extend(stories)

            except Exception:

                logger.exception(
                    "Failed to process source: %s",
                    source_name
                )

    logger.info(
        "News collection completed. Total stories: %s",
        len(all_stories)
    )

    return all_stories


# --------------------------------------------------
# FILTER STORIES FROM LAST 7 DAYS
# --------------------------------------------------

def filter_recent_stories(stories):

    recent_stories = []

    for story in stories:

        if is_recent_story(story):
            recent_stories.append(story)

    logger.info(
        "Freshness filter: %s recent stories out of %s",
        len(recent_stories),
        len(stories)
    )

    return recent_stories


# --------------------------------------------------
# REMOVE DUPLICATES
# --------------------------------------------------

def remove_duplicates(stories):

    unique = []

    seen_hashes = set()

    for story in stories:

        identifier = title_hash(
            story.get("title", "")
        )

        if not identifier or identifier in seen_hashes:
            continue

        seen_hashes.add(identifier)

        unique.append(story)

    return unique


# --------------------------------------------------
# FILTER PREVIOUSLY SEEN STORIES
# --------------------------------------------------

def filter_previously_seen(stories, seen_hashes=None):

    new_stories = []

    # Vercel mode: use story hashes retrieved from Supabase.
    if seen_hashes is not None:

        for story in stories:

            identifier = title_hash(
                story.get("title", "")
            )

            story["story_hash"] = identifier

            if identifier not in seen_hashes:
                new_stories.append(story)

        return new_stories

    # Local mode: continue using the existing SQLite database.
    initialize_database()

    with sqlite3.connect(DB_PATH) as connection:

        for story in stories:

            identifier = title_hash(
                story.get("title", "")
            )

            story["story_hash"] = identifier

            result = connection.execute(
                """
                SELECT 1
                FROM seen_stories
                WHERE title_hash = ?
                """,
                (identifier,)
            ).fetchone()

            if result is None:
                new_stories.append(story)

    return new_stories


# --------------------------------------------------
# RANK STORIES BY IMPORTANCE
# --------------------------------------------------

def rank_stories(stories):

    priority_keywords = {
        "artificial intelligence": 6,
        "generative ai": 6,
        "ai model": 6,
        "large language model": 6,
        "frontier model": 6,
        "ai agent": 5,
        "machine learning": 4,
        "ai research": 5,
        "ai security": 5,
        "ai safety": 5,
        "openai": 4,
        "deepmind": 4,
        "chatgpt": 4,
        "gemini": 4,
        "claude": 4,
        "anthropic": 4,
        "gpt": 4,
        "video generation": 4,
        "image generation": 4,
        "computer vision": 4,
        "neural network": 4,
        "model release": 5,
        "launches": 2,
        "announces": 2,
        "introduces": 2,
        "researchers": 2,
        "breakthrough": 3,
        "security vulnerability": 3,
        "cybersecurity": 1,
    }

    def calculate_score(story):

        title = story.get("title", "").lower()

        summary = story.get("summary", "").lower()

        text = title + " " + summary

        # Start with the AI relevance score.
        score = story.get(
            "ai_relevance_score",
            calculate_ai_relevance(story)
        )

        # Give additional weight to important developments.
        for keyword, weight in priority_keywords.items():

            if keyword in title:
                score += weight

            elif keyword in summary:
                score += max(1, weight // 2)

        # Prefer stories with useful publication dates.
        try:

            published = datetime.fromisoformat(
                story["published"].replace("Z", "+00:00")
            )

            if published.tzinfo is None:

                published = published.replace(
                    tzinfo=timezone.utc
                )

            age_hours = (
                datetime.now(timezone.utc) -
                published.astimezone(timezone.utc)
            ).total_seconds() / 3600

            if 0 <= age_hours <= 24:
                score += 3

            elif age_hours <= 72:
                score += 2

            elif age_hours <= 120:
                score += 1

        except (KeyError, ValueError, TypeError):
            pass

        return score

    # Sort strictly by score.
    # Do not move lower-ranked stories ahead for source diversity.
    ranked = sorted(
        stories,
        key=calculate_score,
        reverse=True
    )

    logger.info(
        "Story ranking completed: %s stories",
        len(ranked)
    )

    return ranked


# --------------------------------------------------
# MARK STORIES AS SEEN
# --------------------------------------------------

def mark_as_seen(stories):

    if not stories:
        return

    initialize_database()

    with sqlite3.connect(DB_PATH) as connection:

        for story in stories:

            connection.execute(
                """
                INSERT OR IGNORE INTO seen_stories
                (title_hash, title)
                VALUES (?, ?)
                """,
                (
                    title_hash(story.get("title", "")),
                    story.get("title", "Untitled")
                )
            )

        connection.commit()


# --------------------------------------------------
# TEST NEWS COLLECTION
# --------------------------------------------------

if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    initialize_database()

    all_stories = fetch_all_sources()

    print(f"\nStories collected: {len(all_stories)}")

    recent_stories = filter_recent_stories(all_stories)

    print(
        f"Stories from last 7 days: {len(recent_stories)}"
    )

    unique_stories = remove_duplicates(recent_stories)

    print(
        f"After duplicate removal: {len(unique_stories)}"
    )

    ai_stories = filter_ai_relevant_stories(unique_stories)

    print(
        f"After AI relevance filtering: {len(ai_stories)}"
    )

    new_stories = filter_previously_seen(ai_stories)

    print(
        f"Not previously recorded: {len(new_stories)}"
    )

    ranked_stories = rank_stories(new_stories)

    print("\nTop 10 AI-relevant stories:")

    for index, story in enumerate(
        ranked_stories[:10],
        start=1
    ):

        print(f"\n{index}. {story['title']}")
        print(f"Source: {story['source']}")

        print(
            "AI relevance score:",
            story.get("ai_relevance_score", 0)
        )

        print(f"Published: {story['published']}")
        print(f"Link: {story['link']}")