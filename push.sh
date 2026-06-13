#!/bin/bash
# push.sh — companion to push.bat, called by it via Git Bash

# cd to the directory containing this script (the repo root)
cd "$(dirname "$0")" || exit 1

AGENT_ENV="$TEMP/ssh-agent-env.sh"

# If a saved agent exists, try to reuse it
if [ -f "$AGENT_ENV" ]; then
    source "$AGENT_ENV" 2>/dev/null
    if ssh-add -l &>/dev/null; then
        echo "Reusing existing ssh-agent, pushing..."
        git push -u origin HEAD
        exit $?
    fi
fi

# Start a new agent
echo "Starting ssh-agent & loading key (enter passphrase once)..."
ssh-agent -s > "$AGENT_ENV"
source "$AGENT_ENV"
ssh-add && git push -u origin HEAD
