from pathlib import Path

import pytest

from ai_service.conf.settings import Settings
from ai_service.prompt.loader import PromptLoader


def test_load_prompt(tmp_path: Path) -> None:
    (tmp_path / "sample.md").write_text("hello", encoding="utf-8")
    loader = PromptLoader(Settings(prompt_directory=tmp_path))
    assert loader.load("sample") == "hello"


def test_missing_prompt_raises(tmp_path: Path) -> None:
    loader = PromptLoader(Settings(prompt_directory=tmp_path))
    with pytest.raises(FileNotFoundError):
        loader.load("missing")
