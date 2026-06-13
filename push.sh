#!/bin/bash
set -e

echo "=== push.sh starting ==="

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
echo "SCRIPT_DIR: $SCRIPT_DIR"
echo "PWD:        $(pwd)"
echo "GIT_DIR:    ${GIT_DIR:-<not set>}"

export PATH="/usr/bin:/mingw64/bin:/cmd:$PATH"
export TEMP="${TEMP:-$TMP}"
AGENT_ENV="$TEMP/ssh-agent-env.sh"

# If a saved agent exists, try to reuse it
if [ -f "$AGENT_ENV" ]; then
    source "$AGENT_ENV" 2>/dev/null || true
    # Re-affirm CWD after source (source might have side-effects)
    cd "$SCRIPT_DIR"
    if ssh-add -l &>/dev/null; then
        echo "Reusing existing ssh-agent, pushing..."
        echo "PWD before push: $(pwd)"
        git push -u origin HEAD
        exit $?
    fi
    echo "Saved agent is dead, starting a new one..."
fi

# Start a new agent
echo "Starting ssh-agent..."
ssh-agent -s > "$AGENT_ENV"
source "$AGENT_ENV"

echo "Loading key (enter passphrase)..."
ssh-add
echo "Key loaded."

cd "$SCRIPT_DIR"
echo "PWD before push: $(pwd)"
git push -u origin HEAD
echo "Done."
