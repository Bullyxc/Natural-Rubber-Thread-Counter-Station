#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Keep native libraries from creating more worker pools than a passive Pi 5
# can sustain. runtime_control.py applies the same safe defaults when launched
# without this helper.
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export MALLOC_ARENA_MAX="${MALLOC_ARENA_MAX:-2}"
export OPENCV_OPENCL_RUNTIME="${OPENCV_OPENCL_RUNTIME:-disabled}"

PYTHON_EXECUTABLE="${THREAD_COUNTER_PYTHON:-/usr/bin/python3}"
if [[ ! -x "$PYTHON_EXECUTABLE" ]]; then
  echo "ERROR: System Python was not found at $PYTHON_EXECUTABLE"
  echo "Run ./install_pi5_system.sh first."
  exit 2
fi

"$PYTHON_EXECUTABLE" pi5_preflight.py --quiet

configure_display_session() {
  if [[ -n "${THREAD_COUNTER_QT_PLATFORM:-}" ]]; then
    export QT_QPA_PLATFORM="$THREAD_COUNTER_QT_PLATFORM"
    return
  fi

  if [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
    export QT_QPA_PLATFORM="wayland"
    return
  fi
  if [[ -n "${DISPLAY:-}" ]]; then
    export QT_QPA_PLATFORM="xcb"
    return
  fi

  local runtime_dir="/run/user/$(id -u)"
  local candidate
  for candidate in "$runtime_dir"/wayland-*; do
    if [[ -S "$candidate" ]]; then
      export XDG_RUNTIME_DIR="$runtime_dir"
      export WAYLAND_DISPLAY="$(basename -- "$candidate")"
      export QT_QPA_PLATFORM="wayland"
      if [[ -S "$runtime_dir/bus" ]]; then
        export DBUS_SESSION_BUS_ADDRESS="unix:path=$runtime_dir/bus"
      fi
      echo "Using HDMI Wayland session: $WAYLAND_DISPLAY"
      return
    fi
  done

  if [[ -S /tmp/.X11-unix/X0 ]]; then
    export DISPLAY=":0"
    export QT_QPA_PLATFORM="xcb"
    echo "Using HDMI X11 session: $DISPLAY"
    return
  fi

  echo "ERROR: No graphical desktop session was found for the HDMI display."
  echo "Enable Desktop Autologin with sudo raspi-config, reboot, then run this script again."
  exit 3
}

configure_display_session

STATION_ENTRYPOINT="${THREAD_COUNTER_ENTRYPOINT:-pi5_usb_hdmi_station.py}"
CPUSET="${THREAD_COUNTER_CPUSET:-0-1}"

if command -v taskset >/dev/null 2>&1; then
  exec taskset -c "$CPUSET" "$PYTHON_EXECUTABLE" "$STATION_ENTRYPOINT" \
    --runtime-profile rpi5-passive "$@"
fi

exec "$PYTHON_EXECUTABLE" "$STATION_ENTRYPOINT" \
  --runtime-profile rpi5-passive "$@"
