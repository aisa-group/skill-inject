#!/usr/bin/env bash
set -euo pipefail

log_file="startup.log"
timestamp="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
agent_name="${AGENT_CMD:-unknown}"

copy_tree() {
  local src="$1"
  local dest="$2"
  if command -v rsync >/dev/null 2>&1; then
    mkdir -p "$dest"
    rsync -a --delete "$src/" "$dest/"
  else
    rm -rf "$dest"
    mkdir -p "$dest"
    cp -a "$src/." "$dest/"
  fi
}

{
  echo "[$timestamp] Startup script running for agent: $agent_name"

  claude_skills=".claude/skills"
  codex_skills=".codex/skills"
  gemini_skills=".gemini/skills"

  # Find the source skills directory (any of the three that exists)
  source_skills=""
  if [[ -d "$claude_skills" ]]; then
    source_skills="$claude_skills"
  elif [[ -d "$codex_skills" ]]; then
    source_skills="$codex_skills"
  elif [[ -d "$gemini_skills" ]]; then
    source_skills="$gemini_skills"
  fi

  # Only copy skills to the current agent's folder
  if [[ -n "$source_skills" ]]; then
    case "$agent_name" in
      claude)
        if [[ "$source_skills" != "$claude_skills" ]]; then
          mkdir -p "$(dirname "$claude_skills")"
          copy_tree "$source_skills" "$claude_skills"
          echo "Copied skills from $source_skills to $claude_skills"
        else
          echo "Skills already in $claude_skills"
        fi
        ;;
      codex)
        if [[ "$source_skills" != "$codex_skills" ]]; then
          mkdir -p "$(dirname "$codex_skills")"
          copy_tree "$source_skills" "$codex_skills"
          echo "Copied skills from $source_skills to $codex_skills"
        else
          echo "Skills already in $codex_skills"
        fi
        ;;
      gemini)
        if [[ "$source_skills" != "$gemini_skills" ]]; then
          mkdir -p "$(dirname "$gemini_skills")"
          copy_tree "$source_skills" "$gemini_skills"
          echo "Copied skills from $source_skills to $gemini_skills"
        else
          echo "Skills already in $gemini_skills"
        fi
        ;;
      *)
        echo "Unknown agent: $agent_name - skipping skill setup"
        ;;
    esac
  else
    echo "No skills directory found"
  fi
} >> "$log_file" 2>&1
