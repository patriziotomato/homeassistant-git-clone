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


def _call(domain: str, service: str, payload: dict, timeout: int = 10) -> bool:
    """Call a core service through the Supervisor's API proxy."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        LOG.info("SUPERVISOR_TOKEN missing — skipped (%s.%s)", domain, service)
        return False
    try:
        response = httpx.post(
            f"{SUPERVISOR}/core/api/services/{domain}/{service}",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return True
    except httpx.HTTPError as err:
        LOG.warning("Service call failed (%s.%s): %s", domain, service, err)
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


def core_reload() -> bool:
    """Reload the YAML configuration that can be reloaded without a restart
    (`homeassistant.reload_all`).

    Deliberately not a replacement for a restart: the homeassistant: block,
    integration setup, custom_components/ code and anything evaluated only at
    startup are untouched by it.
    """
    return _call("homeassistant", "reload_all", {}, timeout=120)


def notify(notification_id: str, title: str, message: str) -> bool:
    return _call("persistent_notification", "create", {
        "notification_id": notification_id,
        "title": title,
        "message": message,
    })


def dismiss(notification_id: str) -> bool:
    return _call("persistent_notification", "dismiss",
                 {"notification_id": notification_id})
