#!/usr/bin/env zsh
set -euo pipefail

# -----------------------------------------------------------------------------
# scripts/setup_brew_autoupdate.zsh
#
# Self-contained, idempotent macOS (Apple Silicon) provisioning script that:
#   1. Verifies Homebrew (/opt/homebrew/bin/brew) and ensures jq is installed.
#   2. Adopts or installs the Antigravity IDE cask (antigravity-ide).
#   3. Cleans up broken/orphaned Caskroom receipts (e.g. orbstack).
#   4. Configures domt4/autoupdate launchd agent on a daily schedule.
#   5. Audits installed casks for interactive .pkg / installer / sudo usage.
#   6. Kickstarts the background job and logs macOS App Management reminders.
#
# Usage:
#   ./scripts/setup_brew_autoupdate.zsh [HH:MM]
# -----------------------------------------------------------------------------

SCHEDULE_TIME="${1:-09:00}"

log_info() {
  printf '[%s] [INFO] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

log_error() {
  printf '[%s] [ERROR] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
}

# 1. Prerequisites & Environment Verification
log_info "Step 1 - Verifying Homebrew installation and environment..."
if [[ ! -x "/opt/homebrew/bin/brew" ]]; then
  log_error "Homebrew binary not found at /opt/homebrew/bin/brew."
  exit 1
fi

if [[ ":${PATH}:" != *":/opt/homebrew/bin:"* ]]; then
  export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:${PATH}"
  log_info "Step 1 - Added /opt/homebrew/bin to PATH."
else
  log_info "Step 1 - /opt/homebrew/bin is already in PATH."
fi

log_info "Step 1 - Ensuring jq formula is installed..."
brew list jq >/dev/null 2>&1 || brew install jq

# 2. Antigravity IDE Cask Adoption
log_info "Step 2 - Checking Homebrew tracking for antigravity-ide..."
if brew list --cask antigravity-ide >/dev/null 2>&1; then
  log_info "Step 2 - Cask antigravity-ide is already tracked by Homebrew."
elif [[ -d "/Applications/Antigravity IDE.app" ]]; then
  log_info "Step 2 - Adopting existing /Applications/Antigravity IDE.app into Homebrew..."
  brew install --cask --adopt antigravity-ide
else
  log_info "Step 2 - Installing antigravity-ide cask via Homebrew..."
  brew install --cask antigravity-ide
fi

# 3. Stale Cask Receipt Cleanup (Optional Parameter / Guard)
log_info "Step 3 - Checking /opt/homebrew/Caskroom for orphaned cask receipts..."
if [[ -d "/opt/homebrew/Caskroom/orbstack" && ! -d "/Applications/OrbStack.app" ]]; then
  log_info "Step 3 - Removing orphaned cask receipt /opt/homebrew/Caskroom/orbstack (/Applications/OrbStack.app is absent)."
  rm -rf "/opt/homebrew/Caskroom/orbstack"
fi

while IFS=$'\t' read -r cask_token uninstaller_exec; do
  [[ -z "${cask_token}" || -z "${uninstaller_exec}" ]] && continue
  if [[ ! -e "${uninstaller_exec}" && -d "/opt/homebrew/Caskroom/${cask_token}" ]]; then
    log_info "Step 3 - Removing broken cask receipt /opt/homebrew/Caskroom/${cask_token} (missing uninstaller ${uninstaller_exec})."
    rm -rf "/opt/homebrew/Caskroom/${cask_token}"
  fi
done < <(
  brew info --cask --json=v2 --installed 2>/dev/null | jq -r '
    .casks[]
    | .token as $token
    | .artifacts[]?
    | .uninstall[]?
    | .script.executable? // empty
    | select(startswith("/Applications/") and contains(".app"))
    | "\($token)\t\(.)"
  ' || true
)

# 4. Configure domt4/autoupdate
log_info "Step 4 - Configuring domt4/autoupdate for daily schedule (${SCHEDULE_TIME})..."
if ! brew tap | grep -qx "domt4/autoupdate"; then
  log_info "Step 4 - Tapping domt4/autoupdate..."
  brew tap domt4/autoupdate
fi

log_info "Step 4 - Trusting external command domt4/autoupdate/autoupdate..."
brew trust --command domt4/autoupdate/autoupdate

mkdir -p "${HOME}/Library/LaunchAgents"

autoupdate_status="$(brew autoupdate status 2>&1 || true)"
if [[ "${autoupdate_status}" == *"running"* || "${autoupdate_status}" == *"installed"* ]]; then
  log_info "Step 4 - Existing autoupdate configuration detected; deleting prior launchd plist..."
  brew autoupdate delete >/dev/null 2>&1 || true
fi

log_info "Step 4 - Starting brew autoupdate at ${SCHEDULE_TIME} with --upgrade --cleanup --greedy..."
brew autoupdate start "${SCHEDULE_TIME}" --upgrade --cleanup --greedy

# 5. Non-Interactive sudo / .pkg Cask Audit
log_info "Step 5 - Auditing installed casks for interactive sudo or pkg installers..."
sudo_casks="$(
  brew info --cask --json=v2 --installed | jq -r '
    .casks[]
    | select((.artifacts | tostring) | test("\"pkg\"|\"installer\"|\"sudo\":true"))
    | .token
  '
)"

if [[ -z "${sudo_casks}" ]]; then
  log_info "Step 5 - Audit complete: 0 installed casks require interactive sudo privileges."
else
  sudo_cask_list="${sudo_casks//$'\n'/, }"
  log_info "Step 5 - Audit complete: casks requiring interactive updates or installer privileges: ${sudo_cask_list}"
fi

# 6. Verification & macOS Permissions Reminder
log_info "Step 6 - Triggering immediate background verification run via launchctl kickstart..."
launchctl kickstart -k "gui/$(id -u)/com.github.domt4.homebrew-autoupdate"
log_info "Step 6 - Verification log path: ~/Library/Logs/com.github.domt4.homebrew-autoupdate/com.github.domt4.homebrew-autoupdate.out"
log_info "Step 6 - Reminder: ensure ~/Library/Application Support/com.github.domt4.homebrew-autoupdate/brew_autoupdate is enabled under System Settings -> Privacy & Security -> App Management."
