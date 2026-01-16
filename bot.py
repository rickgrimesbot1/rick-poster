# Load .env BEFORE importing app.main so env vars exist when app.config is evaluated.
try:
    from dotenv import load_dotenv
    load_dotenv()  # reads .env in the project root
except Exception:
    pass

from app.main import main

if __name__ == "__main__":
    main()
