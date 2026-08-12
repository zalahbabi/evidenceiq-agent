#!/usr/bin/env bash
# Run once from the repo root. Git won't commit empty directories,
# so each one gets a .gitkeep.
set -e

for d in \
  app/components \
  data/raw data/processed \
  docs \
  eval/gold eval/results \
  notebooks \
  src/data src/agent src/verify src/viz src/baseline
do
  mkdir -p "$d"
  touch "$d/.gitkeep"
done

# Python packages need __init__.py to be importable
for d in src src/data src/agent src/verify src/viz src/baseline; do
  touch "$d/__init__.py"
done

echo "Folders created."
find app data docs eval notebooks src -type d | sort
