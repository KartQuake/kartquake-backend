import os
from dotenv import load_dotenv

# Load environment variables from .env file (only in local dev)
load_dotenv()

class Settings:
    def __init__(self) -> None:
        self.OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
        self.GOOGLE_MAPS_API_KEY: str | None = os.getenv("GOOGLE_MAPS_API_KEY")
        self.DATABASE_URL: str | None = os.getenv("DATABASE_URL")
        self.REDIS_URL: str | None = os.getenv("REDIS_URL")

        # Stripe
        self.STRIPE_SECRET_KEY: str | None = os.getenv("STRIPE_SECRET_KEY")
        self.STRIPE_WEBHOOK_SECRET: str | None = os.getenv("STRIPE_WEBHOOK_SECRET")
        self.STRIPE_PRICE_PREMIUM: str | None = os.getenv("STRIPE_PRICE_PREMIUM")
        self.STRIPE_PRICE_COSTCO_ADDON: str | None = os.getenv("STRIPE_PRICE_COSTCO_ADDON")

        # Frontend
        self.FRONTEND_BASE_URL: str = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")

        # Analytics / AI service
        self.POSTHOG_API_KEY: str | None = os.getenv("POSTHOG_API_KEY")
        self.POSTHOG_HOST: str | None = os.getenv("POSTHOG_HOST")
        self.AI_SERVICE_URL: str | None = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:8001")

settings = Settings()
