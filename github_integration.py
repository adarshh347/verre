"""Thin wrapper around the `gh` CLI so the calendar/task app can create and
list GitHub issues without needing its own OAuth flow or API token handling.
`gh` already manages auth (`gh auth login`) and is present on this machine.
"""
import json
import re
import shutil
import subprocess

GH_BIN = shutil.which("gh")
GIT_BIN = shutil.which("git")

_REMOTE_RE = re.compile(
    r"(?:git@github\.com:|https://github\.com/)(?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?$"
)


class GithubError(RuntimeError):
    pass


def gh_available():
    return GH_BIN is not None


def gh_authenticated():
    if not GH_BIN:
        return False
    try:
        result = subprocess.run(
            [GH_BIN, "auth", "status"], capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


def detect_repo_from_path(local_path):
    """Return (owner, repo) by reading the `origin` remote of a local git
    checkout, or (None, None) if it can't be determined."""
    if not local_path or not GIT_BIN:
        return None, None
    try:
        result = subprocess.run(
            [GIT_BIN, "-C", local_path, "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None, None
    if result.returncode != 0:
        return None, None
    match = _REMOTE_RE.search(result.stdout.strip())
    if not match:
        return None, None
    return match.group("owner"), match.group("repo")


def create_issue(owner, repo, title, body=""):
    """Create a GitHub issue via `gh issue create`. Returns (number, url).
    Raises GithubError with a human-readable message on failure."""
    if not GH_BIN:
        raise GithubError("The `gh` CLI isn't installed.")
    if not gh_authenticated():
        raise GithubError(
            "gh isn't logged in yet. Run `gh auth login` in a terminal, then retry."
        )
    cmd = [
        GH_BIN, "issue", "create",
        "--repo", f"{owner}/{repo}",
        "--title", title,
        "--body", body or "(created from desktop calendar widget)",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        raise GithubError("Timed out talking to GitHub.")
    if result.returncode != 0:
        raise GithubError(result.stderr.strip() or "gh issue create failed.")
    url = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    number_match = re.search(r"/issues/(\d+)", url)
    number = int(number_match.group(1)) if number_match else None
    return number, url


def list_open_issues(owner, repo, limit=30):
    if not GH_BIN or not gh_authenticated():
        return []
    cmd = [
        GH_BIN, "issue", "list",
        "--repo", f"{owner}/{repo}",
        "--state", "open",
        "--limit", str(limit),
        "--json", "number,title,url,updatedAt",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return []
    if result.returncode != 0:
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
