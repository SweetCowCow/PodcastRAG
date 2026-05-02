import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:password@localhost:5432/podcastrag",
)
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:8080")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-do-not-use-in-prod-thirtytwo+chars")
os.environ.setdefault("ADMIN_EMAILS", "")
