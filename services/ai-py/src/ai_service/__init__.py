"""AI assistance service skeleton."""

from ai_service.api.app import create_app
from ai_service.conf.settings import AIServiceSettings

__all__ = ["AIServiceSettings", "create_app"]
