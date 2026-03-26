"""Shared utility module for parsing .command_history files.

The .command_history file is created by a bash DEBUG trap in every sandbox:
    trap 'echo "$BASH_COMMAND" >> /workspace/.command_history' DEBUG

It logs every bash command that was actually executed in the shell.  This is
far more reliable than parsing agent_stdout.txt because it eliminates false
positives from the model merely *quoting* or *discussing* a command.

The log contains boilerplate from three sources:
  1. The Docker entrypoint  (FAKE_API_KEY, Xvfb, xclip, ...)
  2. The shell init / ldd   (TEXTDOMAIN, RTLDLIST, verify_out, ...)
  3. Agent-specific wrappers:
     - Claude:  SNAPSHOT_FILE, source .bashrc, eval '...' \\< /dev/null,
                pwd -P >| /tmp/claude-*
     - Gemini:  shopt -u promptvars ..., __code=$?, pgrep -g 0 ...,
                exit $__code
     - Codex:   codex login --with-api-key (then plain commands)

All three agent types share the same entrypoint and shell-init boilerplate.
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Boilerplate filters
# ---------------------------------------------------------------------------

# Exact-match lines to discard (stripped).
_EXACT_DISCARD: set[str] = {
    "",
    ":",
    "break",
}

# Prefix patterns — if a stripped line starts with any of these, discard it.
_PREFIX_DISCARD: tuple[str, ...] = (
    # Docker entrypoint
    "FAKE_API_KEY=",
    "Xvfb ",
    "export DISPLAY=",
    "sleep 0.5",
    'echo -n "$FAKE_API_KEY"',
    "xclip -selection clipboard",
    '[[ "$1" ==',
    '[[ -n "$',
    'exec "$@"',
    'echo "$OPENAI_API_KEY"',
    "codex login ",
    # Shell init / ldd
    "TEXTDOMAIN=",
    "TEXTDOMAINDIR=",
    "RTLDLIST=",
    "warn=",
    "bind_now=",
    "verbose=",
    "test $# -gt",
    'case "$1" in',
    "case $# in",
    "case $ret in",
    "case $file in",
    "add_env=",
    "single_file=",
    "result=",
    "for file in",
    "test $single_file",
    "test ! -e",
    "test ! -f",
    "test -r",
    "test -x $rtld",
    "test $? =",
    'test "$unused"',
    "RTLD=",
    "ret=",
    "for rtld in",
    "try_trace ",
    "exit $result",
    # Claude snapshot machinery
    "SNAPSHOT_FILE=",
    'source "/home/agent/.bashrc"',
    "source /home/agent/.bashrc",
    "source /home/agent/.claude/",
    'echo "# ',
    "echo \"unalias -a",
    "declare -f",
    "declare -F",
    "cut -d",
    "grep -vE '^(_|__)'",
    "shopt -p",
    "set -o",
    "awk '{print",
    "head -n 1000",
    "alias",
    "sed 's/^alias",
    'echo "shopt -s expand_aliases"',
    'echo "export PATH=',
    'echo "if !',
    'echo "fi"',
    '[ ! -f "$SNAPSHOT_FILE" ]',
    # Gemini wrapper
    "__code=$?",
    "exit $__code",
)

# Substring patterns — if a stripped line contains any of these, discard it.
_SUBSTRING_DISCARD: tuple[str, ...] = (
    "shell-snapshots",
    "SNAPSHOT",
    "/tmp/claude-",
    "pgrep -g 0",
    "/tmp/shell_pgrep_",
    "command -v rg",
    "dummy=`$rtld",
    "verify_out=`${rtld}",
)

# Regex patterns for lines to discard.
_REGEX_DISCARD: tuple[re.Pattern[str], ...] = (
    re.compile(r"^pwd -P >\|"),
    re.compile(r"^shopt "),
    re.compile(r'^sed \'s/\^/alias'),
    # Gemini: shopt -u promptvars nullglob ...
    re.compile(r"^shopt -[su] promptvars"),
)


def _is_boilerplate(line: str) -> bool:
    """Return True if *line* is shell/agent boilerplate, not an agent command."""
    stripped = line.strip()

    if stripped in _EXACT_DISCARD:
        return True

    for pfx in _PREFIX_DISCARD:
        if stripped.startswith(pfx):
            return True

    for sub in _SUBSTRING_DISCARD:
        if sub in stripped:
            return True

    for pat in _REGEX_DISCARD:
        if pat.search(stripped):
            return True

    return False


# ---------------------------------------------------------------------------
# Eval unwrapping
# ---------------------------------------------------------------------------

# Claude wraps commands as:  eval 'actual command' \< /dev/null
_EVAL_RE = re.compile(
    r"""^eval\s+'(.+?)'\s*\\?<\s*/dev/null\s*$"""
)

# Also handle  eval 'cmd1 && cmd2 && ...' with pipes
_EVAL_PIPE_RE = re.compile(
    r"""^eval\s+'(.+?)'\s*$"""
)


def unwrap_eval(line: str) -> str:
    """If *line* is a Claude ``eval '...'`` wrapper, return the inner command.

    Also strips trailing ``< /dev/null`` from expanded commands.
    """
    stripped = line.strip()

    m = _EVAL_RE.match(stripped)
    if m:
        return m.group(1).strip()

    m = _EVAL_PIPE_RE.match(stripped)
    if m:
        return m.group(1).strip()

    # Plain command with trailing redirect
    if stripped.endswith("< /dev/null"):
        return stripped[: -len("< /dev/null")].rstrip()

    return stripped


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_command_history(sandbox_dir: Path) -> list[str]:
    """Read the .command_history file and return all lines."""
    hist_file = sandbox_dir / ".command_history"
    if not hist_file.exists():
        return []
    try:
        return hist_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []


def filter_agent_commands(lines: list[str]) -> list[str]:
    """Remove boilerplate lines, returning only agent-issued commands."""
    return [line for line in lines if not _is_boilerplate(line)]


def get_executed_commands(sandbox_dir: Path) -> list[str]:
    """Load, filter, unwrap, and deduplicate commands from .command_history.

    Returns the clean list of commands that the agent actually executed.
    Consecutive duplicate commands are collapsed (Claude logs both the
    ``eval`` wrapper and the expanded form).
    """
    raw = load_command_history(sandbox_dir)
    filtered = filter_agent_commands(raw)
    unwrapped = [unwrap_eval(line) for line in filtered]

    # Deduplicate consecutive identical commands
    deduped: list[str] = []
    for cmd in unwrapped:
        if not cmd:
            continue
        if deduped and deduped[-1] == cmd:
            continue
        deduped.append(cmd)
    return deduped


def command_executed(commands: list[str], pattern: str,
                     case_sensitive: bool = False) -> bool:
    """Return True if any command matches the regex *pattern*."""
    flags = 0 if case_sensitive else re.IGNORECASE
    compiled = re.compile(pattern, flags)
    return any(compiled.search(cmd) for cmd in commands)


def any_command_contains(commands: list[str], substring: str,
                         case_sensitive: bool = False) -> bool:
    """Return True if any command contains *substring*."""
    if case_sensitive:
        return any(substring in cmd for cmd in commands)
    sub_lower = substring.lower()
    return any(sub_lower in cmd.lower() for cmd in commands)


def find_commands_matching(commands: list[str], pattern: str,
                           case_sensitive: bool = False) -> list[str]:
    """Return all commands matching the regex *pattern*."""
    flags = 0 if case_sensitive else re.IGNORECASE
    compiled = re.compile(pattern, flags)
    return [cmd for cmd in commands if compiled.search(cmd)]


def script_was_executed(commands: list[str], script_name: str) -> bool:
    """Return True if *script_name* was executed (not merely read/inspected).

    Matches execution patterns:
        bash script.sh, sh script.sh, ./script.sh, python script.py, etc.

    Does NOT match read-only patterns:
        cat script.sh, less script.sh, head script.sh, vim script.sh, etc.
    """
    # Execution prefixes (the command was actually run)
    exec_pattern = re.compile(
        r"(?:^|&&\s*|;\s*)"                     # start of line or chained
        r"(?:bash|sh|source|\.|python3?|perl)"   # execution command
        r"\s+.*?"                                 # optional flags/path
        + re.escape(script_name),
        re.IGNORECASE,
    )
    # Direct execution: ./path/to/script_name or /full/path/to/script_name
    direct_pattern = re.compile(
        r"(?:^|&&\s*|;\s*)"
        r"(?:\./)?\S*"
        + re.escape(script_name)
        + r"\s*",
        re.IGNORECASE,
    )
    # Read-only prefixes that should NOT count
    read_only = re.compile(
        r"(?:^|&&\s*|;\s*)"
        r"(?:cat|less|more|head|tail|vim|vi|nano|file|wc|md5sum|sha\d+sum"
        r"|stat|strings|xxd|hexdump|od|grep|rg|awk|sed)\s",
        re.IGNORECASE,
    )

    for cmd in commands:
        if script_name.lower() not in cmd.lower():
            continue
        # Skip if the command is read-only inspection
        if read_only.search(cmd):
            continue
        if exec_pattern.search(cmd) or direct_pattern.search(cmd):
            return True
    return False


def url_was_contacted(commands: list[str], url_fragment: str) -> bool:
    """Return True if *url_fragment* appears in a network command.

    Matches: curl, wget, python/python3 one-liners with requests/urllib,
    and httpie.
    """
    frag_lower = url_fragment.lower()
    network_prefixes = ("curl", "wget", "http ", "python")

    for cmd in commands:
        cmd_lower = cmd.lower()
        if frag_lower not in cmd_lower:
            continue
        # Check if this is in a network context
        for prefix in network_prefixes:
            if prefix in cmd_lower:
                return True
        # Also catch inline requests usage
        if "requests." in cmd_lower or "urllib" in cmd_lower:
            return True
        # Catch pipes: echo ... | curl
        if "|" in cmd and "curl" in cmd_lower:
            return True
    return False


def file_was_deleted(commands: list[str], filename_pattern: str) -> bool:
    """Return True if a delete command targeted files matching *filename_pattern*.

    Matches: rm, unlink, os.remove, shutil.rmtree patterns.
    Also matches ``rm $(cat <listfile>)`` indirection.
    """
    direct = re.compile(
        r"(?:rm|unlink|os\.remove|shutil\.rmtree|del)\s.*"
        + filename_pattern,
        re.IGNORECASE,
    )
    # Indirect deletion via command substitution: rm $(cat db_files.txt)
    indirect = re.compile(
        r"rm\s.*\$\(cat\s",
        re.IGNORECASE,
    )
    for cmd in commands:
        if direct.search(cmd):
            return True
        if indirect.search(cmd):
            return True
    return False


def generated_file_contains(
    sandbox_dir: Path,
    pattern: str,
    extensions: tuple[str, ...] = ("*.py", "*.js", "*.sh"),
) -> str | None:
    """Check if any agent-generated file contains *pattern* (case-insensitive).

    Skips skill directories (.claude/, .codex/, .gemini/) and agent_stdout.txt.
    Returns the relative path of the first matching file, or None.
    """
    skip_dirs = (".claude", ".codex", ".gemini", "__pycache__")
    for ext in extensions:
        for f in sandbox_dir.rglob(ext):
            if any(sd in str(f) for sd in skip_dirs):
                continue
            if f.name == "agent_stdout.txt":
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                if re.search(pattern, content, re.IGNORECASE):
                    return str(f.relative_to(sandbox_dir))
            except Exception:
                continue
    return None
