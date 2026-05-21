from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
AGENT_NAMES = [
    "orchestrator",
    "order_manager",
    "project_identifier",
    "rag_retriever",
    "queue_scheduler",
    "equipment_monitor",
    "exception_analyzer",
]


@dataclass(frozen=True)
class AgentModelConfig:
    agent_name: str
    provider: str
    api_key: str | None
    base_url: str | None
    model: str
    temperature: float
    max_tokens: int
    enable_thinking: bool

    def public_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "provider": self.provider,
            "base_url_configured": bool(self.base_url),
            "api_key_configured": bool(self.api_key),
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "enable_thinking": self.enable_thinking,
        }


@dataclass(frozen=True)
class Settings:
    app_name: str = "电器产品质量检测多Agent仿真系统"
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'simulation.db'}")
    knowledge_base_dir: Path = BASE_DIR / "rag" / "knowledge_base"
    rag_index_dir: Path = BASE_DIR / "rag" / "index"
    operations_constraints_path: Path = BASE_DIR / "data" / "scenario_synthetic_center" / "operations_constraints.json"
    llm_provider: str = "openai-compatible"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str = "gpt-4o-mini"
    embedding_provider: str = "openai-compatible"
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None
    embedding_model: str = "text-embedding-3-small"
    mcp_server_command: str = sys.executable
    mcp_server_args: list[str] | None = None
    mcp_server_cwd: Path = BASE_DIR
    mcp_adapter_type: str = "simulation"
    agent_configs: dict[str, AgentModelConfig] = field(default_factory=dict)


def load_environment() -> None:
    env_file = Path(os.getenv("ENV_FILE", str(BASE_DIR / ".env")))
    if env_file.exists():
        load_dotenv(env_file, override=False)


def get_settings() -> Settings:
    load_environment()
    default_mcp_args = ["-m", "mcp_server.simulation_server"]
    raw_args = os.getenv("MCP_SERVER_ARGS")
    llm_provider = _env_text("LLM_PROVIDER", _env_text("MODEL_PROVIDER", "openai-compatible"))
    llm_api_key = os.getenv("LLM_API_KEY") or None
    llm_base_url = os.getenv("LLM_BASE_URL") or None
    llm_model = _env_text("LLM_MODEL", "gpt-4o-mini")
    llm_temperature = _env_float("LLM_TEMPERATURE", 0.0)
    llm_max_tokens = _env_int("LLM_MAX_TOKENS", 512)
    llm_enable_thinking = _env_bool("LLM_ENABLE_THINKING", False)
    return Settings(
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'simulation.db'}"),
        knowledge_base_dir=Path(os.getenv("KNOWLEDGE_BASE_DIR", str(BASE_DIR / "rag" / "knowledge_base"))),
        rag_index_dir=Path(os.getenv("RAG_INDEX_DIR", str(BASE_DIR / "rag" / "index"))),
        operations_constraints_path=Path(
            os.getenv(
                "OPERATIONS_CONSTRAINTS_PATH",
                str(BASE_DIR / "data" / "scenario_synthetic_center" / "operations_constraints.json"),
            )
        ),
        llm_provider=llm_provider,
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "openai-compatible"),
        embedding_api_key=os.getenv("EMBEDDING_API_KEY") or None,
        embedding_base_url=os.getenv("EMBEDDING_BASE_URL") or None,
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        mcp_server_command=os.getenv("MCP_SERVER_COMMAND", sys.executable),
        mcp_server_args=raw_args.split() if raw_args else default_mcp_args,
        mcp_server_cwd=Path(os.getenv("MCP_SERVER_CWD", str(BASE_DIR))),
        mcp_adapter_type=os.getenv("MCP_ADAPTER_TYPE", "simulation"),
        agent_configs=_load_agent_configs(
            provider=llm_provider,
            api_key=llm_api_key,
            base_url=llm_base_url,
            model=llm_model,
            temperature=llm_temperature,
            max_tokens=llm_max_tokens,
            enable_thinking=llm_enable_thinking,
        ),
    )


def _load_agent_configs(
    provider: str,
    api_key: str | None,
    base_url: str | None,
    model: str,
    temperature: float,
    max_tokens: int,
    enable_thinking: bool,
) -> dict[str, AgentModelConfig]:
    return {
        agent_name: _load_single_agent_config(
            agent_name=agent_name,
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            enable_thinking=enable_thinking,
        )
        for agent_name in AGENT_NAMES
    }


def _load_single_agent_config(
    agent_name: str,
    provider: str,
    api_key: str | None,
    base_url: str | None,
    model: str,
    temperature: float,
    max_tokens: int,
    enable_thinking: bool,
) -> AgentModelConfig:
    prefix = f"AGENT_{agent_name.upper()}"
    return AgentModelConfig(
        agent_name=agent_name,
        provider=_env_text(f"{prefix}_PROVIDER", provider),
        api_key=os.getenv(f"{prefix}_API_KEY") or api_key,
        base_url=os.getenv(f"{prefix}_BASE_URL") or base_url,
        model=_env_text(f"{prefix}_MODEL", model),
        temperature=_env_float(f"{prefix}_TEMPERATURE", temperature),
        max_tokens=_env_int(f"{prefix}_MAX_TOKENS", max_tokens),
        enable_thinking=_env_bool(f"{prefix}_ENABLE_THINKING", enable_thinking),
    )


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value == "":
        return default
    return int(raw_value)


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value == "":
        return default
    return float(raw_value)


def _env_text(name: str, default: str) -> str:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value == "":
        return default
    return raw_value


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value == "":
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}
