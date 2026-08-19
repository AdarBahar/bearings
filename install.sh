#!/bin/bash
# Atlas installer: links the skills into ~/.claude/skills and points the user
# at the onboarding wizard. Everything else is configured by /atlas-setup.
set -euo pipefail
ATLAS_HOME="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$HOME/.claude/skills"
mkdir -p "$SKILLS_DIR" "$HOME/.atlas"

for s in atlas-setup atlas-doc atlas-ops; do
  ln -sfn "$ATLAS_HOME/skills/$s" "$SKILLS_DIR/$s"
done
chmod +x "$ATLAS_HOME/scripts/atlas_sweep.py" "$ATLAS_HOME/scripts/install-schedule.sh"

# Remember where the repo lives (atlas-setup fills in the rest)
grep -q '^ATLAS_HOME=' "$HOME/.atlas/atlas.env" 2>/dev/null || \
  echo "ATLAS_HOME=$ATLAS_HOME" >> "$HOME/.atlas/atlas.env"

command -v claude >/dev/null || echo "WARNING: 'claude' CLI not found on PATH — install Claude Code first."
command -v python3 >/dev/null || { echo "ERROR: python3 is required."; exit 1; }

echo "Atlas skills installed: /atlas-setup, /atlas-doc, /atlas-ops"
echo "Next: run    claude \"/atlas-setup\"    to configure."
