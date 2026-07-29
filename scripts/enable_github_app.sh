#!/usr/bin/env bash
# Switch AgentForge from single-user local mode to public GitHub App mode.
#
# Safe by design: it validates every prerequisite BEFORE changing anything.
# Flipping AUTH_MODE while the App is incomplete locks you out of the UI —
# the frontend redirects to /login and sign-in cannot work — so this script
# refuses to flip until it can prove the switch will succeed.
#
# Re-runnable. Run with --check to validate without changing anything.

set -euo pipefail

cd "$(dirname "$0")/.."

ENV_FILE=".env"
KEY_DIR="secrets"
CHECK_ONLY="${1:-}"

green() { printf "\033[0;32m%s\033[0m\n" "$1"; }
red()   { printf "\033[0;31m%s\033[0m\n" "$1"; }
amber() { printf "\033[0;33m%s\033[0m\n" "$1"; }
bold()  { printf "\033[1m%s\033[0m\n" "$1"; }

value_of() {
    # Read a key from .env without sourcing it (values may contain anything).
    grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- || true
}

PROBLEMS=0
report_missing() {
    red "  ✗ $1"
    [[ -n "${2:-}" ]] && printf "      %s\n" "$2"
    PROBLEMS=$((PROBLEMS + 1))
}

bold "Checking GitHub App configuration…"
echo

if [[ ! -f "$ENV_FILE" ]]; then
    red "No .env found. Copy .env.example first."
    exit 1
fi

# --- 1. Required values ----------------------------------------------------
for key in GITHUB_APP_NAME GITHUB_APP_ID GITHUB_APP_CLIENT_ID \
           GITHUB_APP_CLIENT_SECRET GITHUB_APP_WEBHOOK_SECRET \
           GITHUB_APP_COMMIT_NAME GITHUB_APP_COMMIT_EMAIL; do
    if [[ -z "$(value_of "$key")" ]]; then
        case "$key" in
            GITHUB_APP_NAME)
                report_missing "$key" "The App's URL slug, from github.com/apps/<slug>" ;;
            GITHUB_APP_ID)
                report_missing "$key" "The numeric App ID on the App settings page" ;;
            GITHUB_APP_CLIENT_ID)
                report_missing "$key" "Client ID on the App settings page" ;;
            GITHUB_APP_CLIENT_SECRET)
                report_missing "$key" "Generate a client secret; it is shown once" ;;
            GITHUB_APP_COMMIT_NAME|GITHUB_APP_COMMIT_EMAIL)
                report_missing "$key" "e.g. <slug>[bot] and <slug>[bot]@users.noreply.github.com" ;;
            *)
                report_missing "$key" ;;
        esac
    else
        green "  ✓ $key"
    fi
done

# --- 2. Private key --------------------------------------------------------
KEY_PATH="$(value_of GITHUB_APP_PRIVATE_KEY_PATH)"
if [[ -z "$KEY_PATH" ]]; then
    report_missing "GITHUB_APP_PRIVATE_KEY_PATH"
else
    # The container sees /run/secrets; on the host that is ./secrets.
    HOST_KEY="${KEY_PATH/\/run\/secrets/$KEY_DIR}"
    if [[ ! -f "$HOST_KEY" ]]; then
        report_missing "private key not found at $HOST_KEY" \
            "Download the .pem from the App page and save it there."
    elif ! grep -q "PRIVATE KEY" "$HOST_KEY"; then
        report_missing "$HOST_KEY is not a PEM private key"
    else
        green "  ✓ private key present at $HOST_KEY"
    fi
fi

echo
if [[ "$PROBLEMS" -gt 0 ]]; then
    red "$PROBLEMS item(s) still needed — AUTH_MODE left as-is."
    echo
    bold "Create the App at: https://github.com/settings/apps/new"
    cat <<'GUIDE'

  Homepage URL   http://localhost:3000
  Callback URL   http://localhost:8000/api/v1/auth/github/callback
  Setup URL      http://localhost:8000/api/v1/github/setup

  [x] Request user authorization (OAuth) during installation   <- REQUIRED
  [x] Redirect on update
  [ ] Webhook -> Active            (leave OFF; no tunnel needed to start)

  Repository permissions:
      Metadata        Read-only
      Contents        Read and write
      Pull requests   Read and write

  Where can this be installed?  ->  Any account

  Then: "Generate a private key" and save the .pem as
        agentforge/secrets/agentforge.pem

GUIDE
    exit 1
fi

green "All prerequisites satisfied."

if [[ "$CHECK_ONLY" == "--check" ]]; then
    echo "(--check: nothing changed)"
    exit 0
fi

# --- 3. Flip the switch ----------------------------------------------------
echo
if [[ "$(value_of AUTH_MODE)" == "github_app" ]]; then
    amber "AUTH_MODE is already github_app."
else
    cp "$ENV_FILE" "$ENV_FILE.backup-$(date +%Y%m%d-%H%M%S)"
    # Replace the active AUTH_MODE line, leaving comments untouched.
    if grep -qE "^AUTH_MODE=" "$ENV_FILE"; then
        sed -i.tmp -E "s|^AUTH_MODE=.*|AUTH_MODE=github_app|" "$ENV_FILE"
        rm -f "$ENV_FILE.tmp"
    else
        printf "\nAUTH_MODE=github_app\n" >> "$ENV_FILE"
    fi
    green "AUTH_MODE -> github_app (previous .env backed up)"
fi

echo
bold "Restarting backend, worker and frontend…"
docker compose up -d backend worker frontend

echo
bold "Waiting for the backend to report ready…"
for _ in $(seq 1 30); do
    if curl -fsS http://localhost:8000/ready >/dev/null 2>&1; then break; fi
    sleep 2
done

MODE="$(curl -fsS http://localhost:8000/api/v1/auth/me 2>/dev/null \
        | grep -o '"auth_mode":"[^"]*"' | cut -d'"' -f4 || echo unknown)"

echo
if [[ "$MODE" == "github_app" ]]; then
    green "AgentForge is now in public GitHub App mode."
    cat <<'NEXT'

Next, in the browser:
  1. open http://localhost:3000  -> you should see a sign-in page
  2. Sign in with GitHub
  3. Repositories -> Install GitHub App
  4. Choose an account and pick the repositories to grant
  5. Register one, then create a task

You will never edit GITHUB_ALLOWED_REPOS again — the installation grant
replaces it entirely.
NEXT
else
    red "Backend did not come up in github_app mode (reported: $MODE)."
    echo "Check the logs:  docker compose logs backend --tail=40"
    echo "To go back:      set AUTH_MODE=local in .env and rerun 'docker compose up -d backend'"
fi
