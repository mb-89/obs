#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)

as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        echo "Installing uv requires root access or sudo." >&2
        return 1
    fi
}

install_with_pipx() {
    pipx install uv
    PATH="$HOME/.local/bin:$PATH"
    export PATH
}

if ! command -v uv >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then
        brew install uv
    elif command -v apt-get >/dev/null 2>&1; then
        as_root apt-get update
        if apt-cache show uv >/dev/null 2>&1; then
            as_root apt-get install -y uv
        else
            as_root apt-get install -y pipx
            install_with_pipx
        fi
    elif command -v dnf >/dev/null 2>&1; then
        if ! as_root dnf install -y uv; then
            as_root dnf install -y pipx
            install_with_pipx
        fi
    elif command -v pacman >/dev/null 2>&1; then
        as_root pacman -Sy --noconfirm uv
    elif command -v zypper >/dev/null 2>&1; then
        as_root zypper --non-interactive install uv
    elif command -v apk >/dev/null 2>&1; then
        as_root apk add uv
    else
        echo "No supported package manager found (brew, apt, dnf, pacman, zypper, or apk)." >&2
        exit 1
    fi
fi

cd "$ROOT"
uv run obs-document "$@"