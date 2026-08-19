#!/bin/bash
# Bearings installer: links the skills into ~/.claude/skills and points the user
# at the onboarding wizard. Everything else is configured by /bearings-setup.
set -euo pipefail
BEARINGS_HOME="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$HOME/.claude/skills"
mkdir -p "$SKILLS_DIR" "$HOME/.bearings"

for s in bearings-setup bearings-doc bearings-ops; do
  ln -sfn "$BEARINGS_HOME/skills/$s" "$SKILLS_DIR/$s"
done
chmod +x "$BEARINGS_HOME/scripts/bearings_sweep.py" "$BEARINGS_HOME/scripts/install-schedule.sh"

# Remember where the repo lives (bearings-setup fills in the rest)
grep -q '^BEARINGS_HOME=' "$HOME/.bearings/bearings.env" 2>/dev/null || \
  echo "BEARINGS_HOME=$BEARINGS_HOME" >> "$HOME/.bearings/bearings.env"

command -v claude >/dev/null || echo "WARNING: 'claude' CLI not found on PATH — install Claude Code first."
command -v python3 >/dev/null || { echo "ERROR: python3 is required."; exit 1; }

echo "Bearings skills installed: /bearings-setup, /bearings-doc, /bearings-ops"
echo "Next: run    claude \"/bearings-setup\"    to configure."
