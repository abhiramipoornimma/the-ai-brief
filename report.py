import logging
import os
import re
import html
import time

from datetime import datetime
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

logger = logging.getLogger(__name__)

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_TIMEOUT = 60000
MAX_RETRIES = 3
RETRY_DELAYS = [5, 15, 30]


# --------------------------------------------------
# Text utilities
# --------------------------------------------------

def format_publish_time(value):
    """Format a publication date for Telegram."""
    if not value:
        return "Date unavailable"

    try:
        published = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
        return published.strftime("%d %b %Y, %H:%M UTC")
    except (ValueError, TypeError, AttributeError):
        return "Date unavailable"


def clean_text(value):
    """Remove HTML and clean text."""
    if not value:
        return ""

    value = html.unescape(str(value))
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", value).strip()


def create_gemini_client():
    """Create the Gemini API client."""
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing from .env")

    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT),
    )


# --------------------------------------------------
# Fallback content generation
# --------------------------------------------------

def create_fallback_summary(title, summary):
    """Create a useful summary from available RSS information."""

    if not summary:
        return (
            f"The RSS feed provides the headline '{title}', "
            "but does not include an article description. "
            "Open the original article for the full details."
        )

    # Split the RSS description into readable sentences.
    sentences = re.split(r"(?<=[.!?])\s+", summary)

    # Keep up to three sentences.
    result = " ".join(sentences[:3]).strip()

    # Avoid excessively long Telegram summaries.
    if len(result) > 650:
        result = result[:647].rsplit(" ", 1)[0] + "..."

    return result


def create_fallback_why(title, summary):
    """
    Generate a topic-specific explanation using only
    the information available in the headline and RSS summary.
    """

    text = f"{title} {summary}".lower()

    topics = [
        (
            ["cybersecurity", "cyber security", "security breach",
             "vulnerability", "hacking", "malware", "ransomware"],
            "AI security and cybersecurity are important areas to follow. "
            "This story is relevant to understanding the security risks "
            "and challenges associated with technology."
        ),
        (
            ["creator", "content creation", "video generation",
             "image generation", "editing", "youtube"],
            "This development is relevant to content creators because "
            "AI tools can influence how digital content is created, "
            "edited, and produced."
        ),
        (
            ["chatgpt", "openai", "gemini", "claude",
             "language model", "llm", "ai model"],
            "AI models are central to the development of modern AI tools. "
            "This story provides insight into how the AI model landscape "
            "and its capabilities are evolving."
        ),
        (
            ["robot", "robotics", "autonomous", "self-driving"],
            "Developments in robotics and autonomous systems can influence "
            "how AI is applied in physical environments and real-world tasks."
        ),
        (
            ["research", "researcher", "study", "scientist",
             "scientific", "university"],
            "AI research helps shape future technologies and applications. "
            "This story offers a look at the research developments "
            "taking place in the field."
        ),
        (
            ["business", "enterprise", "partnership", "company",
             "startup", "workflows"],
            "The adoption of AI in business can influence productivity, "
            "workflows, and the way organizations use technology. "
            "This development is relevant to people following AI's "
            "commercial applications."
        ),
    ]

    for keywords, explanation in topics:
        if any(keyword in text for keyword in keywords):
            return explanation

    return (
        "This story highlights a development in artificial intelligence. "
        "Following these developments helps readers understand the "
        "changing AI landscape and its potential applications."
    )


def create_fallback_hooks(title):
    """Create three distinct hooks based on the actual story headline."""

    title = title.rstrip(".!? ")

    return [
        f"What is happening with {title}?",
        f"Why should AI enthusiasts pay attention to {title}?",
        f"What could happen next after {title}?"
    ]


def create_fallback(title, summary):
    """Create a complete fallback report without Gemini."""

    return {
        "headline": title,
        "summary": create_fallback_summary(title, summary),
        "why": create_fallback_why(title, summary),
        "hooks": create_fallback_hooks(title),
    }


# --------------------------------------------------
# Gemini error handling
# --------------------------------------------------

def is_daily_quota_error(exc):
    """Identify daily quota errors that will not improve with retries."""

    message = str(exc).lower()

    return any(
        phrase in message
        for phrase in [
            "per day",
            "per_day",
            "daily quota",
            "requests per day",
            "free_tier_requests",
            "daily limit",
        ]
    )


def is_temporary_error(exc):
    """Check whether an error may be temporary."""

    if is_daily_quota_error(exc):
        return False

    message = str(exc).upper()

    temporary_errors = [
        "503",
        "504",
        "UNAVAILABLE",
        "DEADLINE_EXCEEDED",
        "RESOURCE_EXHAUSTED",
        "429",
        "INTERNAL",
        "500",
    ]

    return any(error in message for error in temporary_errors)


# --------------------------------------------------
# Gemini response parsing
# --------------------------------------------------

def extract_field(block, field_name):
    """Extract one field from a Gemini story block."""

    pattern = (
        rf"^{re.escape(field_name)}\s*:\s*"
        rf"(.*?)"
        rf"(?=^(?:HEADLINE|SUMMARY|WHY IT MATTERS|HOOK 1|HOOK 2|HOOK 3)\s*:|\Z)"
    )

    match = re.search(
        pattern,
        block,
        flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )

    if not match:
        return ""

    return clean_text(match.group(1))


def parse_gemini_response(response_text, story_count):
    """Parse all story sections returned by Gemini."""

    results = []

    for index in range(1, story_count + 1):

        pattern = (
            rf"\[STORY\s*{index}\]"
            rf"(.*?)"
            rf"\[/STORY\s*{index}\]"
        )

        match = re.search(
            pattern,
            response_text,
            flags=re.IGNORECASE | re.DOTALL,
        )

        if not match:
            results.append(None)
            continue

        block = match.group(1)

        story_data = {
            "headline": extract_field(block, "HEADLINE"),
            "summary": extract_field(block, "SUMMARY"),
            "why": extract_field(block, "WHY IT MATTERS"),
            "hooks": [
                extract_field(block, "HOOK 1"),
                extract_field(block, "HOOK 2"),
                extract_field(block, "HOOK 3"),
            ],
        }

        if not all([
            story_data["headline"],
            story_data["summary"],
            story_data["why"],
            *story_data["hooks"],
        ]):
            results.append(None)
        else:
            results.append(story_data)

    return results


# --------------------------------------------------
# Gemini content generation
# --------------------------------------------------

def generate_all_stories(stories, client):
    """
    Generate content for every selected story
    using ONE Gemini API request.
    """

    story_inputs = []

    for index, story in enumerate(stories, start=1):

        title = clean_text(story.get("title", "Untitled"))

        summary = clean_text(
            story.get("summary", "")
            or story.get("description", "")
        )

        source = clean_text(
            story.get("source", "Unknown source")
        )

        story_inputs.append(
            f"""
STORY {index}
SOURCE: {source}
TITLE: {title}
RSS SUMMARY: {summary}
"""
        )

    prompt = f"""
You are the editorial assistant for The AI Brief.

Create a concise, informative report for each AI news story.

AUDIENCE:
AI enthusiasts, technology followers, and digital content creators.

IMPORTANT RULES:

- Use only information supplied in the headlines and RSS summaries.
- Never invent facts, statistics, quotes, dates, or developments.
- Write a meaningful summary of approximately 2-3 sentences.
- Explain WHY IT MATTERS specifically for the individual story.
- Avoid generic explanations that could apply to every news story.
- Connect the significance to AI enthusiasts, creators, businesses,
  researchers, or technology users when supported by the information.
- Make all three video hooks unique and specific to their story.
- Hooks should be engaging and suitable for short-form videos.
- Do not repeat the headline as the summary.
- If information is limited, clearly acknowledge the limitation.
- Return every story in the exact format requested below.
- Do not add an introduction or conclusion.

FOR EACH STORY, USE THIS EXACT FORMAT:

[STORY 1]
HEADLINE: A clear headline
SUMMARY: A concise 2-3 sentence summary
WHY IT MATTERS: A story-specific explanation
HOOK 1: An engaging short-form video hook
HOOK 2: A different engaging video hook
HOOK 3: Another unique video hook
[/STORY 1]

Replace the story number for each additional story.

NEWS STORIES:

{"".join(story_inputs)}
"""

    for attempt in range(MAX_RETRIES):

        try:

            response = client.models.generate_content(
                model=MODEL,
                contents=prompt,
            )

            if not response.text:
                raise ValueError(
                    "Gemini returned an empty response."
                )

            parsed = parse_gemini_response(
                response.text,
                len(stories),
            )

            return parsed

        except Exception as exc:

            logger.warning(
                "Gemini batch request failed: %s",
                exc,
            )

            if is_daily_quota_error(exc):

                logger.error(
                    "Gemini daily quota exhausted. Skipping retries."
                )

                break

            if not is_temporary_error(exc):
                break

            if attempt < MAX_RETRIES - 1:

                delay = RETRY_DELAYS[attempt]

                logger.warning(
                    "Retrying Gemini request in %s seconds.",
                    delay,
                )

                time.sleep(delay)

    return [None] * len(stories)


# --------------------------------------------------
# Create Telegram reports
# --------------------------------------------------

def create_report(stories, max_stories=3):
    """
    Create Telegram reports.

    All selected stories are sent to Gemini in one API request.
    If Gemini fails, story-specific fallback content is used.

    Returns a list of (report_text, original_story) tuples.
    """

    selected_stories = stories[:max_stories]

    if not selected_stories:
        return []

    try:

        client = create_gemini_client()

        generated_results = generate_all_stories(
            selected_stories,
            client,
        )

    except Exception:

        logger.exception(
            "Could not initialize Gemini."
        )

        generated_results = [None] * len(selected_stories)

    prepared_reports = []

    for index, story in enumerate(selected_stories):

        original_title = clean_text(
            story.get("title", "Untitled")
        )

        original_summary = clean_text(
            story.get("summary", "")
            or story.get("description", "")
        )

        generated = generated_results[index]

        # Use improved fallback if Gemini is unavailable
        # or returns an incomplete response.
        if generated is None:

            generated = create_fallback(
                original_title,
                original_summary,
            )

        headline = html.escape(
            generated["headline"]
        )

        summary = html.escape(
            generated["summary"]
        )

        why = html.escape(
            generated["why"]
        )

        hooks = generated["hooks"]

        source = html.escape(
            clean_text(
                story.get("source", "Unknown source")
            )
        )

        published = format_publish_time(
            story.get("published")
            or story.get("published_at")
            or story.get("published_at_utc")
        )

        link = story.get("link", "")

        if link.startswith(("https://", "http://")):

            safe_link = html.escape(
                link,
                quote=True
            )

            article_link = (
                f'<a href="{safe_link}">Read full article</a>'
            )

        else:

            article_link = "Article link unavailable"

        report_text = (
            f"📰 <b>THE AI BRIEF</b>\n\n"

            f"<b>{headline}</b>\n\n"

            f"<b>Summary</b>\n"
            f"{summary}\n\n"

            f"<b>Why it matters</b>\n"
            f"{why}\n\n"

            f"<b>Video hooks</b>\n"
            f"1. {html.escape(hooks[0])}\n"
            f"2. {html.escape(hooks[1])}\n"
            f"3. {html.escape(hooks[2])}\n\n"

            f"🗞 <b>Source:</b> {source}\n"
            f"🕒 <b>Published:</b> {published}\n"
            f"🔗 {article_link}"
        )

        prepared_reports.append(
            (report_text, story)
        )

    return prepared_reports