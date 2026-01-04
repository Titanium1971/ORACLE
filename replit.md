# Velvet Oracle

A Telegram WebApp-based quiz/ritual experience with Flask backend.

## Overview

This is a "Velvet Oracle" ritual application that:
- Serves a static webapp (HTML/CSS/JS) for users to take a quiz/ritual
- Provides a Flask API backend for questions (from Airtable) and ritual tracking
- Integrates with Telegram as a WebApp
- Stores results in Notion/Airtable

## Project Structure

```
/
├── server.py          # Flask API server (also serves static webapp)
├── bot.py             # Telegram bot (for production deployment)
├── requirements.txt   # Python dependencies
├── webapp/            # Static frontend
│   ├── index.html     # Main HTML
│   ├── app.js         # Frontend JavaScript
│   ├── style.css      # Styles
│   ├── velvet-logo.svg
│   ├── tick-soft.mp3  # Audio asset
│   └── Morena*.otf    # Custom fonts
└── vercel.json        # (Legacy Vercel config)
```

## Running Locally

The Flask server runs on port 5000 and serves:
- Static webapp files at `/`
- API endpoints at `/api`, `/health`, `/version`, `/questions/random`, etc.

## API Endpoints

- `GET /` - Serves the webapp
- `GET /api` - API status
- `GET /health` - Health check with Airtable ping
- `GET /version` - Version info
- `GET /questions/random?count=N` - Get random questions from Airtable
- `POST /ritual/start` - Start a ritual session
- `POST /ritual/complete` - Complete a ritual and log results

## Environment Variables

The following environment variables are needed for full functionality:
- `AIRTABLE_API_KEY` - Airtable API key
- `AIRTABLE_BASE_ID` - Airtable base ID for questions
- `AIRTABLE_TABLE_ID` - Airtable table ID for questions
- `AIRTABLE_CORE_BASE_ID` - (Optional) Airtable base for players/attempts
- `AIRTABLE_PLAYERS_TABLE` - Players table name
- `AIRTABLE_ATTEMPTS_TABLE` - Attempts table name
- `TELEGRAM_BOT_TOKEN` - For Telegram bot functionality (bot.py)
- `NOTION_API_KEY` - For Notion integration
- `NOTION_EXAMS_DB_ID` - Notion database ID

## Recent Changes

- 2026-01-04: Configured for Replit environment
  - Updated Flask to serve static files from webapp folder
  - Modified app.js to use current host as API URL
  - Set up workflow on port 5000
