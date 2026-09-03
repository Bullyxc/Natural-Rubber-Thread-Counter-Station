#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "ERROR: Raspberry Pi 5 deployment requires Raspberry Pi OS 64-bit (aarch64)."
  exit 2
fi

if [[ "${EUID}" -eq 0 ]]; then
  APT_COMMAND=(apt-get)
elif command -v sudo >/dev/null 2>&1; then
  APT_COMMAND=(sudo apt-get)
else
  echo "ERROR: Run this installer as root or install sudo first."
  exit 2
fi

"${APT_COMMAND[@]}" update
"${APT_COMMAND[@]}" install -y \
  python3 \
  python3-numpy \
  python3-opencv \
  v4l-utils

/usr/bin/python3 pi5_preflight.py

echo "System installation complete. Start with: ./run_pi5.sh"
