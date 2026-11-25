#!/usr/bin/env python3
"""Generate a dark, dashboard-style public GitHub activity panel for the profile README."""

from __future__ import annotations

import html
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

USERNAME = os.environ.get("GITHUB_USERNAME", "sayaklearner-prog")
README_PATH = Path(os.environ.get("README_PATH", "README.md"))
OUTPUT_PATH = Path("assets/open-source-activity.svg")
API_URL = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
EVENT_LIMIT = 8

START_MARKER = "<!--START_SECTION:open-source-activity-->"
END_MARKER = "<!--END_SECTION:open-source-activity-->"

IST = ZoneInfo("Asia/Kolkata")
REPO_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

WIDTH = 1440
HEIGHT = 980
BG = "#0b0e14"
PANEL = "#111722"
CARD = "#151d29"
BORDER = "#263142"
TEXT = "#f1f5f9"
MUTED = "#9aa8b8"
PURPLE = "#9885ff"
GREEN = "#2ac49a"
GOLD = "#e7bd69"
RED = "#f17878"
BLUE = "#63a8ff"
ORANGE = "#ee9867"


def safe_repo(event: dict) -> tuple[str, str] | None:
    name = (event.get("repo") or {}).get("name", "")
    if not isinstance(name, str) or not REPO_NAME_PATTERN.fullmatch(name):
        return None
    return name, f"https://github.com/{name}"


def parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def format_datetime(value: str) -> str:
    parsed = parse_datetime(value)
    if not parsed:
        return "Date unavailable"
    return parsed.astimezone(IST).strftime("%d %b %Y · %I:%M %p IST")


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
    emoji = "•"
    category = "other"
    label = ""
    target_url = repo_url

    if event_type == "PushEvent":
        ref = payload.get("ref", "")
        branch = ref.removeprefix("refs/heads/").removeprefix("refs/tags/")
        count = len(payload.get("commits") or [])
        if count == 0:
            count = payload.get("size") or 0
        if count:
            word = "commit" if count == 1 else "commits"
            label = f"Pushed {count} {word}"
        else:
            label = "Pushed code updates"
        if branch:
            label += f" to {branch}"
        head = payload.get("head", "")
        if isinstance(head, str) and re.fullmatch(r"[0-9a-fA-F]{7,40}", head):
            target_url = f"{repo_url}/commit/{head}"
        emoji, category = "↗", "pushes"

    elif event_type == "PullRequestEvent":
        pr = payload.get("pull_request") or {}
        number = issue_number(pr)
        if not number:
            return None
        merged = bool(pr.get("merged"))
        state = pr.get("state")
        if merged or pr.get("merged_at"):
            label, emoji = f"Merged pull request #{number}", "✓"
        elif action == "opened":
            label, emoji = f"Opened pull request #{number}", "↗"
        elif action == "closed" or state == "closed":
            label, emoji = f"Closed pull request #{number}", "×"
        elif action == "reopened":
            label, emoji = f"Reopened pull request #{number}", "↻"
        elif action in {"synchronize", "ready_for_review"}:
            label, emoji = f"Updated pull request #{number}", "↻"
        else:
            return None
        target_url = f"{repo_url}/pull/{number}"
        category = "prs"

    elif event_type == "IssuesEvent":
        issue = payload.get("issue") or {}
        number = issue_number(issue)
        if not number or action not in {"opened", "closed", "reopened"}:
            return None
        words = {"opened": "Opened", "closed": "Closed", "reopened": "Reopened"}
        label = f"{words[action]} issue #{number}"
        emoji = "○" if action == "opened" else "✓"
        target_url = f"{repo_url}/issues/{number}"
        category = "issues"

    elif event_type == "IssueCommentEvent":
        issue = payload.get("issue") or {}
        number = issue_number(issue)
        if not number:
            return None
        label, emoji, category = f"Commented on issue #{number}", "✎", "reviews"
        target_url = f"{repo_url}/issues/{number}"

    elif event_type == "PullRequestReviewEvent":
        pr = payload.get("pull_request") or {}
        number = issue_number(pr)
        if not number:
            return None
        review = payload.get("review") or {}
        state = str(review.get("state", "")).lower()
        if state == "approved":
            label, emoji = f"Approved pull request #{number}", "✓"
        elif state == "changes_requested":
            label, emoji = f"Requested changes on pull request #{number}", "!"
        else:
            label, emoji = f"Reviewed pull request #{number}", "⌕"
        target_url = f"{repo_url}/pull/{number}"
        category = "reviews"

    elif event_type == "PullRequestReviewCommentEvent":
        pr = payload.get("pull_request") or {}
        number = issue_number(pr)
        if not number:
            return None
        label, emoji, category = f"Commented on pull request #{number}", "✎", "reviews"
        target_url = f"{repo_url}/pull/{number}"

    elif event_type == "CommitCommentEvent":
        comment = payload.get("comment") or {}
        commit_id = comment.get("commit_id", "")
        label, emoji, category = "Commented on a commit", "✎", "reviews"
        if isinstance(commit_id, str) and re.fullmatch(r"[0-9a-fA-F]{7,40}", commit_id):
            target_url = f"{repo_url}/commit/{commit_id}"

    elif event_type == "ReleaseEvent":
        release = payload.get("release") or {}
        tag = release.get("tag_name") or release.get("name") or ""
        if not tag:
            return None
        label, emoji, category = f"Published release {tag}", "◆", "other"
        target_url = f"{repo_url}/releases"

    elif event_type == "CreateEvent":
        ref_type = payload.get("ref_type", "branch")
        if ref_type == "repository":
            label, emoji, category = "Created a public repository", "+", "other"
        else:
            ref = payload.get("ref", "")
            label = f"Created {ref_type}" + (f" {ref}" if ref else "")
            emoji, category = "+", "other"

    elif event_type == "ForkEvent":
        label, emoji, category = "Forked a repository", "⑂", "other"
        fork = payload.get("forkee") or {}
        html_url = fork.get("html_url")
        if isinstance(html_url, str) and html_url.startswith("https://github.com/"):
            target_url = html_url

    else:
        return None

    created_at = event.get("created_at", "")
    date_text = format_datetime(created_at)
    safe_label = html.escape(label)
    safe_repo_name = html.escape(repo_name)
    safe_repo_url = html.escape(repo_url, quote=True)
    safe_target_url = html.escape(target_url, quote=True)

    return {
        "id": str(event.get("id", "")),
        "repo": repo_name,
        "repo_url": repo_url,
        "label": label,
        "date": date_text,
        "created_at": created_at,
        "emoji": emoji,
        "category": category,
        "target_url": target_url,
        "html": (
            "<tr>"
            f'<td align="center" width="38"><strong>{html.escape(emoji)}</strong></td>'
            "<td>"
            f'<a href="{safe_target_url}"><strong>{safe_label}</strong></a><br/>'
            f'<sub><a href="{safe_repo_url}">{safe_repo_name}</a> · {html.escape(date_text)}</sub>'
            "</td>"
            "</tr>"
        ),
    }


def fetch_public_events() -> list[dict]:
    """Fetch up to three pages (300 events); GitHub retains public events for 30 days."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "sayaklearner-profile-activity",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    all_events: list[dict] = []
    seen_ids: set[str] = set()

    for page in range(1, 4):
        endpoint = (
            f"{API_URL}/users/{quote(USERNAME, safe='')}/events/public"
            f"?per_page=100&page={page}"
        )
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
        if not data:
            break

        for event in data:
            # Ignore activity generated by the profile README and its own automation.
            repo_name = (event.get("repo") or {}).get("name", "").lower()
            if repo_name == f"{USERNAME}/{USERNAME}".lower():
                continue
            event_id = str(event.get("id", ""))
            if event_id and event_id not in seen_ids:
                seen_ids.add(event_id)
                all_events.append(event)

        if len(data) < 100:
            break

    return all_events


def aggregate(events: list[dict]) -> dict:
    pr_states: dict[str, str] = {}
    issue_keys: set[str] = set()
    reviews = 0
    pushes = 0
    activity_by_week: dict[str, Counter] = defaultdict(Counter)

    now_local = datetime.now(IST)
    monday = now_local.date() - timedelta(days=now_local.weekday())
    week_starts = [monday - timedelta(weeks=5 - i) for i in range(6)]

    for event in events:
        if event.get("public") is False:
            continue

        desc = describe_event(event)
        if not desc:
            continue

        event_type = event.get("type")
        payload = event.get("payload") or {}
        repo_name = (event.get("repo") or {}).get("name", "")
        created = parse_datetime(event.get("created_at", ""))
        if created:
            local_day = created.astimezone(IST).date()
            week_index = (local_day - week_starts[0]).days // 7
            if 0 <= week_index < len(week_starts):
                activity_by_week[str(week_starts[week_index])][desc["category"]] += 1

        if event_type == "PullRequestEvent":
            pr = payload.get("pull_request") or {}
            number = issue_number(pr)
            if number:
                key = f"{repo_name}#{number}"
                if key not in pr_states:
                    if pr.get("merged") or pr.get("merged_at"):
                        pr_states[key] = "merged"
                    elif pr.get("state") == "closed" or payload.get("action") == "closed":
                        pr_states[key] = "closed"
                    else:
                        pr_states[key] = "open"

        elif event_type == "IssuesEvent":
            issue = payload.get("issue") or {}
            number = issue_number(issue)
            if number:
                issue_keys.add(f"{repo_name}#{number}")

        elif event_type in {"PullRequestReviewEvent", "PullRequestReviewCommentEvent", "IssueCommentEvent", "CommitCommentEvent"}:
            reviews += 1

        elif event_type == "PushEvent":
            pushes += 1

    statuses = Counter(pr_states.values())
    weekly = {
        "labels": [d.strftime("%d %b") for d in week_starts],
        "prs": [],
        "pushes": [],
        "issues": [],
    }
    for week in week_starts:
        counts = activity_by_week[str(week)]
        weekly["prs"].append(counts["prs"])
        weekly["pushes"].append(counts["pushes"])
        weekly["issues"].append(counts["issues"] + counts["reviews"])

    visible_count = sum(1 for e in events if e.get("public") is not False)
    return {
        "public_events": visible_count,
        "prs": len(pr_states),
        "open_prs": statuses["open"],
        "merged_prs": statuses["merged"],
        "closed_prs": statuses["closed"],
        "issues": len(issue_keys),
        "reviews": reviews,
        "pushes": pushes,
        "weekly": weekly,
    }


def svg_text(x: int, y: int, value: str, size: int, color: str = TEXT, weight: int = 400) -> str:
    return (
        f'<text x="{x}" y="{y}" fill="{color}" font-family="Inter,Segoe UI,Arial,sans-serif" '
        f'font-size="{size}" font-weight="{weight}">{html.escape(str(value))}</text>'
    )


def truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def render_svg(events: list[dict], stats: dict) -> str:
    now_text = datetime.now(IST).strftime("%d %b %Y · %I:%M %p IST")
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">',
        "<title id=\"title\">Open Source Activity Dashboard</title>",
        "<desc id=\"desc\">Recent public GitHub activity including pull requests, pushes, issues, reviews and weekly trends.</desc>",
        f'<rect width="{WIDTH}" height="{HEIGHT}" rx="24" fill="{BG}"/>',
        svg_text(32, 52, "OPEN SOURCE ACTIVITY", 28, TEXT, 750),
        svg_text(32, 83, "Your public engineering activity at a glance · Recent GitHub events", 15, MUTED, 400),
        svg_text(1400, 52, "UPDATED", 11, MUTED, 650),
        f'<text x="1400" y="78" text-anchor="end" fill="{TEXT}" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="14">{html.escape(now_text)}</text>',
    ]

    cards = [
        ("PUBLIC EVENTS", stats["public_events"], "Recent public GitHub events", BLUE),
        ("PULL REQUESTS", stats["prs"], "Unique PRs in event window", PURPLE),
        ("CODE PUSHES", stats["pushes"], "Visible push events", GREEN),
        ("CODE REVIEWS", stats["reviews"], "Reviews and code comments", ORANGE),
    ]
    card_x = [24, 246, 468, 690]
    for (label, value, sub, accent), x in zip(cards, card_x):
        parts.extend([
            f'<rect x="{x}" y="112" width="208" height="142" rx="16" fill="{CARD}" stroke="{BORDER}"/>',
            f'<rect x="{x}" y="112" width="4" height="142" rx="2" fill="{accent}"/>',
            svg_text(x + 20, 148, label, 12, MUTED, 650),
            svg_text(x + 20, 202, value, 38, TEXT, 750),
            svg_text(x + 20, 229, sub, 11, MUTED, 400),
        ])

    # Pull request status panel and donut chart.
    panel_x, panel_y, panel_w, panel_h = 924, 112, 492, 310
    parts.extend([
        f'<rect x="{panel_x}" y="{panel_y}" width="{panel_w}" height="{panel_h}" rx="18" fill="{PANEL}" stroke="{BORDER}"/>',
        svg_text(panel_x + 22, panel_y + 38, "PULL REQUEST STATUS", 17, TEXT, 700),
        svg_text(panel_x + 22, panel_y + 64, "Breakdown of unique PRs in the recent event window", 12, MUTED, 400),
    ])

    cx, cy, radius = 1084, 286, 76
    total_prs = stats["prs"]
    circumference = 2 * 3.141592653589793 * radius
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="#293444" stroke-width="22"/>')
    offset = 0.0
    for key, color in (("merged_prs", GREEN), ("open_prs", GOLD), ("closed_prs", RED)):
        count = stats[key]
        length = circumference * count / total_prs if total_prs else 0
        if length > 0:
            parts.append(
                f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="{color}" '
                f'stroke-width="22" stroke-dasharray="{length:.2f} {circumference - length:.2f}" '
                f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {cx} {cy})"/>'
            )
            offset += length
    parts.extend([
        f'<text x="{cx}" y="{cy - 2}" text-anchor="middle" fill="{TEXT}" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="31" font-weight="750">{total_prs}</text>',
        f'<text x="{cx}" y="{cy + 22}" text-anchor="middle" fill="{MUTED}" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="11">TOTAL PRs</text>',
    ])

    legend = [
        ("OPEN", stats["open_prs"], GOLD, 1190, 221),
        ("MERGED", stats["merged_prs"], GREEN, 1190, 270),
        ("CLOSED", stats["closed_prs"], RED, 1190, 319),
    ]
    for label, count, color, x, y in legend:
        parts.append(f'<circle cx="{x}" cy="{y - 4}" r="6" fill="{color}"/>')
        parts.append(svg_text(x + 17, y, f"{label}  {count}", 13, TEXT, 600))

    # Recent activity list.
    list_x, list_y, list_w, list_h = 24, 278, 880, 668
    parts.extend([
        f'<rect x="{list_x}" y="{list_y}" width="{list_w}" height="{list_h}" rx="18" fill="{PANEL}" stroke="{BORDER}"/>',
        svg_text(list_x + 24, list_y + 42, "RECENT OPEN SOURCE ACTIVITY", 17, TEXT, 700),
        svg_text(list_x + 24, list_y + 67, "Latest public pull requests, commits, issues, reviews and releases", 12, MUTED, 400),
    ])

    feed = []
    seen = set()
    for event in events:
        if event.get("public") is False:
            continue
        item = describe_event(event)
        if not item or item["id"] in seen:
            continue
        seen.add(item["id"])
        feed.append(item)
        if len(feed) >= EVENT_LIMIT:
            break

    row_y = list_y + 94
    row_h = 65
    if not feed:
        parts.append(svg_text(list_x + 28, row_y + 40, "No recent public development events were returned by GitHub.", 14, MUTED, 400))
    else:
        for index, item in enumerate(feed):
            y = row_y + index * row_h
            if index % 2 == 0:
                parts.append(f'<rect x="{list_x + 14}" y="{y}" width="{list_w - 28}" height="58" rx="10" fill="#151d29"/>')
            category_color = {
                "prs": PURPLE,
                "pushes": GREEN,
                "issues": GOLD,
                "reviews": ORANGE,
                "other": BLUE,
            }.get(item["category"], BLUE)
            parts.append(f'<circle cx="{list_x + 43}" cy="{y + 29}" r="16" fill="{category_color}" fill-opacity="0.16"/>')
            parts.append(
                f'<text x="{list_x + 43}" y="{y + 34}" text-anchor="middle" fill="{category_color}" '
                f'font-family="Inter,Segoe UI,Arial,sans-serif" font-size="17" font-weight="700">{html.escape(item["emoji"])}</text>'
            )
            parts.append(svg_text(list_x + 72, y + 26, truncate(item["label"], 72), 14, TEXT, 650))
            parts.append(svg_text(list_x + 72, y + 46, truncate(item["repo"], 54), 11, MUTED, 400))
            parts.append(f'<text x="{list_x + list_w - 24}" y="{y + 35}" text-anchor="end" fill="{MUTED}" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="11">{html.escape(item["date"])}</text>')

    # Weekly activity chart.
    chart_x, chart_y, chart_w, chart_h = 924, 446, 492, 500
    parts.extend([
        f'<rect x="{chart_x}" y="{chart_y}" width="{chart_w}" height="{chart_h}" rx="18" fill="{PANEL}" stroke="{BORDER}"/>',
        svg_text(chart_x + 22, chart_y + 42, "ACTIVITY TIMELINE", 17, TEXT, 700),
        svg_text(chart_x + 22, chart_y + 66, "Public events by week · last six weeks", 12, MUTED, 400),
    ])

    plot_left, plot_top, plot_w, plot_h = chart_x + 58, chart_y + 126, 382, 258
    plot_bottom = plot_top + plot_h
    weekly = stats["weekly"]
    series = [
        ("Pull requests", weekly["prs"], PURPLE),
        ("Code pushes", weekly["pushes"], GREEN),
        ("Issues & reviews", weekly["issues"], GOLD),
    ]
    max_value = max([v for _, values, _ in series for v in values] + [1])
    scale_top = max(4, max_value + 1)
    for tick in range(5):
        value = scale_top * (4 - tick) / 4
        y = plot_top + tick * (plot_h / 4)
        parts.append(f'<line x1="{plot_left}" y1="{y:.1f}" x2="{plot_left + plot_w}" y2="{y:.1f}" stroke="#283344" stroke-dasharray="4 6"/>')
        parts.append(f'<text x="{plot_left - 12}" y="{y + 4:.1f}" text-anchor="end" fill="{MUTED}" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="10">{round(value)}</text>')

    for index, label in enumerate(weekly["labels"]):
        x = plot_left + index * (plot_w / 5)
        parts.append(f'<text x="{x:.1f}" y="{plot_bottom + 25}" text-anchor="middle" fill="{MUTED}" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="10">{html.escape(label)}</text>')

    for label, values, color in series:
        points = []
        for index, value in enumerate(values):
            x = plot_left + index * (plot_w / 5)
            y = plot_bottom - (value / scale_top) * plot_h
            points.append((x, y))
        point_string = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        parts.append(f'<polyline points="{point_string}" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
        for x, y in points:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{color}" stroke="{PANEL}" stroke-width="2"/>')

    legend_y = chart_y + 448
    legend_x = chart_x + 26
    for label, _, color in series:
        parts.append(f'<circle cx="{legend_x}" cy="{legend_y - 4}" r="5" fill="{color}"/>')
        parts.append(svg_text(legend_x + 12, legend_y, label, 10, MUTED, 500))
        legend_x += 145 if label != "Issues & reviews" else 0

    parts.append(svg_text(32, 970, "SOURCE: GITHUB PUBLIC EVENTS API  ·  RECENT WINDOW (UP TO 300 EVENTS / 30 DAYS)", 10, MUTED, 500))
    parts.append(svg_text(1400, 970, "SAYAK MONDAL  /  OPEN SOURCE", 10, MUTED, 600))
    parts.append("</svg>")
    return "\n".join(parts)


def render_html_feed(events: list[dict]) -> str:
    rows = []
    seen = set()
    for event in events:
        if event.get("public") is False:
            continue
        item = describe_event(event)
        if not item or item["id"] in seen:
            continue
        seen.add(item["id"])
        rows.append(item["html"])
        if len(rows) >= EVENT_LIMIT:
            break

    if not rows:
        rows.append(
            '<tr><td align="center"><sub>No recent public development events found. '
            'New public activity will appear here when GitHub reports it.</sub></td></tr>'
        )

    return (
        '<p align="center"><img src="./assets/open-source-activity.svg" '
        'alt="Open Source Activity dashboard" width="100%"/></p>\n'
        '<details>\n<summary><strong>View clickable recent activity</strong></summary>\n\n'
        '<table>\n<tbody>\n' + "\n".join(rows) + '\n</tbody>\n</table>\n</details>'
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
        stats = aggregate(events)
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(render_svg(events, stats), encoding="utf-8")
        update_readme(render_html_feed(events))
        print(
            f"Updated dashboard for @{USERNAME}: {stats['public_events']} public events, "
            f"{stats['prs']} PRs, {stats['issues']} issues and {stats['reviews']} reviews."
        )
        return 0
    except Exception as error:
        print(f"Activity dashboard update failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
