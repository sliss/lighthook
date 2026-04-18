# And Claude said, LET THERE BE LIGHT.

Claude Code hooks that drive Wyze color bulbs and play audio cues so
your room reflects what Claude is doing.

- **UserPromptSubmit** / **PreToolUse** → red + `promptsent` sound
- **Notification** → blue + `notify` sound *(only when Claude was actively
  working; end-of-turn idle notifications are ignored so they don't fight
  with Stop)*
- **Stop** → 4600K warm white + `done` sound

A `pulse` mode is also implemented (breathing through red shades) if you
prefer a more dynamic working indicator — run `./venv/bin/python wyze_light.py pulse`
manually, or swap it into the `UserPromptSubmit` hook.

## Setup

You'll need a Mac, Python 3.11+, and one or more Wyze color mesh bulbs
(`WLPA19C` or `HL_A19C2` tested; other mesh models likely work).

```bash
python3.11 -m venv venv
./venv/bin/pip install wyze_sdk
```

Create `.env` in the repo root (gitignored) with Wyze credentials. The
`WYZE_KEY_ID` and `WYZE_API_KEY` come from
https://developer-api-console.wyze.com/ — generate them with your Wyze
account, free:

```
WYZE_EMAIL=you@example.com
WYZE_PASSWORD=your-wyze-password
WYZE_KEY_ID=...
WYZE_API_KEY=...
```

> Google SSO accounts don't have a native password. Use "Forgot Password"
> in the Wyze app to set one; the Google login will still work afterward.

Discover your bulbs and write `bulbs.json`:

```bash
./venv/bin/python discover.py
```

Sanity-check it works:

```bash
./venv/bin/python wyze_light.py red
./venv/bin/python wyze_light.py normal
```

Wire it into Claude Code by adding a `hooks` block to `~/.claude/settings.json`
(adjust the absolute paths to match your checkout):

```json
{
  "hooks": {
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "nohup /path/to/lighthack/venv/bin/python /path/to/lighthack/wyze_light.py red >/dev/null 2>&1 & (afplay /path/to/lighthack/promptsent.wav 2>/dev/null || afplay /System/Library/Sounds/Pop.aiff) >/dev/null 2>&1 &"}]}],
    "PreToolUse":       [{"hooks": [{"type": "command", "command": "nohup /path/to/lighthack/venv/bin/python /path/to/lighthack/wyze_light.py red >/dev/null 2>&1 &"}]}],
    "Notification":     [{"hooks": [{"type": "command", "command": "nohup /path/to/lighthack/venv/bin/python /path/to/lighthack/wyze_light.py blue >/dev/null 2>&1 & (afplay /path/to/lighthack/notify.wav 2>/dev/null || afplay /System/Library/Sounds/Glass.aiff) >/dev/null 2>&1 &"}]}],
    "Stop":             [{"hooks": [{"type": "command", "command": "nohup /path/to/lighthack/venv/bin/python /path/to/lighthack/wyze_light.py normal >/dev/null 2>&1 & (afplay /path/to/lighthack/done.wav 2>/dev/null || afplay /System/Library/Sounds/Hero.aiff) >/dev/null 2>&1 &"}]}]
  }
}
```

Reload your Claude Code session and submit a prompt.

## Using your own sounds

Drop your own audio files into the repo root with these exact names:

| Event | File | System fallback |
|---|---|---|
| UserPromptSubmit | `promptsent.wav` | `Pop.aiff` |
| Notification | `notify.wav` | `Glass.aiff` |
| Stop | `done.wav` | `Hero.aiff` |

The hook commands try your file first (`afplay ... 2>/dev/null`) and only
fall back to `/System/Library/Sounds/*.aiff` if it's missing or fails. Any
format `afplay` supports works — `.wav`, `.aiff`, `.mp3`, `.m4a`, etc. — as
long as the filename matches.

Audio files are gitignored, so replacing them is a local-only change;
feel free to keep something embarrassing there without worrying about it
landing in a pushed commit.

## Why the debounce

Each bulb command costs ~0.5s round-trip to the Wyze cloud. Setting two
bulbs to a new color is six calls (turn_on + set_color + set_brightness
per bulb). `PreToolUse` fires on every tool call during a response, so a
naive "set red" hook would hammer the API and lag Claude's responsiveness.

`wyze_light.py` writes the current mode to `state.json` and short-circuits
repeated applies of the same mode. Cached state expires after 30 minutes
so real drift (manual toggle, power cut) eventually recovers on its own.

## Why Google SSO breaks `wyze_sdk`

`wyze_sdk` speaks Wyze's legacy email+password login flow. It can't
exchange a Google OAuth token, so SSO-only accounts need a password set
via the "Forgot Password" reset flow before any of this works.

## Files

| File | Role | Tracked |
|---|---|---|
| `wyze_light.py` | Mode dispatcher (red / blue / normal / pulse) | yes |
| `discover.py` | Lists devices, writes `bulbs.json` | yes |
| `.gitignore` | Keeps secrets / cache / audio out | yes |
| `.env` | Wyze credentials | no |
| `bulbs.json` | Discovered bulb MACs + models | no |
| `state.json` | Debounce cache | no |
| `pulse.pid` | Running-pulse PID | no |
| `token.json` | Cached Wyze auth token (24h TTL) | no |
| `*.wav` / `*.aiff` | Your custom sounds | no |
