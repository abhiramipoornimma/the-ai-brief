import asyncio
import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from news import (
    initialize_database,
    fetch_all_sources,
    filter_recent_stories,
    remove_duplicates,
    filter_ai_relevant_stories,
    filter_previously_seen,
    rank_stories,
    mark_as_seen,
)

from report import create_report


# --------------------------------------------------
# Configuration
# --------------------------------------------------

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

subscribers = set()

report_lock = asyncio.Lock()


# --------------------------------------------------
# Prepare news reports
# --------------------------------------------------

def prepare_reports(use_supabase=False):

    if use_supabase:
        from storage import get_seen_story_hashes

        seen_hashes = get_seen_story_hashes()

        logger.info("Using Supabase story history.")

    else:
        initialize_database()
        seen_hashes = None

        logger.info("Using local SQLite story history.")

    logger.info("Fetching news sources.")

    all_stories = fetch_all_sources()

    logger.info("Stories fetched: %s", len(all_stories))

    # Step 1: Keep stories from the last 7 days.
    recent_stories = filter_recent_stories(all_stories)

    logger.info("Recent stories: %s", len(recent_stories))

    # Step 2: Remove duplicate headlines.
    unique_stories = remove_duplicates(recent_stories)

    logger.info("Unique stories: %s", len(unique_stories))

    # Step 3: Keep only AI-relevant stories.
    ai_stories = filter_ai_relevant_stories(unique_stories)

    logger.info("AI-relevant stories: %s", len(ai_stories))

    # Step 4: Exclude previously delivered stories.
    new_stories = filter_previously_seen(
        ai_stories,
        seen_hashes=seen_hashes
    )

    logger.info("New stories: %s", len(new_stories))

    # Step 5: Rank stories by relevance and freshness.
    ranked_stories = rank_stories(new_stories)

    logger.info("Stories ranked successfully.")

    # Step 6: Select the top 3 stories.
    selected_stories = ranked_stories[:3]

    if not selected_stories:
        logger.info("No new AI-relevant stories found.")
        return []

    logger.info(
        "Generating reports for %s stories.",
        len(selected_stories)
    )

    # Step 7: Generate reports using Gemini or fallback.
    reports = create_report(
        selected_stories,
        max_stories=3
    )

    return reports
async def send_news_report(message, use_supabase=False):

    if report_lock.locked():

        await message.reply_text(
            "⏳ A news report is already being prepared. "
            "Please wait."
        )

        return

    async with report_lock:

        status_message = await message.reply_text(
            "📰 Collecting AI news and preparing your report..."
        )

        try:

            prepared_reports = await asyncio.to_thread(
                prepare_reports,
                use_supabase=use_supabase
            )

            if not prepared_reports:

                await status_message.edit_text(
                    "📰 No new AI news stories were found."
                )

                return

            combined_parts = []

            delivered_stories = []

            for index, (report_text, story) in enumerate(
                prepared_reports,
                start=1
            ):

                story_text = report_text.replace(
                    "📰 <b>THE AI BRIEF</b>\n\n",
                    "",
                    1
                )

                story_text = story_text.replace(
                    "<b>",
                    f"<b>{index}. ",
                    1
                )

                combined_parts.append(story_text)

                if story:
                    delivered_stories.append(story)

            combined_report = (
                "📰 <b>THE AI BRIEF</b>\n\n"
                + "\n\n━━━━━━━━━━━━━━━━━━\n\n".join(
                    combined_parts
                )
            )

            if len(combined_report) > 4000:

                raise ValueError(
                    "Combined report exceeds the safe Telegram "
                    "message length. Please shorten the reports."
                )

            await status_message.delete()

            await message.reply_text(
                combined_report,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )

            # Save stories only after successful Telegram delivery.
            if delivered_stories:

                if use_supabase:
                    from storage import mark_stories_as_seen

                    await asyncio.to_thread(
                        mark_stories_as_seen,
                        delivered_stories
                    )

                else:
                    await asyncio.to_thread(
                        mark_as_seen,
                        delivered_stories
                    )

            logger.info(
                "Combined news report delivered successfully."
            )

        except Exception:

            logger.exception(
                "Failed to generate or deliver the news report."
            )

            try:
                await status_message.edit_text(
                    "❌ Something went wrong while preparing "
                    "the news report. Please try again later."
                )
            except Exception:
                pass


# --------------------------------------------------
# /start command
# --------------------------------------------------

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id

    subscribers.add(chat_id)

    await update.message.reply_text(
        "👋 Welcome to <b>The AI Brief</b>!\n\n"
        "Your source for AI news and creator-focused insights.\n\n"
        "Available commands:\n"
        "/now - Get the latest AI news report\n"
        "/status - Check bot status\n"
        "/stop - Stop receiving scheduled updates\n\n"
        "Use /now whenever you want a fresh report.",
        parse_mode=ParseMode.HTML
    )


# --------------------------------------------------
# /stop command
# --------------------------------------------------

async def stop(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id

    subscribers.discard(chat_id)

    await update.message.reply_text(
        "🔕 You have been removed from the subscriber list."
    )


# --------------------------------------------------
# /now command
# --------------------------------------------------

async def now(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await send_news_report(update.message)


# --------------------------------------------------
# /status command
# --------------------------------------------------

async def status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if report_lock.locked():
        report_status = "A report is currently being prepared."
    else:
        report_status = "The bot is ready."

    await update.message.reply_text(
        "🤖 <b>The AI Brief Status</b>\n\n"
        "Status: Running\n"
        f"Report generation: {report_status}\n"
        "News freshness: Last 7 days\n"
        "AI relevance filtering: Enabled\n"
        "Maximum stories per report: 3\n"
        "Story ranking: Enabled\n"
        "Report format: Combined message",
        parse_mode=ParseMode.HTML
    )


# --------------------------------------------------
# Main function
# --------------------------------------------------

def main():

    if not TELEGRAM_BOT_TOKEN:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN is missing from your .env file."
        )

    logger.info("Starting The AI Brief bot...")

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("stop", stop)
    )

    application.add_handler(
        CommandHandler("now", now)
    )

    application.add_handler(
        CommandHandler("status", status)
    )

    logger.info("The AI Brief bot is running.")

    application.run_polling()


# --------------------------------------------------
# Run bot
# --------------------------------------------------

if __name__ == "__main__":
    main()