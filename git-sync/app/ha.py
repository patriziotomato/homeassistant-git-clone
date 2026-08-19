"""Persistent Home Assistant notifications via the Supervisor proxy.

Inside the app container SUPERVISOR_TOKEN is provided automatically once
config.yaml declares `homeassistant_api: true`. In local development the
token is absent and every call becomes a logged no-op.
"""

import logging
import os

import httpx

LOG = logging.getLogger("git-sync")
SUPERVISOR = os.environ.get("SUPERVISOR_URL", "http://supervisor")


def _call(service: str, payload: dict) -> bool:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        LOG.info("SUPERVISOR_TOKEN fehlt — Benachrichtigung übersprungen (%s)", service)
        return False
    try:
        response = httpx.post(
            f"{SUPERVISOR}/core/api/services/persistent_notification/{service}",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
        return True
    except httpx.HTTPError as err:
        LOG.warning("Benachrichtigung fehlgeschlagen (%s): %s", service, err)
        return False


def notify(notification_id: str, title: str, message: str) -> bool:
    return _call("create", {
        "notification_id": notification_id,
        "title": title,
        "message": message,
    })


def dismiss(notification_id: str) -> bool:
    return _call("dismiss", {"notification_id": notification_id})
