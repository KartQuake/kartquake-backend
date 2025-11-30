from typing import Any, Dict, Optional

import httpx

from app.core.config import settings

class AIClient:
    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base_url = base_url or settings.AI_SERVICE_URL or "http://127.0.0.1:8001"

    def parse_intents(self, user_id: Optional[str], message: str) -> Dict[str, Any]:
        """
        Call the AI service /parse-intents endpoint and return the JSON response.
        """
        url = f"{self.base_url}/parse-intents"
        payload = {"user_id": user_id, "message": message}

        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
