#!/bin/bash
# Install (or remove) the daily Bearings timer. The sweep self-gates on the
# cadence set in the vault's _Config.md, so this timer just ticks daily.
#   install-schedule.sh [HH:MM]      install (default 09:00)
#   install-schedule.sh --uninstall  remove
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.bearings.sweep"
TIME="${1:-09:00}"
PYTHON="$(command -v python3)"

if [ "$(uname)" = "Darwin" ]; then
  PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
  if [ "${1:-}" = "--uninstall" ]; then
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"; echo "bearings: schedule removed"; exit 0
  fi
  HOUR="${TIME%%:*}"; MIN="${TIME##*:}"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$PYTHON</string>
    <string>$SCRIPT_DIR/bearings_sweep.py</string>
  </array>
  <key>StartCalendarInterval</key><dict>
    <key>Hour</key><integer>$((10#$HOUR))</integer>
    <key>Minute</key><integer>$((10#$MIN))</integer>
  </dict>
  <key>StandardOutPath</key><string>$HOME/.bearings/sweep.log</string>
  <key>StandardErrorPath</key><string>$HOME/.bearings/sweep.log</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
</dict></plist>
EOF
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "bearings: launchd timer installed — daily $TIME (log: ~/.bearings/sweep.log)"
else
  # Linux: systemd user timer, cron fallback
  if command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1; then
    UNIT_DIR="$HOME/.config/systemd/user"; mkdir -p "$UNIT_DIR"
    if [ "${1:-}" = "--uninstall" ]; then
      systemctl --user disable --now bearings-sweep.timer 2>/dev/null || true
      rm -f "$UNIT_DIR/bearings-sweep."{service,timer}; echo "bearings: schedule removed"; exit 0
    fi
    printf '[Unit]\nDescription=Bearings sweep\n[Service]\nType=oneshot\nExecStart=%s %s/bearings_sweep.py\nStandardOutput=append:%s/.bearings/sweep.log\nStandardError=append:%s/.bearings/sweep.log\n' \
      "$PYTHON" "$SCRIPT_DIR" "$HOME" "$HOME" > "$UNIT_DIR/bearings-sweep.service"
    printf '[Unit]\nDescription=Daily Bearings sweep\n[Timer]\nOnCalendar=*-*-* %s:00\nPersistent=true\n[Install]\nWantedBy=timers.target\n' \
      "$TIME" > "$UNIT_DIR/bearings-sweep.timer"
    systemctl --user daemon-reload
    systemctl --user enable --now bearings-sweep.timer
    echo "bearings: systemd user timer installed — daily $TIME (log: ~/.bearings/sweep.log)"
  else
    CRON_LINE="${TIME##*:} ${TIME%%:*} * * * $PYTHON $SCRIPT_DIR/bearings_sweep.py >> $HOME/.bearings/sweep.log 2>&1 # bearings-sweep"
    if [ "${1:-}" = "--uninstall" ]; then
      crontab -l 2>/dev/null | grep -v '# bearings-sweep' | crontab -; echo "bearings: schedule removed"; exit 0
    fi
    (crontab -l 2>/dev/null | grep -v '# bearings-sweep'; echo "$CRON_LINE") | crontab -
    echo "bearings: cron entry installed — daily $TIME (log: ~/.bearings/sweep.log)"
  fi
fi
