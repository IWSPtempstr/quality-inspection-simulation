from functools import lru_cache
from pathlib import Path

from ai_service.conf.settings import Settings


class PromptLoader:
    def __init__(self, settings: Settings):
        self._base_path = settings.prompt_dir

    @property
    def base_path(self) -> Path:
        return self._base_path

    @lru_cache(maxsize=32)
    def load(self, name: str) -> str:
        candidate = self.base_path / f"{name}.md"
        if not candidate.exists():
            raise FileNotFoundError(f"prompt_not_found:{name}")
        return candidate.read_text(encoding="utf-8")
