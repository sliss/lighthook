#!/usr/bin/env python3
"""Drive Wyze color bulbs for Claude Code hooks.

Modes:
    red     — one-shot solid red
    normal  — stop any running pulse, set 4600K warm white
    pulse   — long-running daemon that cycles shades of red until killed
"""
import json
import os
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from wyze_sdk import Client
from wyze_sdk.errors import WyzeApiError
from wyze_sdk.models.devices.base import DeviceModels

# wyze_sdk 2.2.0 doesn't know about the newer HL_A19C2 color bulb.
# The cloud API treats it like other mesh color bulbs, so register it.
if "HL_A19C2" not in DeviceModels.MESH_BULB:
    DeviceModels.MESH_BULB = list(DeviceModels.MESH_BULB) + ["HL_A19C2"]
    DeviceModels.BULB = DeviceModels.BULB_WHITE + DeviceModels.BULB_WHITE_V2 + DeviceModels.MESH_BULB

BASE = Path(__file__).resolve().parent
ENV_PATH = BASE / ".env"
TOKEN_PATH = BASE / "token.json"
BULBS_PATH = BASE / "bulbs.json"
PID_PATH = BASE / "pulse.pid"
STATE_PATH = BASE / "state.json"
# Wyze access tokens live ~48h. Refresh if older than 24h.
TOKEN_TTL = 24 * 3600
# Re-apply even cached static modes after this long, in case the bulb
# state drifted (manual toggle, power cut, etc.).
STATE_TTL = 30 * 60
# Breathing sequence of red shades + brightness. Tuples of (hex, brightness).
PULSE_FRAMES = [
    ("FF0000", 100),
    ("FF2020", 85),
    ("FF4040", 65),
    ("FF2020", 45),
    ("CC0000", 30),
    ("990000", 20),
    ("CC0000", 30),
    ("FF0000", 45),
    ("FF2020", 65),
    ("FF4040", 85),
]
PULSE_INTERVAL = 0.9


def load_env():
    env = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def fresh_client():
    env = load_env()
    client = Client(
        email=env["WYZE_EMAIL"],
        password=env["WYZE_PASSWORD"],
        key_id=env["WYZE_KEY_ID"],
        api_key=env["WYZE_API_KEY"],
    )
    token = getattr(client, "_token", None)
    if token:
        TOKEN_PATH.write_text(json.dumps({"access_token": token, "saved_at": time.time()}))
        TOKEN_PATH.chmod(0o600)
    return client


def get_client():
    if TOKEN_PATH.exists():
        try:
            tok = json.loads(TOKEN_PATH.read_text())
            if time.time() - tok.get("saved_at", 0) < TOKEN_TTL:
                return Client(token=tok["access_token"])
        except Exception:
            pass
    return fresh_client()


def kill_pulse():
    if not PID_PATH.exists():
        return
    try:
        pid = int(PID_PATH.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        # Wait briefly for the old pulse's in-flight API call to finish
        # so its last frame doesn't race with whatever we do next.
        for _ in range(20):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
    except (ValueError, ProcessLookupError):
        pass
    try:
        PID_PATH.unlink()
    except FileNotFoundError:
        pass


STATIC_COLORS = {
    "red": "FF0000",
    "blue": "0000FF",
}


def _cached_mode():
    if not STATE_PATH.exists():
        return None
    try:
        st = json.loads(STATE_PATH.read_text())
        if time.time() - st.get("ts", 0) > STATE_TTL:
            return None
        return st.get("mode")
    except Exception:
        return None


def _write_state(mode):
    STATE_PATH.write_text(json.dumps({"mode": mode, "ts": time.time()}))


def _apply_static(mode):
    # Debounce repeated applies of the same mode — PreToolUse can fire
    # many times during a single response and each call is 6 cloud RPCs.
    if _cached_mode() == mode:
        return

    bulbs = json.loads(BULBS_PATH.read_text())
    client = get_client()

    def _one(bulb):
        mac, model = bulb["mac"], bulb["model"]
        client.bulbs.turn_on(device_mac=mac, device_model=model)
        if mode in STATIC_COLORS:
            client.bulbs.set_color(device_mac=mac, device_model=model, color=STATIC_COLORS[mode])
        elif mode == "normal":
            client.bulbs.set_color_temp(device_mac=mac, device_model=model, color_temp=4600)
        else:
            raise SystemExit(f"unknown mode: {mode}")
        client.bulbs.set_brightness(device_mac=mac, device_model=model, brightness=100)

    with ThreadPoolExecutor(max_workers=len(bulbs)) as pool:
        list(pool.map(_one, bulbs))

    _write_state(mode)


def _pulse_frame(client, bulbs, color, brightness):
    def _one(bulb):
        try:
            client.bulbs.set_color(
                device_mac=bulb["mac"], device_model=bulb["model"], color=color
            )
            client.bulbs.set_brightness(
                device_mac=bulb["mac"], device_model=bulb["model"], brightness=brightness
            )
        except WyzeApiError:
            # Transient errors shouldn't kill the pulse loop.
            pass

    with ThreadPoolExecutor(max_workers=len(bulbs)) as pool:
        list(pool.map(_one, bulbs))


def run_pulse():
    # If a pulse is already alive, leave it alone — this keeps PreToolUse
    # from restarting the loop on every tool call.
    if PID_PATH.exists():
        try:
            existing = int(PID_PATH.read_text().strip())
            os.kill(existing, 0)
            return
        except (ValueError, ProcessLookupError):
            pass  # stale pid file, fall through and start fresh
    PID_PATH.write_text(str(os.getpid()))
    _write_state("pulse")

    def _shutdown(*_):
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)

    bulbs = json.loads(BULBS_PATH.read_text())
    client = get_client()
    # Make sure bulbs are on before we start cycling.
    for b in bulbs:
        try:
            client.bulbs.turn_on(device_mac=b["mac"], device_model=b["model"])
        except WyzeApiError:
            pass

    try:
        i = 0
        while True:
            color, brightness = PULSE_FRAMES[i % len(PULSE_FRAMES)]
            _pulse_frame(client, bulbs, color, brightness)
            i += 1
            time.sleep(PULSE_INTERVAL)
    finally:
        try:
            PID_PATH.unlink()
        except FileNotFoundError:
            pass


def apply(mode):
    if mode == "pulse":
        run_pulse()
        return
    # Static modes stop any running pulse first.
    kill_pulse()
    _apply_static(mode)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
    try:
        apply(mode)
    except WyzeApiError:
        if TOKEN_PATH.exists():
            TOKEN_PATH.unlink()
        apply(mode)
