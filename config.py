"""Shared configuration for the SKILL-INJECT benchmark."""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

DATA_DIR = PROJECT_ROOT / "data"
SKILL_ROOT = DATA_DIR / "skills"
FINAL_RESULTS_DIR = PROJECT_ROOT / "final_results"
DOCKER_DIR = PROJECT_ROOT / "docker"
STARTUP_SCRIPTS_DIR = PROJECT_ROOT / "startup_scripts"

CONTEXTUAL_INJECTIONS_FILE = DATA_DIR / "contextual_injections.json"
OBVIOUS_INJECTIONS_FILE = DATA_DIR / "obvious_injections.json"
CONTEXTUAL_WSCRIPT_FILE = DATA_DIR / "contextual_injections_wscript.json"
OBVIOUS_DIRECT_FILE = DATA_DIR / "obvious_injections_direct.json"

DOCKER_IMAGE_NAME = "instruct-bench-agent"

APPTAINER_DIR = PROJECT_ROOT / "apptainer"
APPTAINER_IMAGE_NAME = "instruct-bench-agent.sif"

AGENT_MODELS: dict[str, list[dict[str, str]]] = {
    "codex": [
        {"model": "gpt-5.2-codex", "display_name": "Codex (5.2-codex)"},
        {"model": "gpt-5.1-codex-max", "display_name": "Codex (5.1-max)"},
        {"model": "gpt-5.1-codex-mini", "display_name": "Codex (5.1-mini)"},
        {"model": "gpt-5.2", "display_name": "Codex (5.2)"},
        {"model": "gpt-5.1", "display_name": "Codex (5.1)"},
        {"model": "gpt-4.1", "display_name": "GPT (4.1)"},
        {"model": "gpt-5-nano", "display_name": "Codex (5-nano)"},
        {"model": "gpt-5-codex", "display_name": "Codex (5-codex)"},
        {"model": "gpt-5-mini", "display_name": "Codex (5-mini)"},
    ],
    "claude": [
        {"model": "sonnet", "display_name": "Claude Code (Sonnet)"},
        {"model": "claude-opus-4-5-20251101", "display_name": "Claude Code (Opus)"},
        {"model": "haiku", "display_name": "Claude Code (Haiku)"},
    ],
    "gemini": [
        {"model": "gemini-2.5-pro", "display_name": "Gemini CLI (2.5 Pro)"},
        {"model": "gemini-2.5-flash", "display_name": "Gemini CLI (2.5 Flash)"},
        {"model": "gemini-3-pro-preview", "display_name": "Gemini CLI (3 Pro)"},
        {"model": "gemini-3-flash-preview", "display_name": "Gemini CLI (3 Flash)"},
    ],
    "vibe": [
        {"model": "devstral-small", "display_name": "Vibe (DevStral Small)"},
        {"model": "devstral-2", "display_name": "Vibe (DevStral 2)"},
    ],
}

SKILL_MAPPING: dict[str, str] = {
    "pptx": "document-skills/pptx",
    "docx": "document-skills/docx",
    "xlsx": "document-skills/xlsx",
    "pdf": "document-skills/pdf",
    "internal_comms": "internal-comms",
    "internal_communication": "internal-comms",
    "git": "git",
    "code": "skill-creator",
    "calendar": "calendar",
    "email": "email-api",
    "email-api": "email-api",
    "mcp": "mcp",
    "fhir": "healthcare/fhir-developer-skill",
    "fhir-developer-skill": "healthcare/fhir-developer-skill",
    "slack": "slack-gif-creator",
    "webapp": "webapp-testing",
    "python-code": "python-code",
}


AGENT_PARALLEL: dict[str, int] = {
    "codex": 17,
    "claude": 15,
    "gemini": 5,
    "vibe": 10,
}

POLICY_CONFIGS: dict[str, dict] = {
    "normal": {
        "safety_protocol": 0,
        "suffix": None,
        "display": "Standard (no safety protocol)",
    },
    "legitimizing": {
        "safety_protocol": 2,
        "suffix": "legitimizing",
        "display": "Legitimizing safety protocol",
    },
    "warning": {
        "safety_protocol": 2,
        "suffix": "warning",
        "display": "Warning safety protocol",
    },
}

MODEL_CLI_MAP: dict[str, tuple[str, str]] = {
    "sonnet": ("claude", "sonnet"),
    "claude-opus-4-5-20251101": ("claude", "claude-opus-4-5-20251101"),
    "haiku": ("claude", "haiku"),
    "gemini-2.5-pro": ("gemini", "gemini-2.5-pro"),
    "gemini-2.5-flash": ("gemini", "gemini-2.5-flash"),
    "gemini-3-flash": ("gemini", "gemini-3-flash-lite"),
    "gemini-3-pro": ("gemini", "gemini-3-pro-preview"),
    "gpt-5.2-codex": ("codex", "gpt-5.2-codex"),
    "gpt-5.1-codex-max": ("codex", "gpt-5.1-codex-max"),
    "gpt-5.1-codex-mini": ("codex", "gpt-5.1-codex-mini"),
    "gpt-5.2": ("codex", "gpt-5.2"),
    "gpt-4": ("codex", "gpt-4"),
    "gpt-5-nano": ("codex", "gpt-5-nano"),
    "gpt-5-codex": ("codex", "gpt-5-codex"),
    "gpt-5-mini": ("codex", "gpt-5-mini"),
}


def get_skill_path(skill_type: str) -> str:
    """Map skill type to its subdirectory under SKILL_ROOT."""
    return SKILL_MAPPING.get(skill_type, skill_type)


def resolve_models(agent: str, model_filter: str | None = None) -> list[dict[str, str]]:
    """Get model list for an agent, optionally filtered to one model."""
    models = AGENT_MODELS[agent]
    if model_filter:
        models = [m for m in models if m["model"] == model_filter]
        if not models:
            available = [m["model"] for m in AGENT_MODELS[agent]]
            raise ValueError(
                f"Model '{model_filter}' not found for agent '{agent}'. "
                f"Available: {available}"
            )
    return models
