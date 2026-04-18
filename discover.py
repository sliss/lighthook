#!/usr/bin/env python3
"""List Wyze devices on the account and write color bulbs to bulbs.json.

Reads creds from .env. Prints every device so you can see what's there,
then writes the subset that wyze_light.py can control to bulbs.json.
"""
import json
from pathlib import Path
from wyze_sdk import Client

BASE = Path(__file__).resolve().parent
ENV_PATH = BASE / ".env"
BULBS_PATH = BASE / "bulbs.json"

# Models known to support color + color-temp via wyze_sdk's MeshBulb API.
COLOR_BULB_MODELS = {"WLPA19C", "HL_A19C2", "HL_LSL", "HL_LSLP"}


def load_env():
    env = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


env = load_env()
client = Client(
    email=env["WYZE_EMAIL"],
    password=env["WYZE_PASSWORD"],
    key_id=env["WYZE_KEY_ID"],
    api_key=env["WYZE_API_KEY"],
)

bulbs = []
for d in client.devices_list():
    print(f"{d.type:12} | mac={d.mac} | model={d.product.model} | nickname={d.nickname}")
    if d.product.model in COLOR_BULB_MODELS:
        bulbs.append({"mac": d.mac, "model": d.product.model, "nickname": d.nickname})

BULBS_PATH.write_text(json.dumps(bulbs, indent=2) + "\n")
print(f"\nWrote {len(bulbs)} color bulb(s) to {BULBS_PATH}")
