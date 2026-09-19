#!/usr/bin/env bash
# Create parallel worktrees, one branch per task, each with its own Claude Code session.
# usage: scripts/worktrees.sh hora-tests personal-card esp32-port
set -euo pipefail
repo=$(git rev-parse --show-toplevel)
base=$(dirname "$repo")
for name in "$@"; do
  dir="$base/$(basename "$repo")-$name"
  git -C "$repo" worktree add -b "feat/$name" "$dir"
  echo "→ cd $dir && claude"
done
