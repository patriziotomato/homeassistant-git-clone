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
        LOG.info("SUPERVISOR_TOKEN missing — notification skipped (%s)", service)
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
        LOG.warning("Notification failed (%s): %s", service, err)
        return False


def core_check() -> tuple[bool | None, str | None]:
    """Validate the Home Assistant configuration (`ha core check`).

    Returns (True, None) on success, (False, message) on a config error,
    (None, reason) when the Supervisor is unavailable (local development).
    """
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None, "supervisor_unavailable"
    try:
        response = httpx.post(
            f"{SUPERVISOR}/core/check",
            headers={"Authorization": f"Bearer {token}"},
            timeout=180,  # validates the whole configuration
        )
    except httpx.HTTPError as err:
        return False, str(err)
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code == 200 and data.get("result") == "ok":
        return True, None
    return False, str(data.get("message") or response.text)[:600]


def core_restart() -> bool:
    """Restart Home Assistant Core (`ha core restart`)."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        LOG.info("SUPERVISOR_TOKEN missing — restart skipped")
        return False
    try:
        response = httpx.post(
            f"{SUPERVISOR}/core/restart",
            headers={"Authorization": f"Bearer {token}"},
            timeout=300,
        )
        response.raise_for_status()
        return True
    except httpx.TimeoutException:
        return True  # restart initiated; core going down can drop the reply
    except httpx.HTTPError as err:
        LOG.warning("Restart failed: %s", err)
        return False


def notify(notification_id: str, title: str, message: str) -> bool:
    return _call("create", {
        "notification_id": notification_id,
        "title": title,
        "message": message,
    })


def dismiss(notification_id: str) -> bool:
    return _call("dismiss", {"notification_id": notification_id})
