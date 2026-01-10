# Rick Bot – GDFlix, TMDB Posters, Audio Info

[![Contact Developer on Telegram](https://img.shields.io/badge/Developer-%40RICKGRIMES-blue?logo=telegram)](https://t.me/J1_CHANG_WOOK)

- Telegram Developer: [J1_CHANG_WOOK](https://t.me/J1_CHANG_WOOK)

A modular Telegram bot that:
- Converts Google Drive links to GDFlix share links
- Fetches TMDB metadata and posters/backdrops with type and language filters
- Extracts and formats audio tracks via MediaInfo
- Provides owner-only settings and restart controls

## Features

- Google Drive → GDFlix integration
- TMDB poster/backdrop selection with:
  - Type: Landscape (backdrops) or Portrait (posters)
  - Language: No Language, English, Tamil, Telugu, Hindi, Malayalam, Kannada (+ any other TMDB languages)
  - Pagination with arrows and numeric buttons
  - Bold caption including a direct “Click Here” image link
- Manual caption reposting for poster images
- Owner-only interactive environment manager and restart

## Requirements

- Python 3.11+
- Telegram Bot API token (BotFather)
- Optional: Heroku or any host for long-running Python processes

## Environment Variables

Set via platform configuration (e.g., Heroku Config Vars) or a local `.env` file:

- TELEGRAM_BOT_TOKEN
- OWNER_ID
- TMDB_API_KEY
- WORKERS_BASE
- DEV_LINK (optional)
- GDFLIX_API_KEY (optional)
- GDFLIX_API_BASE (default: https://gdflix.dev/v2)
- GDFLIX_FILE_BASE (default: https://gdflix.dev/file)
- NETFLIX_API (optional)
- FREEIMAGE_API_KEY (optional)
- FREEIMAGE_UPLOAD_API (default: https://freeimage.host/api/1/upload)
- STATE_REMOTE_URL (optional)
- DISABLE_MEDIAINFO (0 or 1)

## Deploy (Heroku Example)

1) Stack and buildpacks:
- heroku-22
- heroku-community/apt
- heroku/python

2) Root files:
- Procfile: `worker: python bot.py`
- Aptfile: `mediainfo`
- runtime.txt: `python-3.11.9`
- requirements.txt:
  - python-telegram-bot==21.6
  - requests==2.32.3
  - beautifulsoup4==4.12.3
  - urllib3==2.2.2
  - python-dotenv==1.0.1

3) Configure environment variables and deploy.

## Local Development

1) Copy `.env.example` to `.env` and fill values.
2) Create venv and install dependencies.
3) Run `python bot.py`.

## Project Structure

- bot.py
- app/
  - main.py
  - config.py
  - state.py
  - utils.py
  - keyboards.py
  - handlers/
    - start_help.py
    - core.py
    - streaming.py  ← OTT scrap commands live here (see list below)
    - posters_ui.py
    - admin.py
    - ucer.py
    - restart.py
    - bs.py
- services/
  - gdflix.py
  - tmdb.py
  - mediainfo.py
- Procfile
- Aptfile
- runtime.txt
- requirements.txt
- .env.example

## OTT Platforms Supported (Scrape commands)

All OTT poster scrap commands are implemented in `app/handlers/streaming.py`. Each command fetches platform-specific posters/backdrops and renders a bold caption.

- /amzn — Amazon Prime Video
- /airtel — Airtel Xstream
- /zee5 — ZEE5
- /hulu — Hulu
- /viki — Viki
- /snxt — Sun NXT
- /mmax — ManoramaMax
- /aha — Aha
- /dsnp — Disney+
- /apple — Apple TV
- /bms — BookMyShow
- /iq — iQIYI
- /hbo — HBO Max
- /up — UltraPlay
- /uj — UltraJhakaas
- /wetv — WeTV
- /sl — SonyLiv
- /tk — Tentkotta
- /nf — Netflix (via configured worker/API)

Each command:
- Accepts the platform URL (or Netflix ID for /nf)
- Returns landscape and/or portrait image URLs
- Sends bold caption with clickable image link

## Troubleshooting

- If the bot doesn’t respond in groups:
  - In BotFather, set privacy OFF: `/setprivacy` → OFF
  - Ensure the bot has permissions to send/edit messages
  - Use authorization flow if your build includes it
- If MediaInfo fails:
  - Ensure `mediainfo` is present via Aptfile and apt buildpack
  - Set `DISABLE_MEDIAINFO=1` to skip audio parsing
- For persistent settings on Heroku:
  - Use Config Vars; local `.env` is not persistent across dyno restarts

## Security

- Keep secrets in platform config (e.g., Heroku Config Vars).
- Do not commit `.env` to version control.

## License

Provided as-is for customization.
