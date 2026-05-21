from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    app_name: str = "电器产品质量检测多Agent仿真系统"
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'simulation.db'}")
    knowledge_base_dir: Path = BASE_DIR / "rag" / "knowledge_base"
    rag_index_dir: Path = BASE_DIR / "rag" / "index"
    embedding_provider: str = "openai-compatible"
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None
    embedding_model: str = "text-embedding-3-small"
    mcp_server_command: str = sys.executable
    mcp_server_args: list[str] | None = None
    mcp_server_cwd: Path = BASE_DIR


def get_settings() -> Settings:
    default_mcp_args = ["-m", "mcp_server.simulation_server"]
    raw_args = os.getenv("MCP_SERVER_ARGS")
    return Settings(
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'simulation.db'}"),
        knowledge_base_dir=Path(os.getenv("KNOWLEDGE_BASE_DIR", str(BASE_DIR / "rag" / "knowledge_base"))),
        rag_index_dir=Path(os.getenv("RAG_INDEX_DIR", str(BASE_DIR / "rag" / "index"))),
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "openai-compatible"),
        embedding_api_key=os.getenv("EMBEDDING_API_KEY") or None,
        embedding_base_url=os.getenv("EMBEDDING_BASE_URL") or None,
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        mcp_server_command=os.getenv("MCP_SERVER_COMMAND", sys.executable),
        mcp_server_args=raw_args.split() if raw_args else default_mcp_args,
        mcp_server_cwd=Path(os.getenv("MCP_SERVER_CWD", str(BASE_DIR))),
    )
