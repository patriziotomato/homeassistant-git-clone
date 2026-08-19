"""Minimal GitHub REST client for the setup wizard."""

import httpx

API = "https://api.github.com"


class GitHubError(Exception):
    """A GitHub call failed; `kind` is a stable, UI-friendly error code."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(detail or kind)
        self.kind = kind
        self.detail = detail


def _request(token: str, method: str, path: str, **kwargs) -> httpx.Response:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ha-git-sync",
    }
    try:
        response = httpx.request(
            method, f"{API}{path}", headers=headers, timeout=20, **kwargs
        )
    except httpx.HTTPError as err:
        raise GitHubError("network", str(err)) from err

    if response.status_code == 401:
        raise GitHubError("invalid_token")
    if response.status_code in (403, 404):
        raise GitHubError("forbidden", response.text[:300])
    if response.status_code >= 400:
        raise GitHubError("github_error", f"{response.status_code}: {response.text[:300]}")
    return response


def get_user(token: str) -> dict:
    data = _request(token, "GET", "/user").json()
    return {"login": data["login"], "name": data.get("name")}


def list_repos(token: str) -> list[dict]:
    data = _request(
        token,
        "GET",
        "/user/repos",
        params={"per_page": 100, "sort": "pushed", "affiliation": "owner,collaborator"},
    ).json()
    return [
        {
            "full_name": repo["full_name"],
            "private": repo["private"],
            "default_branch": repo.get("default_branch", "main"),
        }
        for repo in data
    ]


def list_branches(token: str, full_name: str) -> list[str]:
    data = _request(
        token, "GET", f"/repos/{full_name}/branches", params={"per_page": 100}
    ).json()
    return [branch["name"] for branch in data]


def create_repo(token: str, name: str) -> dict:
    data = _request(
        token,
        "POST",
        "/user/repos",
        json={
            "name": name,
            "private": True,
            "auto_init": True,
            "description": "Home Assistant configuration, managed by Git Sync",
        },
    ).json()
    return {
        "full_name": data["full_name"],
        "private": data["private"],
        "default_branch": data.get("default_branch", "main"),
    }
