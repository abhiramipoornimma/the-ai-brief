📰 The AI Brief

Your automated briefing on the latest developments in Artificial Intelligence.

The AI Brief is a Telegram-based AI news reporting bot that collects the latest AI-related news, generates concise summaries using Google Gemini, and delivers news reports directly to subscribers.

🚀 Features

- Automated AI News Collection – Fetches news from multiple technology and AI sources.
- AI-Powered Summaries – Uses Google Gemini to generate easy-to-understand news reports.
- Telegram Integration – Delivers reports directly through a Telegram bot.
- Hourly Automation – Uses cron-job.org to trigger scheduled news delivery.
- On-Demand Reports – Users can request the latest news whenever they want.
- User Management – Registers Telegram users and manages their subscriptions.
- Duplicate Prevention – Tracks previously delivered stories using Supabase.
- Cloud Deployment – Runs through Vercel serverless functions.

🛠️ Technologies Used

Technology| Purpose
Python| Core programming language
Telegram Bot API| User interaction and news delivery
Google Gemini API| AI-powered news summarization
Supabase| Cloud database and user management
Vercel| Serverless deployment
cron-job.org| Hourly scheduled execution
Feedparser| RSS news collection
HTTPX| HTTP requests

📰 News Sources

The bot collects AI-related news from sources including:

- MIT Technology Review
- OpenAI News
- Google AI
- Google DeepMind
- The Verge AI

News articles are filtered based on their publication date and AI relevance.

🤖 Telegram Bot Commands

Find the bot: "@TheAIBriefNewsBot" (https://t.me/TheAIBriefNewsBot)

Command| Description
"/start"| Register and activate your subscription
"/now"| Receive an AI news report immediately
"/status"| Check subscription status
"/stop"| Stop hourly news reports

New users are automatically registered, approved, and subscribed.

⚙️ Project Structure

The-AI-Brief/
│
├── api/
│   └── index.py
│
├── bot.py
├── news.py
├── report.py
├── storage.py
├── test_real_news.py
│
├── supabase_setup.sql
├── requirements.txt
├── vercel.json
├── .gitignore
└── README.md

💻 Run Locally

1. Clone the repository

git clone https://github.com/abhiramipoornimma/the-ai-brief.git

2. Navigate to the project

cd The-AI-Brief

3. Create a virtual environment

python -m venv .venv

4. Activate the environment

Windows:

.venv\Scripts\Activate.ps1

5. Install dependencies

pip install -r requirements.txt

6. Configure environment variables

Create a ".env" file in the project root:

TELEGRAM_BOT_TOKEN=
GEMINI_API_KEY=
GEMINI_MODEL=

SUPABASE_URL=
SUPABASE_KEY=
SUPABASE_SECRET_KEY=

TELEGRAM_WEBHOOK_SECRET=
CRON_SECRET=

Add your own credentials. Never commit your ".env" file or expose secret keys publicly.

7. Start the bot

python bot.py

☁️ Deployment Architecture

The project uses the following workflow:

1. cron-job.org triggers the Vercel API endpoint every hour.
2. Vercel executes the serverless Python application.
3. News collection retrieves recent AI-related articles from RSS feeds.
4. Google Gemini generates concise news summaries.
5. Supabase manages subscribers and previously delivered stories.
6. Telegram Bot API delivers reports to active subscribers.

The scheduled endpoint is protected using a secret authorization header.

🗄️ Database

Supabase is used for cloud-based data storage.

Main database tables:

- "telegram_users" – Stores Telegram user information, approval status, and subscription status.
- "sent_stories" – Tracks successfully delivered news stories to prevent duplicates.

Row Level Security (RLS) is enabled on the database tables. Backend access uses the Supabase secret key.

🔐 Security

- Environment variables are used to protect API credentials.
- Secret keys are not included in the source code.
- Telegram webhook requests are verified using a secret token.
- Scheduled API requests require authorization.
- Supabase credentials are stored in the deployment environment.

📌 Project Status

Deployment: Vercel
Telegram Bot: Active
Database: Supabase
Scheduled Automation: Configured

The first scheduled execution is awaiting verification.

👩‍💻 Developer

Abhirami Poornima

GitHub: "@abhiramipoornimma" (https://github.com/abhiramipoornimma)

---

The AI Brief – Making AI news easier to follow, one report at a time.
