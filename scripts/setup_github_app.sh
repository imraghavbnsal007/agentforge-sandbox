#!/usr/bin/env bash
# Interactive one-shot setup for GitHub App mode.
#
# Prompts for the four values from your App's settings page, writes them into
# .env, derives the commit identity, checks the private key is in place, then
# hands off to enable_github_app.sh which validates everything before it
# flips AUTH_MODE.
#
# The client secret is read with the terminal echo off, so it never appears
# on screen or in your shell history.

set -euo pipefail

cd "$(dirname "$0")/.."

ENV_FILE=".env"
KEY_PATH="secrets/agentforge.pem"

bold()  { printf "\033[1m%s\033[0m\n" "$1"; }
green() { printf "\033[0;32m%s\033[0m\n" "$1"; }
red()   { printf "\033[0;31m%s\033[0m\n" "$1"; }
amber() { printf "\033[0;33m%s\033[0m\n" "$1"; }

bold "AgentForge — GitHub App setup"
echo "Values come from https://github.com/settings/apps (your App -> General)."
echo

# --- 1. Private key --------------------------------------------------------
if [[ ! -f "$KEY_PATH" ]]; then
    red "Private key not found at $KEY_PATH"
    echo
    echo "On the App page: Private keys -> Generate a private key, then run:"
    echo
    echo "  mv ~/Downloads/*.private-key.pem \\"
    echo "     $(pwd)/$KEY_PATH"
    echo
    FOUND=$(ls -t "$HOME"/Downloads/*private-key.pem 2>/dev/null | head -1 || true)
    if [[ -n "$FOUND" ]]; then
        amber "Found a likely key in Downloads:"
        echo "  $FOUND"
        read -r -p "Move it into place now? [y/N] " REPLY
        if [[ "$REPLY" =~ ^[Yy]$ ]]; then
            mv "$FOUND" "$KEY_PATH"
            green "Moved to $KEY_PATH"
        else
            exit 1
        fi
    else
        exit 1
    fi
else
    green "Private key present at $KEY_PATH"
fi
echo

# --- 2. Collect the four values -------------------------------------------
read -r -p "App name (the URL slug, e.g. agentforge-raghav): " APP_NAME
read -r -p "App ID (numeric):                                " APP_ID
read -r -p "Client ID (starts with Iv):                      " CLIENT_ID
# -s: never echoed, never in history.
read -r -s -p "Client secret (hidden, paste and press enter): " CLIENT_SECRET
echo
echo

for pair in "APP_NAME:$APP_NAME" "APP_ID:$APP_ID" "CLIENT_ID:$CLIENT_ID" \
            "CLIENT_SECRET:$CLIENT_SECRET"; do
    if [[ -z "${pair#*:}" ]]; then
        red "${pair%%:*} was empty — nothing written. Re-run when you have it."
        exit 1
    fi
done

# --- 3. Write them into .env ----------------------------------------------
cp "$ENV_FILE" "$ENV_FILE.backup-$(date +%Y%m%d-%H%M%S)"

APP_NAME="$APP_NAME" APP_ID="$APP_ID" CLIENT_ID="$CLIENT_ID" \
CLIENT_SECRET="$CLIENT_SECRET" python3 - "$ENV_FILE" <<'PYTHON'
import os, re, sys

path = sys.argv[1]
name = os.environ["APP_NAME"].strip()

values = {
    "GITHUB_APP_NAME": name,
    "GITHUB_APP_ID": os.environ["APP_ID"].strip(),
    "GITHUB_APP_CLIENT_ID": os.environ["CLIENT_ID"].strip(),
    "GITHUB_APP_CLIENT_SECRET": os.environ["CLIENT_SECRET"].strip(),
    # GitHub attributes App commits to "<slug>[bot]".
    "GITHUB_APP_COMMIT_NAME": f"{name}[bot]",
    "GITHUB_APP_COMMIT_EMAIL": f"{name}[bot]@users.noreply.github.com",
}

lines = open(path).read().splitlines()
seen = set()
out = []
for line in lines:
    match = re.match(r"^([A-Z0-9_]+)=", line)
    key = match.group(1) if match else None
    if key in values:
        out.append(f"{key}={values[key]}")
        seen.add(key)
    else:
        out.append(line)

missing = [k for k in values if k not in seen]
if missing:
    out.append("")
    out += [f"{k}={values[k]}" for k in missing]

open(path, "w").write("\n".join(out) + "\n")
print(f"  wrote {len(values)} value(s) into {path}")
PYTHON

green "Credentials saved (previous .env backed up)."
echo

# --- 4. Validate and switch ------------------------------------------------
bold "Validating and switching to GitHub App mode…"
echo
exec ./scripts/enable_github_app.sh
