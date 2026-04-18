#!/usr/bin/env python3
"""Set Wyze color bulbs to a named preset. Token-cached for fast repeat calls."""
import json
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
# Wyze access tokens live ~48h. Refresh if older than 24h.
TOKEN_TTL = 24 * 3600


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


def _apply_one(client, bulb, mode):
    mac, model = bulb["mac"], bulb["model"]
    client.bulbs.turn_on(device_mac=mac, device_model=model)
    if mode == "red":
        client.bulbs.set_color(device_mac=mac, device_model=model, color="FF0000")
    elif mode == "normal":
        client.bulbs.set_color_temp(device_mac=mac, device_model=model, color_temp=4600)
    else:
        raise SystemExit(f"unknown mode: {mode}")
    client.bulbs.set_brightness(device_mac=mac, device_model=model, brightness=100)


def apply(mode):
    bulbs = json.loads(BULBS_PATH.read_text())
    client = get_client()
    with ThreadPoolExecutor(max_workers=len(bulbs)) as pool:
        list(pool.map(lambda b: _apply_one(client, b, mode), bulbs))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
    try:
        apply(mode)
    except WyzeApiError:
        # Token likely expired — force fresh login and retry once.
        if TOKEN_PATH.exists():
            TOKEN_PATH.unlink()
        apply(mode)
