from app.main import main

if __name__ == "__main__":
    # Load .env for local development; Heroku uses Config Vars instead.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    main()
