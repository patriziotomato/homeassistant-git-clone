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


def get_file(token: str, full_name: str, path: str, ref: str) -> str | None:
    """File content at ref, or None if it does not exist."""
    import base64

    try:
        data = _request(
            token, "GET", f"/repos/{full_name}/contents/{path}", params={"ref": ref}
        ).json()
    except GitHubError as err:
        if err.kind == "forbidden":  # 404 maps here
            return None
        raise
    if isinstance(data, dict) and data.get("encoding") == "base64":
        return base64.b64decode(data["content"]).decode("utf-8", "replace")
    return None


def find_open_pr(token: str, full_name: str, head_branch: str) -> dict | None:
    owner = full_name.split("/")[0]
    data = _request(
        token,
        "GET",
        f"/repos/{full_name}/pulls",
        params={"state": "open", "head": f"{owner}:{head_branch}", "per_page": 1},
    ).json()
    return _pr_fields(data[0]) if data else None


def get_pr(token: str, full_name: str, number: int) -> dict:
    return _pr_fields(_request(token, "GET", f"/repos/{full_name}/pulls/{number}").json())


def create_pr(token: str, full_name: str, head: str, base: str, title: str, body: str) -> dict:
    data = _request(
        token,
        "POST",
        f"/repos/{full_name}/pulls",
        json={"title": title, "head": head, "base": base, "body": body},
    ).json()
    return _pr_fields(data)


def merge_pr(token: str, full_name: str, number: int, method: str = "squash",
             commit_title: str | None = None) -> dict:
    # commit_title becomes the first line of the squash commit on main; the
    # body stays GitHub's default (the list of squashed commits).
    payload: dict = {"merge_method": method}
    if commit_title:
        payload["commit_title"] = commit_title
    data = _request(
        token,
        "PUT",
        f"/repos/{full_name}/pulls/{number}/merge",
        json=payload,
    ).json()
    return {"merged": bool(data.get("merged")), "sha": data.get("sha")}


def delete_branch(token: str, full_name: str, branch: str) -> None:
    try:
        _request(token, "DELETE", f"/repos/{full_name}/git/refs/heads/{branch}")
    except GitHubError:
        pass  # already gone — not worth failing the merge flow over


def _pr_fields(data: dict) -> dict:
    return {
        "number": data["number"],
        "title": data.get("title"),
        "url": data.get("html_url"),
        "state": data.get("state"),
        "mergeable": data.get("mergeable"),
        "mergeable_state": data.get("mergeable_state"),
        "commits": data.get("commits"),
        "created_at": data.get("created_at"),
    }


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
