# Rick Bot (Modular, Heroku-ready)

Modular Telegram bot:
- Core: GDrive → GDFlix + TMDB + MediaInfo + Manual Poster
- OTT Poster Scrapers: /amzn /airtel /zee5 /hulu /viki /mmax /snxt /aha /dsnp /apple /bms /iq /hbo /up /uj /wetv /sl /tk /nf
- UCER settings, Admin panel, State persistence (local JSON + optional remote)

## Deploy (Heroku Buildpack)
1) Set stack, add buildpacks:
```
heroku stack:set heroku-22 -a <app>
heroku buildpacks:add -a <app> heroku-community/apt
heroku buildpacks:add -a <app> heroku/python
```

2) Config Vars:
```
heroku config:set -a <app> TELEGRAM_BOT_TOKEN=xxx TMDB_API_KEY=xxx WORKERS_BASE=https://your.workers.dev ...
```

3) Push & Scale:
```
git push heroku main
heroku ps:scale worker=1 -a <app>
heroku logs -t -a <app>
```

## Files
- Procfile (worker: python bot.py)
- Aptfile (mediainfo)
- runtime.txt (python-3.11.9)
- requirements.txt
- bot.py (entrypoint)
- app/ (all modules)