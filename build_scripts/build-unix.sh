#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-python3}
RELEASE_DIR="$ROOT_DIR/release/unix"

mkdir -p "$RELEASE_DIR"

"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -r "$ROOT_DIR/build_scripts/requirements-build.txt"
"$PYTHON_BIN" -m PyInstaller --clean --noconfirm "$ROOT_DIR/sync_skills.spec"

cp "$ROOT_DIR/dist/sync-skills" "$RELEASE_DIR/sync-skills"
chmod +x "$RELEASE_DIR/sync-skills"
printf 'Unix binary written to %s/sync-skills\n' "$RELEASE_DIR"