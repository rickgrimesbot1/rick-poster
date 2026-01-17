import logging
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)

from app.config import TELEGRAM_BOT_TOKEN
from app.handlers import start_help, core, streaming, ucer, admin, posters_ui, restart, bs, repost
from app.handlers import top_poster  # NEW
from app.state import load_state


def setup_logging():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )


def main():
    setup_logging()
    load_state()

    if not TELEGRAM_BOT_TOKEN:
        print("Set TELEGRAM_BOT_TOKEN env first!")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Basic
    app.add_handler(CommandHandler("start", start_help.start, block=False))
    app.add_handler(CommandHandler("help", start_help.help_cmd, block=False))
    app.add_handler(CommandHandler("authorize", core.authorize, block=False))

    # Access control
    app.add_handler(CommandHandler("allow", core.allow_user, block=False))
    app.add_handler(CommandHandler("deny", core.deny_user, block=False))

    # Core media commands
    app.add_handler(CommandHandler("get", core.get_cmd, block=False))
    app.add_handler(CommandHandler("info", core.info_cmd, block=False))
    app.add_handler(CommandHandler("ls", core.ls_cmd, block=False))
    app.add_handler(CommandHandler("tmdb", core.tmdb_cmd, block=False))
    app.add_handler(MessageHandler(filters.PHOTO, core.manual_poster))

    # UCER settings
    app.add_handler(CommandHandler("ucer", ucer.ucer_cmd, block=False))
    app.add_handler(CallbackQueryHandler(ucer.ucer_cb, pattern="^ucer:", block=False))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ucer.ucer_text))

    # Admin panel
    app.add_handler(CommandHandler("admin", admin.admin_cmd, block=False))
    app.add_handler(CallbackQueryHandler(admin.admin_cb, pattern="^admin:", block=False))

    # Streaming posters
    app.add_handler(CommandHandler("amzn", streaming.amzn, block=False))
    app.add_handler(CommandHandler("airtel", streaming.airtel, block=False))
    app.add_handler(CommandHandler("zee5", streaming.zee5, block=False))
    app.add_handler(CommandHandler("hulu", streaming.hulu, block=False))
    app.add_handler(CommandHandler("viki", streaming.viki, block=False))
    app.add_handler(CommandHandler("snxt", streaming.snxt, block=False))
    app.add_handler(CommandHandler("mmax", streaming.mmax, block=False))
    app.add_handler(CommandHandler("aha", streaming.aha, block=False))
    app.add_handler(CommandHandler("dsnp", streaming.dsnp, block=False))
    app.add_handler(CommandHandler("apple", streaming.apple, block=False))
    app.add_handler(CommandHandler("bms", streaming.bms, block=False))
    app.add_handler(CommandHandler("nf", streaming.nf, block=False))
    app.add_handler(CommandHandler("iq", streaming.iq, block=False))
    app.add_handler(CommandHandler("hbo", streaming.hbo, block=False))
    app.add_handler(CommandHandler("up", streaming.up, block=False))
    app.add_handler(CommandHandler("uj", streaming.uj, block=False))
    app.add_handler(CommandHandler("wetv", streaming.wetv, block=False))
    app.add_handler(CommandHandler("sl", streaming.sl, block=False))
    app.add_handler(CommandHandler("tk", streaming.tk, block=False))

    # Posters UI (type + language selection)
    app.add_handler(CommandHandler("posters", posters_ui.posters_command, block=False))
    app.add_handler(CallbackQueryHandler(posters_ui.posters_cb, pattern="^poster:", block=False))

    # Bot settings (/bs)
    app.add_handler(CommandHandler("bs", bs.bs_cmd, block=False))
    app.add_handler(CallbackQueryHandler(bs.bs_cb, pattern="^bs:", block=False))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bs.bs_text))

    # /rk — caption with quoted Audio block
    app.add_handler(CommandHandler("rk", repost.rk, block=False))

    # NEW: /tp — top caption + TMDB poster from GDFlix/Drive link
    app.add_handler(CommandHandler("tp", top_poster.tp, block=False))

    # Restart (owner) and whoami
    app.add_handler(CommandHandler("whoami", restart.whoami, block=False))
    app.add_handler(CommandHandler("restart", restart.restart_cmd, block=False))
    app.add_handler(CallbackQueryHandler(restart.restart_cb, pattern="^restart:", block=False))

    print("Bot running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
