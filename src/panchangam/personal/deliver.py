"""Delivery backends: Slack incoming webhook, and OpenClaw CLI (WhatsApp or any channel)."""
import os
import shutil
import subprocess

import requests


def slack_webhook(text: str, url_env: str = "SLACK_WEBHOOK_URL") -> None:
    url = os.environ.get(url_env)
    if not url:
        raise RuntimeError(f"{url_env} is not set")
    r = requests.post(url, json={"text": text}, timeout=15)
    r.raise_for_status()


def openclaw(text: str, channel: str, target: str, account: str | None = None) -> None:
    exe = shutil.which("openclaw") or os.path.expanduser("~/.local/bin/openclaw")
    cmd = [exe, "message", "send", "--channel", channel, "--target", target, "--message", text]
    if account:
        cmd += ["--account", account]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"openclaw failed ({res.returncode}): {res.stderr.strip() or res.stdout.strip()}")


def send(text: str, cfg: dict) -> None:
    kind = cfg["type"]
    if kind == "slack_webhook":
        slack_webhook(text, cfg.get("url_env", "SLACK_WEBHOOK_URL"))
    elif kind == "openclaw":
        target = cfg.get("target") or os.environ[cfg["target_env"]]
        openclaw(text, cfg["channel"], target, cfg.get("account"))
    else:
        raise ValueError(f"unknown delivery type: {kind}")
