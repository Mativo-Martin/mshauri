#!/usr/bin/env bash
# Create or update the "protect-main" ruleset from .github/rules/branch-protection.json.
# Requires: gh CLI authenticated (gh auth login) with admin rights on the repo.
set -euo pipefail

RULESET_FILE="$(dirname "$0")/../.github/rules/branch-protection.json"
REPO="${1:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
NAME="$(jq -r .name "$RULESET_FILE")"

ID="$(gh api "repos/$REPO/rulesets" --jq ".[] | select(.name==\"$NAME\") | .id" || true)"

if [[ -n "$ID" ]]; then
  echo "Updating ruleset '$NAME' ($ID) on $REPO"
  gh api --method PUT "repos/$REPO/rulesets/$ID" --input "$RULESET_FILE" >/dev/null
else
  echo "Creating ruleset '$NAME' on $REPO"
  gh api --method POST "repos/$REPO/rulesets" --input "$RULESET_FILE" >/dev/null
fi
echo "Done. Verify: https://github.com/$REPO/rules"

