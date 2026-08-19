#!/bin/bash
# Install (or remove) the daily Atlas timer. The sweep self-gates on the
# cadence set in the vault's _Config.md, so this timer just ticks daily.
#   install-schedule.sh [HH:MM]      install (default 09:00)
#   install-schedule.sh --uninstall  remove
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.atlas.sweep"
TIME="${1:-09:00}"
PYTHON="$(command -v python3)"

if [ "$(uname)" = "Darwin" ]; then
  PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
  if [ "${1:-}" = "--uninstall" ]; then
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"; echo "atlas: schedule removed"; exit 0
  fi
  HOUR="${TIME%%:*}"; MIN="${TIME##*:}"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$PYTHON</string>
    <string>$SCRIPT_DIR/atlas_sweep.py</string>
  </array>
  <key>StartCalendarInterval</key><dict>
    <key>Hour</key><integer>$((10#$HOUR))</integer>
    <key>Minute</key><integer>$((10#$MIN))</integer>
  </dict>
  <key>StandardOutPath</key><string>$HOME/.atlas/sweep.log</string>
  <key>StandardErrorPath</key><string>$HOME/.atlas/sweep.log</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
</dict></plist>
EOF
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "atlas: launchd timer installed — daily $TIME (log: ~/.atlas/sweep.log)"
else
  # Linux: systemd user timer, cron fallback
  if command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1; then
    UNIT_DIR="$HOME/.config/systemd/user"; mkdir -p "$UNIT_DIR"
    if [ "${1:-}" = "--uninstall" ]; then
      systemctl --user disable --now atlas-sweep.timer 2>/dev/null || true
      rm -f "$UNIT_DIR/atlas-sweep."{service,timer}; echo "atlas: schedule removed"; exit 0
    fi
    printf '[Unit]\nDescription=Atlas sweep\n[Service]\nType=oneshot\nExecStart=%s %s/atlas_sweep.py\nStandardOutput=append:%s/.atlas/sweep.log\nStandardError=append:%s/.atlas/sweep.log\n' \
      "$PYTHON" "$SCRIPT_DIR" "$HOME" "$HOME" > "$UNIT_DIR/atlas-sweep.service"
    printf '[Unit]\nDescription=Daily Atlas sweep\n[Timer]\nOnCalendar=*-*-* %s:00\nPersistent=true\n[Install]\nWantedBy=timers.target\n' \
      "$TIME" > "$UNIT_DIR/atlas-sweep.timer"
    systemctl --user daemon-reload
    systemctl --user enable --now atlas-sweep.timer
    echo "atlas: systemd user timer installed — daily $TIME (log: ~/.atlas/sweep.log)"
  else
    CRON_LINE="${TIME##*:} ${TIME%%:*} * * * $PYTHON $SCRIPT_DIR/atlas_sweep.py >> $HOME/.atlas/sweep.log 2>&1 # atlas-sweep"
    if [ "${1:-}" = "--uninstall" ]; then
      crontab -l 2>/dev/null | grep -v '# atlas-sweep' | crontab -; echo "atlas: schedule removed"; exit 0
    fi
    (crontab -l 2>/dev/null | grep -v '# atlas-sweep'; echo "$CRON_LINE") | crontab -
    echo "atlas: cron entry installed — daily $TIME (log: ~/.atlas/sweep.log)"
  fi
fi
