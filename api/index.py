import asyncio
import json
import logging
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


def env(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value


def telegram_request(method, payload):
    token = env("TELEGRAM_BOT_TOKEN")
    response = httpx.post(
        f"{TELEGRAM_API}/bot{token}/{method}",
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")

    return result.get("result")


def send_message(chat_id, text):
    return telegram_request(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
    )


def get_storage():
    import storage
    return storage


def approved_user(user_id):
    user = get_storage().get_user(user_id)
    return bool(user and user.get("is_approved"))


def handle_start(message):
    user = message.get("from", {})
    user_id = user.get("id")
    chat_id = message["chat"]["id"]

    get_storage().register_user(
        user_id,
        user.get("username"),
        user.get("first_name"),
    )

    if not approved_user(user_id):
        send_message(
            chat_id,
            "Welcome to <b>The AI Brief</b>!\n\n"
            "Your access request has been registered. "
            "An administrator must approve your account before you can receive reports.",
        )
        return

    get_storage().set_subscription(user_id, True)
    send_message(
        chat_id,
        "Welcome back to <b>The AI Brief</b>!\n\n"
        "You are approved and subscribed to hourly AI news reports.\n\n"
        "Commands:\n"
        "/now - Get a report now\n"
        "/status - Check your status\n"
        "/stop - Stop hourly reports",
    )


def handle_message(message):
    text = (message.get("text") or "").strip()
    if not text.startswith("/"):
        return

    command = text.split()[0].split("@")[0].lower()
    user_id = message.get("from", {}).get("id")
    chat_id = message["chat"]["id"]

    if command == "/start":
        handle_start(message)
        return

    if not user_id or not approved_user(user_id):
        send_message(chat_id, "Your account is not approved yet.")
        return

    if command == "/stop":
        get_storage().set_subscription(user_id, False)
        send_message(chat_id, "Hourly reports have been stopped. Send /start to subscribe again.")

    elif command == "/status":
        user = get_storage().get_user(user_id)
        subscribed = user.get("is_subscribed", False)
        status = "Active" if subscribed else "Stopped"
        send_message(chat_id, f"Your hourly report subscription is: <b>{status}</b>.")

    elif command == "/now":
        send_message(chat_id, "Preparing your AI news report. Please wait...")
        try:
            reports = prepare_reports()
            if not reports:
                send_message(chat_id, "No new AI stories are available right now.")
                return

            for report_text, story in reports:
                send_message(chat_id, report_text)

            get_storage().mark_stories_as_seen(
                [story for _, story in reports]
            )

        except Exception:
            logger.exception("Unable to prepare an on-demand report")
            send_message(chat_id, "Sorry, I couldn't prepare the report. Please try again later.")

    else:
        send_message(chat_id, "Unknown command. Try /now, /status, or /stop.")


def prepare_reports():
    from bot import prepare_reports as create_reports
    return create_reports(use_supabase=True)


def run_hourly_report():
    storage = get_storage()
    subscribers = storage.get_subscribers()

    if not subscribers:
        logger.info("No approved subscribers.")
        return

    reports = prepare_reports()
    if not reports:
        logger.info("No new stories.")
        return

    stories = [story for _, story in reports]
    all_succeeded = True

    for chat_id in subscribers:
        try:
            for report_text, story in reports:
                send_message(chat_id, report_text)
        except Exception:
            all_succeeded = False
            logger.exception("Failed to send report to Telegram chat %s", chat_id)

    if all_succeeded:
        storage.mark_stories_as_seen(stories)
    else:
        logger.warning("Some deliveries failed; stories were not marked as seen.")


class handler(BaseHTTPRequestHandler):

    def respond(self, status, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path

        if path not in ("/api", "/api/"):
            self.respond(404, {"error": "Not found"})
            return

        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {env('CRON_SECRET')}"

        if supplied != expected:
            self.respond(401, {"error": "Unauthorized"})
            return

        try:
            run_hourly_report()
            self.respond(200, {"ok": True, "message": "Hourly report completed"})
        except Exception:
            logger.exception("Hourly report failed")
            self.respond(500, {"ok": False, "error": "Report failed"})

    def do_POST(self):
        path = urlparse(self.path).path

        if path not in ("/api", "/api/"):
            self.respond(404, {"error": "Not found"})
            return

        supplied = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        expected = env("TELEGRAM_WEBHOOK_SECRET")

        if supplied != expected:
            self.respond(401, {"error": "Unauthorized"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            update = json.loads(self.rfile.read(length) or b"{}")

            message = update.get("message") or update.get("edited_message")
            if message:
                handle_message(message)

            self.respond(200, {"ok": True})

        except Exception:
            logger.exception("Webhook update failed")
            self.respond(200, {"ok": True})

    def log_message(self, format, *args):
        logger.info(format, *args)