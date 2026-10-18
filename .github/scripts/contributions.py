"""Render the profile's contribution calendar as two monochrome SVGs (light and dark).

Runs daily from .github/workflows/contributions.yml. With GITHUB_TOKEN set it reads the
GraphQL API; without it (local preview) it reads the public contributions page instead.
Both sources include private contributions when the profile is set to show them.
"""

import datetime as dt
import json
import os
import re
import urllib.request
from pathlib import Path

USER = os.environ.get("GH_USER", "Spidey507")
TOKEN = os.environ.get("GITHUB_TOKEN")
OUT = Path(__file__).resolve().parents[2] / "assets"

LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}

THEMES = {
    "light": {
        "text": "#111111", "muted": "#6e6e6e", "rule": "#d0d0d0",
        "cells": ["#ebebeb", "#c6c6c6", "#8e8e8e", "#4a4a4a", "#111111"],
    },
    "dark": {
        "text": "#f0f0f0", "muted": "#8b8b8b", "rule": "#30363d",
        "cells": ["#1c1f24", "#3d3d3d", "#6e6e6e", "#a9a9a9", "#f0f0f0"],
    },
}


def http(url, data=None):
    headers = {"User-Agent": f"{USER}-profile"}
    if data is not None:
        headers["Authorization"] = f"bearer {TOKEN}"
        headers["Content-Type"] = "application/json"
        data = json.dumps(data).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data, headers), timeout=30) as r:
        return r.read().decode()


# ---- data sources: each returns (all_days, last_year_days); a day is (date, count, level)

def from_graphql():
    def gql(query):
        body = json.loads(http("https://api.github.com/graphql", {"query": query}))
        if body.get("errors"):
            raise RuntimeError(body["errors"])
        return body["data"]["user"]

    cal = "contributionCalendar { weeks { contributionDays { date contributionCount contributionLevel } } }"

    def days(collection):
        return [
            (dt.date.fromisoformat(d["date"]), d["contributionCount"], LEVELS[d["contributionLevel"]])
            for w in collection["contributionCalendar"]["weeks"] for d in w["contributionDays"]
        ]

    user = gql(f'{{ user(login: "{USER}") {{ contributionsCollection {{ contributionYears {cal} }} }} }}')
    last_year = days(user["contributionsCollection"])
    years = user["contributionsCollection"]["contributionYears"]
    aliases = " ".join(
        f'y{y}: contributionsCollection(from: "{y}-01-01T00:00:00Z", to: "{y}-12-31T23:59:59Z") {{ {cal} }}'
        for y in years
    )
    per_year = gql(f'{{ user(login: "{USER}") {{ {aliases} }} }}')
    all_days = [d for y in years for d in days(per_year[f"y{y}"])]
    return all_days, last_year


def from_html():
    def page(query=""):
        html = http(f"https://github.com/users/{USER}/contributions{query}")
        counts = {}
        for m in re.finditer(r'for="(contribution-day-component-[\d-]+)"[^>]*>([^<]*)</tool-tip>', html):
            n = re.match(r"([\d,]+) contribution", m.group(2))
            counts[m.group(1)] = int(n.group(1).replace(",", "")) if n else 0
        out = []
        for m in re.finditer(r"<td[^>]*ContributionCalendar-day[^>]*>", html):
            td = m.group(0)
            date = re.search(r'data-date="([\d-]+)"', td).group(1)
            cid = re.search(r'id="([^"]+)"', td).group(1)
            level = int(re.search(r'data-level="(\d)"', td).group(1))
            out.append((dt.date.fromisoformat(date), counts.get(cid, 0), level))
        return sorted(out)

    created = json.loads(http(f"https://api.github.com/users/{USER}"))["created_at"][:4]
    today = dt.date.today()
    all_days = [d for y in range(int(created), today.year + 1) for d in page(f"?from={y}-01-01&to={y}-12-31")]
    return all_days, page()


# ---- stats

def streaks(days):
    days = sorted({d[0]: d for d in days if d[0] <= dt.date.today()}.values())
    longest = run = 0
    for _, count, _ in days:
        run = run + 1 if count else 0
        longest = max(longest, run)
    current = 0
    tail = days[:-1] if days and days[-1][1] == 0 else days  # today may still be empty
    for _, count, _ in reversed(tail):
        if not count:
            break
        current += 1
    return current, longest


# ---- render

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;")


def render(theme, all_days, last_year):
    t = THEMES[theme]
    sans = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
    mono = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

    total = sum(c for _, c, _ in all_days)
    year_total = sum(c for _, c, _ in last_year)
    current, longest = streaks(all_days)
    since = min(d for d, c, _ in all_days if c).year if total else dt.date.today().year

    cell, gap, left, top = 12, 3, 34, 118
    start = last_year[0][0]
    start -= dt.timedelta(days=(start.weekday() + 1) % 7)  # align to Sunday
    weeks = (last_year[-1][0] - start).days // 7 + 1
    grid_w = weeks * (cell + gap) - gap
    width = left + grid_w
    height = top + 7 * (cell + gap) - gap + 40

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">',
        f"<title>{total:,} contributions since {since}; {year_total:,} in the last twelve months</title>",
    ]

    stats = [
        (f"{total:,}", f"CONTRIBUTIONS SINCE {since}"),
        (f"{year_total:,}", "LAST 12 MONTHS"),
        (f"{current}", "CURRENT STREAK, DAYS"),
        (f"{longest}", "LONGEST STREAK, DAYS"),
    ]
    col = width / len(stats)
    for i, (value, label) in enumerate(stats):
        x = i * col + (0 if i == 0 else 16)
        if i:
            parts.append(f'<line x1="{i * col:.1f}" y1="0" x2="{i * col:.1f}" y2="62" stroke="{t["rule"]}" />')
        parts.append(f'<text x="{x:.1f}" y="34" font-family="{sans}" font-size="30" font-weight="600" letter-spacing="-0.5" fill="{t["text"]}">{value}</text>')
        parts.append(f'<text x="{x:.1f}" y="56" font-family="{mono}" font-size="10" letter-spacing="1" fill="{t["muted"]}">{label}</text>')
    parts.append(f'<line x1="0" y1="80" x2="{width}" y2="80" stroke="{t["text"]}" stroke-width="2" />')

    seen = set()
    for w in range(weeks):
        first = start + dt.timedelta(weeks=w)
        month = (first + dt.timedelta(days=6)).replace(day=1)
        if month not in seen and (first + dt.timedelta(days=6)).day <= 7 and w < weeks - 2:
            seen.add(month)
            parts.append(f'<text x="{left + w * (cell + gap)}" y="{top - 10}" font-family="{mono}" font-size="10" letter-spacing="1" fill="{t["muted"]}">{month.strftime("%b").upper()}</text>')
    for row, name in ((1, "MON"), (3, "WED"), (5, "FRI")):
        parts.append(f'<text x="0" y="{top + row * (cell + gap) + cell - 2}" font-family="{mono}" font-size="9" fill="{t["muted"]}">{name}</text>')

    for date, count, level in last_year:
        w, d = (date - start).days // 7, (date.weekday() + 1) % 7
        x, y = left + w * (cell + gap), top + d * (cell + gap)
        label = f"{count} contribution{'s' if count != 1 else ''} on {date:%Y-%m-%d}"
        parts.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="{t["cells"][level]}"><title>{esc(label)}</title></rect>')

    base = top + 7 * (cell + gap) + 22
    parts.append(f'<text x="0" y="{base}" font-family="{mono}" font-size="10" letter-spacing="1" fill="{t["muted"]}">UPDATED {dt.date.today():%Y-%m-%d} · INCLUDES PRIVATE WORK</text>')
    lx = width - 5 * (cell + gap) - 40
    parts.append(f'<text x="{lx - 8}" y="{base}" text-anchor="end" font-family="{mono}" font-size="10" letter-spacing="1" fill="{t["muted"]}">LESS</text>')
    for i, c in enumerate(t["cells"]):
        parts.append(f'<rect x="{lx + i * (cell + gap)}" y="{base - 10}" width="{cell}" height="{cell}" fill="{c}" />')
    parts.append(f'<text x="{width}" y="{base}" text-anchor="end" font-family="{mono}" font-size="10" letter-spacing="1" fill="{t["muted"]}">MORE</text>')

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main():
    all_days, last_year = from_graphql() if TOKEN else from_html()
    OUT.mkdir(exist_ok=True)
    for theme in THEMES:
        (OUT / f"contributions-{theme}.svg").write_text(render(theme, all_days, last_year), encoding="utf-8")
    print(f"{sum(c for _, c, _ in all_days):,} total, {sum(c for _, c, _ in last_year):,} last year, streaks {streaks(all_days)}")


if __name__ == "__main__":
    main()
