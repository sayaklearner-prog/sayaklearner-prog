#!/usr/bin/env python3
"""Refresh the profile README with recent public GitHub development activity."""

from __future__ import annotations

import html
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

USERNAME = os.environ.get("GITHUB_USERNAME", "sayaklearner-prog")
README_PATH = Path(os.environ.get("README_PATH", "README.md"))
API_URL = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
EVENT_LIMIT = 8

START_MARKER = "<!--START_SECTION:open-source-activity-->"
END_MARKER = "<!--END_SECTION:open-source-activity-->"

IST = ZoneInfo("Asia/Kolkata")
REPO_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def safe_repo(event: dict) -> tuple[str, str] | None:
    name = (event.get("repo") or {}).get("name", "")
    if not REPO_NAME_PATTERN.fullmatch(name):
        return None
    return name, f"https://github.com/{name}"


def event_datetime(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(IST).strftime("%d %b %Y · %I:%M %p IST")
    except (TypeError, ValueError):
        return "Date unavailable"


def issue_number(item: dict) -> int | None:
    number = item.get("number")
    return number if isinstance(number, int) and number > 0 else None


def describe_event(event: dict) -> dict | None:
    repo_data = safe_repo(event)
    if not repo_data:
        return None

    repo_name, repo_url = repo_data
    payload = event.get("payload") or {}
    event_type = event.get("type")
    action = payload.get("action", "")
    emoji = "🛠️"
    label = ""
    target_url = repo_url

    if event_type == "PushEvent":
        ref = payload.get("ref", "")
        branch = ref.removeprefix("refs/heads/").removeprefix("refs/tags/")
        branch_label = f" to <code>{html.escape(branch)}</code>" if branch else ""
        count = payload.get("size") or len(payload.get("commits") or [])
        commit_word = "commit" if count == 1 else "commits"
        label = f"Pushed {count} {commit_word}{branch_label}"
        head = payload.get("head", "")
        if isinstance(head, str) and re.fullmatch(r"[0-9a-fA-F]{7,40}", head):
            target_url = f"{repo_url}/commit/{head}"
        emoji = "🚀"

    elif event_type == "PullRequestEvent":
        pr = payload.get("pull_request") or {}
        number = issue_number(pr)
        if not number:
            return None
        merged = bool(pr.get("merged"))
        if merged:
            label, emoji = f"Merged pull request #{number}", "🎉"
        elif action == "opened":
            label, emoji = f"Opened pull request #{number}", "🔀"
        elif action == "closed":
            label, emoji = f"Closed pull request #{number}", "🔒"
        elif action == "reopened":
            label, emoji = f"Reopened pull request #{number}", "🔁"
        elif action in {"synchronize", "ready_for_review"}:
            label, emoji = f"Updated pull request #{number}", "🧩"
        else:
            return None
        target_url = f"{repo_url}/pull/{number}"

    elif event_type == "IssuesEvent":
        issue = payload.get("issue") or {}
        number = issue_number(issue)
        if not number or action not in {"opened", "closed", "reopened"}:
            return None
        words = {"opened": "Opened", "closed": "Closed", "reopened": "Reopened"}
        label = f"{words[action]} issue #{number}"
        emoji = "🧩" if action == "opened" else "✅"
        target_url = f"{repo_url}/issues/{number}"

    elif event_type == "IssueCommentEvent":
        issue = payload.get("issue") or {}
        number = issue_number(issue)
        if not number:
            return None
        label, emoji = f"Commented on issue #{number}", "💬"
        target_url = f"{repo_url}/issues/{number}"

    elif event_type == "PullRequestReviewEvent":
        pr = payload.get("pull_request") or {}
        number = issue_number(pr)
        if not number:
            return None
        review = payload.get("review") or {}
        state = str(review.get("state", "")).lower()
        if state == "approved":
            label, emoji = f"Approved pull request #{number}", "✅"
        elif state == "changes_requested":
            label, emoji = f"Requested changes on pull request #{number}", "📝"
        else:
            label, emoji = f"Reviewed pull request #{number}", "🔎"
        target_url = f"{repo_url}/pull/{number}"

    elif event_type == "PullRequestReviewCommentEvent":
        pr = payload.get("pull_request") or {}
        number = issue_number(pr)
        if not number:
            return None
        label, emoji = f"Commented on pull request #{number}", "💬"
        target_url = f"{repo_url}/pull/{number}"

    elif event_type == "CommitCommentEvent":
        comment = payload.get("comment") or {}
        commit_id = comment.get("commit_id", "")
        label, emoji = "Commented on a commit", "💬"
        if isinstance(commit_id, str) and re.fullmatch(r"[0-9a-fA-F]{7,40}", commit_id):
            target_url = f"{repo_url}/commit/{commit_id}"

    elif event_type == "ReleaseEvent":
        release = payload.get("release") or {}
        tag = release.get("tag_name") or release.get("name") or ""
        if not tag:
            return None
        label, emoji = f"Published release {tag}", "🚀"
        target_url = f"{repo_url}/releases"

    else:
        return None

    title = html.escape(label)
    repo_text = html.escape(repo_name)
    date_text = html.escape(event_datetime(event.get("created_at", "")))
    url = html.escape(target_url, quote=True)

    return {
        "id": str(event.get("id", "")),
        "html": (
            '<tr>'
            f'<td align="center" width="42">{emoji}</td>'
            '<td>'
            f'<a href="{url}"><strong>{title}</strong></a><br/>'
            f'<sub><a href="{html.escape(repo_url, quote=True)}">{repo_text}</a> · {date_text}</sub>'
            '</td>'
            '</tr>'
        ),
    }


def fetch_public_events() -> list[dict]:
    endpoint = f"{API_URL}/users/{quote(USERNAME, safe='')}/events/public?per_page=100"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "sayaklearner-profile-activity",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(endpoint, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API returned HTTP {error.code}: {details}") from error
    except URLError as error:
        raise RuntimeError(f"Could not reach the GitHub API: {error.reason}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError("GitHub API returned invalid JSON.") from error

    if not isinstance(data, list):
        raise RuntimeError("GitHub API response was not an event list.")
    return data


def render_activity(events: list[dict]) -> str:
    entries = []
    seen = set()

    for event in events:
        if event.get("public") is False:
            continue
        item = describe_event(event)
        if not item or item["id"] in seen:
            continue
        seen.add(item["id"])
        entries.append(item["html"])
        if len(entries) >= EVENT_LIMIT:
            break

    refreshed = datetime.now(IST).strftime("%d %b %Y · %I:%M %p IST")
    if not entries:
        body = (
            '<tr><td align="center">'
            '<sub>No recent public development activity found. New public events will appear here automatically.</sub>'
            '</td></tr>'
        )
    else:
        body = "\n".join(entries)

    return (
        f'<p align="right"><sub>Last refreshed: {html.escape(refreshed)}</sub></p>\n'
        '<table>\n<tbody>\n'
        f'{body}\n'
        '</tbody>\n</table>'
    )


def update_readme(rendered: str) -> None:
    if not README_PATH.is_file():
        raise RuntimeError(f"README file not found: {README_PATH}")

    content = README_PATH.read_text(encoding="utf-8")
    if content.count(START_MARKER) != 1 or content.count(END_MARKER) != 1:
        raise RuntimeError("Expected exactly one pair of Open Source Activity markers in README.md.")

    start = content.index(START_MARKER) + len(START_MARKER)
    end = content.index(END_MARKER)
    if end < start:
        raise RuntimeError("Open Source Activity markers are in the wrong order.")

    updated = content[:start] + "\n" + rendered + "\n" + content[end:]
    README_PATH.write_text(updated, encoding="utf-8")


def main() -> int:
    try:
        events = fetch_public_events()
        rendered = render_activity(events)
        update_readme(rendered)
        print(f"Updated the Open Source Activity timeline for @{USERNAME}.")
        return 0
    except Exception as error:  # Fail the workflow with a useful message.
        print(f"Activity timeline update failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
