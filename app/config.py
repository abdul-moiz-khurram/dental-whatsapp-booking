import os
from dotenv import load_dotenv
load_dotenv()
print("DATABASE:", os.environ.get("DATABASE_URL"))



class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    _db_url = os.environ.get("DATABASE_URL")
    if _db_url and _db_url.startswith("postgres://"):
        # SQLAlchemy 1.4+/2.x requires the "postgresql://" scheme.
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)

    SQLALCHEMY_DATABASE_URI = _db_url or "sqlite:///" + os.path.join(
        os.path.abspath(os.path.dirname(os.path.dirname(__file__))), "instance", "recall.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Fallback WhatsApp settings, used only if a clinic hasn't configured its
    # own credentials yet from the dashboard (Clinic settings > WhatsApp
    # integration). Per-clinic credentials always take priority - see
    # app/chatbot/providers/__init__.py.
    WHATSAPP_PROVIDER = os.environ.get("WHATSAPP_PROVIDER", "twilio")

    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
    TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM")

    META_PHONE_NUMBER_ID = os.environ.get("META_PHONE_NUMBER_ID")
    META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN")
    META_VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "verify-token")

    # --- Email (password resets, staff invites, new-booking alerts) ---
    # If MAIL_SERVER isn't set, the app logs emails instead of sending them,
    # so the product works in development/demo without real SMTP creds.
    MAIL_SERVER = os.environ.get("MAIL_SERVER")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "no-reply@recall.local")

    # --- Encryption key for per-clinic WhatsApp credentials at rest ---
    # Must be a stable Fernet key in production (generate once, keep secret,
    # never rotate without a migration plan). Falls back to a key derived
    # from SECRET_KEY so local/demo installs still work out of the box.
    CREDENTIALS_ENCRYPTION_KEY = os.environ.get("CREDENTIALS_ENCRYPTION_KEY")

    # --- Rate limiting storage (defaults to in-memory; fine for a single
    # server, use Redis in a multi-process production deployment) ---
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

    # --- Reminder/recall background scheduler ---
    # Runs in-process via APScheduler. If you run more than one gunicorn
    # worker, set this to "false" on all but one worker, or every worker
    # will send its own copy of each reminder/recall message.
    SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "true").lower() == "true"
