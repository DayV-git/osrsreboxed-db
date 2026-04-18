#!/bin/bash
# Shared helpers for scripts/update/*.sh
# Git Bash on Windows typically has `python` but not `python3`, and venv uses
# venv/Scripts/activate instead of venv/bin/activate.

# Print bootstrap interpreter for "python -m venv" (before venv exists).
osrsbox_bootstrap_python() {
    if command -v python3 >/dev/null 2>&1; then
        printf '%s\n' python3
    elif command -v python >/dev/null 2>&1; then
        printf '%s\n' python
    else
        echo "osrsbox: neither python3 nor python is on PATH" >&2
        return 1
    fi
}

# Activate repo venv from repository root ($1 or current directory).
osrsbox_activate_venv() {
    local root="${1:-.}"
    if [ -f "${root}/venv/Scripts/activate" ]; then
        # shellcheck disable=SC1090
        . "${root}/venv/Scripts/activate"
    elif [ -f "${root}/venv/bin/activate" ]; then
        # shellcheck disable=SC1090
        . "${root}/venv/bin/activate"
    else
        echo "osrsbox: no venv at ${root}/venv (run 3_data.sh first)." >&2
        return 1
    fi
}
