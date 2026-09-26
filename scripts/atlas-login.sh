#!/usr/bin/env bash
set -euo pipefail

readonly ORG_ID='69ef9daf03d2ce35c2657862'

reauth=false
case "${1:-}" in
  '') ;;
  --reauth) reauth=true ;;
  *)
    printf 'Usage: %s [--reauth]\n' "$0" >&2
    exit 2
    ;;
esac

if ! command -v atlas >/dev/null 2>&1; then
  printf 'Atlas CLI is required. Install it with: brew install mongodb-atlas-cli\n' >&2
  exit 1
fi

login_profile() {
  local profile_flag=()
  local profile_label='default'
  if [[ -n "${1:-}" ]]; then
    profile_flag=(-P "$1")
    profile_label="$1"
  fi

  atlas config set org_id "$ORG_ID" "${profile_flag[@]}"

  if [[ "$reauth" == true ]] && atlas auth whoami "${profile_flag[@]}" >/dev/null 2>&1; then
    atlas auth logout --force "${profile_flag[@]}"
  fi

  if ! atlas auth whoami "${profile_flag[@]}" >/dev/null 2>&1; then
    printf '\nSign in to the Atlas %s profile. Complete the one-time browser verification when prompted.\n' "$profile_label"
    atlas auth login "${profile_flag[@]}"
  else
    printf 'Atlas %s profile is already authenticated.\n' "$profile_label"
  fi
}

login_profile
login_profile mcp

printf '\nProjects in the configured organisation (%s):\n' "$ORG_ID"
atlas projects list --orgId "$ORG_ID" --output json
