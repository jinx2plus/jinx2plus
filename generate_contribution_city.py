#!/usr/bin/env python3
"""Generate an isometric GitHub contribution city SVG.

Uses GitHub GraphQL contributionCalendar. No third-party Python packages.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import math
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

WIDTH, HEIGHT = 960, 620
BG, PANEL, GRID, ROAD = "#0d1117", "#161b22", "#21262d", "#30363d"
TEXT, MUTED, CYAN, GREEN = "#c9d1d9", "#7d8590", "#39d0ff", "#3fb950"
TILE_W, TILE_H = 20.0, 10.0
ORIGIN_X, ORIGIN_Y = 165.0, 210.0
H_MIN, H_MAX = 8.0, 118.0
ROOFS = ["#12325a", "#15558a", "#1f7fb8", "#2fb7dd", "#5ce1ff"]
LEFTS = ["#0e223b", "#103b5c", "#155678", "#197999", "#239db8"]
RIGHTS = ["#0a182c", "#0d2b48", "#103f5f", "#145b77", "#1a7b91"]


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def graphql_calendar(username: str, token: str, days: int = 365) -> list[dict]:
    now = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(days=days - 1)
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            weeks {
              contributionDays {
                date
                contributionCount
                weekday
              }
            }
          }
        }
      }
    }
    """
    payload = json.dumps({
        "query": query,
        "variables": {
            "login": username,
            "from": start.isoformat(),
            "to": now.isoformat(),
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "contribution-city-generator",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    if body.get("errors"):
        raise RuntimeError("GitHub GraphQL error: " + json.dumps(body["errors"], ensure_ascii=False))
    user = body.get("data", {}).get("user")
    if not user:
        raise RuntimeError(f"GitHub user not found: {username}")

    result = []
    weeks = user["contributionsCollection"]["contributionCalendar"]["weeks"]
    for week_index, week in enumerate(weeks):
        for day in week["contributionDays"]:
            result.append({
                "date": day["date"],
                "count": int(day["contributionCount"]),
                "weekday": int(day["weekday"]),
                "week": week_index,
            })
    result.sort(key=lambda x: x["date"])
    return result[-days:]


def quantile_thresholds(counts: list[int]) -> list[int]:
    nonzero = sorted(c for c in counts if c > 0)
    if not nonzero:
        return [1, 1, 1, 1]

    def q(frac: float) -> int:
        idx = min(len(nonzero) - 1, int((len(nonzero) - 1) * frac))
        return nonzero[idx]

    return [q(0.20), q(0.45), q(0.70), q(0.90)]


def level_for(count: int, thresholds: list[int]) -> int:
    if count <= 0:
        return -1
    return sum(count > t for t in thresholds)


def poly(points: list[tuple[float, float]], **attrs: str) -> str:
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    attr = " ".join(f'{k.replace("_", "-")}="{esc(v)}"' for k, v in attrs.items())
    return f'<polygon points="{pts}" {attr}/>'


def building_svg(cx: float, cy: float, count: int, peak: int, level: int) -> str:
    left = (cx - TILE_W / 2, cy)
    right = (cx + TILE_W / 2, cy)
    top = (cx, cy - TILE_H / 2)
    bottom = (cx, cy + TILE_H / 2)

    if count <= 0:
        return poly([top, right, bottom, left], fill=PANEL, stroke=GRID, stroke_width="0.7")

    height = H_MIN + (H_MAX - H_MIN) * math.sqrt(count / max(peak, 1))
    top_u = (top[0], top[1] - height)
    right_u = (right[0], right[1] - height)
    bottom_u = (bottom[0], bottom[1] - height)
    left_u = (left[0], left[1] - height)

    parts = [
        poly([left, bottom, bottom_u, left_u], fill=LEFTS[level]),
        poly([bottom, right, right_u, bottom_u], fill=RIGHTS[level]),
        poly(
            [top_u, right_u, bottom_u, left_u],
            fill=ROOFS[level],
            stroke=CYAN if level >= 4 else ROOFS[level],
            stroke_width="0.65",
        ),
    ]

    floors = max(0, min(12, int((height - 8) // 9)))
    for floor in range(floors):
        yoff = 7 + floor * 9
        if (floor + count) % 3 == 0:
            continue
        for face, a, b, color in (
            ("l", left, bottom, "#7df9ff"),
            ("r", bottom, right, "#47c8ef"),
        ):
            for frac in (0.22, 0.62):
                if (floor * 7 + int(frac * 100) + count + (0 if face == "l" else 1)) % 4 == 0:
                    continue
                p1 = (a[0] + (b[0] - a[0]) * frac, a[1] + (b[1] - a[1]) * frac - yoff)
                p2 = (
                    a[0] + (b[0] - a[0]) * (frac + 0.21),
                    a[1] + (b[1] - a[1]) * (frac + 0.21) - yoff,
                )
                p3 = (p2[0], p2[1] - 3.0)
                p4 = (p1[0], p1[1] - 3.0)
                parts.append(poly([p1, p2, p3, p4], fill=color, opacity="0.78"))
    return "".join(parts)


def render(days: list[dict], username: str) -> str:
    if not days:
        raise RuntimeError("No contribution days were returned.")

    dates = [dt.date.fromisoformat(d["date"]) for d in days]
    first = min(dates)
    first_sunday = first - dt.timedelta(days=(first.weekday() + 1) % 7)

    normalized = []
    for item in days:
        date = dt.date.fromisoformat(item["date"])
        normalized.append({
            **item,
            "week": (date - first_sunday).days // 7,
            "weekday": (date.weekday() + 1) % 7,
        })

    counts = [d["count"] for d in normalized]
    total = sum(counts)
    active = sum(c > 0 for c in counts)
    peak = max(counts) if counts else 0
    peak_day = max(normalized, key=lambda d: d["count"])
    thresholds = quantile_thresholds(counts)

    ordered = sorted(normalized, key=lambda d: (d["week"] + d["weekday"], d["week"]))
    shapes = []
    for item in ordered:
        week, weekday, count = item["week"], item["weekday"], item["count"]
        cx = ORIGIN_X + (week - weekday) * TILE_W / 2
        cy = ORIGIN_Y + (week + weekday) * TILE_H / 2
        level = level_for(count, thresholds)
        shapes.append(
            f'<g><title>{esc(item["date"])}: {count} contributions</title>'
            + building_svg(cx, cy, count, peak, level)
            + "</g>"
        )

    roads = []
    for k in (10, 22, 34, 46):
        x1 = ORIGIN_X + k * TILE_W / 2
        y1 = ORIGIN_Y + k * TILE_H / 2 + 5
        x2 = ORIGIN_X + (k - 6) * TILE_W / 2
        y2 = ORIGIN_Y + (k + 6) * TILE_H / 2 + 5
        roads.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{ROAD}" stroke-width="1.2" stroke-dasharray="3 4" opacity="0.55"/>'
        )

    legend_x = 720
    legend = "".join(
        f'<rect x="{legend_x + i*24}" y="486" width="16" height="12" rx="2" fill="{color}"/>'
        for i, color in enumerate([PANEL] + ROOFS)
    )
    start_label = min(dates).strftime("%Y-%m-%d")
    end_label = max(dates).strftime("%Y-%m-%d")

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">
<title id="title">{esc(username)} Contribution City</title>
<desc id="desc">Isometric city generated from the last 365 days of GitHub contributions. One lot per day; taller buildings represent more contributions.</desc>
<defs>
  <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="#070b12"/>
    <stop offset="100%" stop-color="{BG}"/>
  </linearGradient>
  <filter id="glow" x="-100%" y="-100%" width="300%" height="300%">
    <feGaussianBlur stdDeviation="4" result="blur"/>
    <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <pattern id="microgrid" width="32" height="32" patternUnits="userSpaceOnUse">
    <path d="M32 0H0V32" fill="none" stroke="{CYAN}" stroke-opacity="0.035"/>
  </pattern>
  <style>
    text {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; }}
    .pulse {{ animation: pulse 3.4s ease-in-out infinite; }}
    @keyframes pulse {{ 0%,100% {{ opacity:.55 }} 50% {{ opacity:1 }} }}
    @media (prefers-reduced-motion: reduce) {{ .pulse {{ animation:none }} }}
  </style>
</defs>
<rect width="{WIDTH}" height="{HEIGHT}" rx="18" fill="url(#sky)"/>
<rect x="1" y="1" width="{WIDTH-2}" height="{HEIGHT-2}" rx="18" fill="none" stroke="{GRID}"/>
<rect width="{WIDTH}" height="{HEIGHT}" rx="18" fill="url(#microgrid)"/>

<text x="44" y="54" fill="{CYAN}" font-size="24" font-weight="700" filter="url(#glow)">YJP CONTRIBUTION CITY</text>
<text x="44" y="78" fill="{MUTED}" font-size="12">mobility data skyline · one building per contribution day</text>
<line x1="44" y1="94" x2="916" y2="94" stroke="{CYAN}" stroke-opacity=".24"/>
<line x1="44" y1="94" x2="250" y2="94" stroke="{CYAN}" stroke-width="2" stroke-opacity=".85"/>

<g opacity=".9">{''.join(roads)}</g>
<g>{''.join(shapes)}</g>

<g transform="translate(714 146)">
  <rect x="0" y="0" width="202" height="278" rx="12" fill="#0d1117" fill-opacity=".78" stroke="{GRID}"/>
  <text x="18" y="34" fill="{TEXT}" font-size="12">USER</text>
  <text x="18" y="57" fill="{CYAN}" font-size="19" font-weight="700">@{esc(username)}</text>
  <text x="18" y="94" fill="{MUTED}" font-size="11">CONTRIBUTIONS</text>
  <text x="18" y="124" fill="{TEXT}" font-size="29" font-weight="700">{total:,}</text>
  <text x="18" y="157" fill="{MUTED}" font-size="11">ACTIVE DAYS</text>
  <text x="18" y="180" fill="{GREEN}" font-size="18" font-weight="700">{active} / {len(normalized)}</text>
  <text x="18" y="211" fill="{MUTED}" font-size="11">BUSIEST DAY</text>
  <text x="18" y="234" fill="{TEXT}" font-size="13">{esc(peak_day["date"])}</text>
  <text x="18" y="255" fill="{CYAN}" font-size="15" font-weight="700">{peak} contributions</text>
</g>

<text x="44" y="548" fill="{MUTED}" font-size="11">{start_label} → {end_label}</text>
<text x="720" y="470" fill="{MUTED}" font-size="11">quiet</text>
{legend}
<text x="720" y="520" fill="{MUTED}" font-size="11">activity → skyline height</text>

<circle class="pulse" cx="900" cy="54" r="4" fill="{GREEN}"/>
<text x="888" y="58" fill="{MUTED}" font-size="10" text-anchor="end">AUTO UPDATED</text>
</svg>
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default=os.getenv("GITHUB_REPOSITORY_OWNER", "jinx2plus"))
    parser.add_argument("--token", default=os.getenv("CONTRIBUTION_TOKEN") or os.getenv("GITHUB_TOKEN"))
    parser.add_argument("--output", default="contribution-city.svg")
    args = parser.parse_args()

    if not args.token:
        print("error: CONTRIBUTION_TOKEN or GITHUB_TOKEN is required", file=sys.stderr)
        return 2
    try:
        days = graphql_calendar(args.username, args.token)
    except (urllib.error.URLError, RuntimeError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: failed to fetch contribution calendar: {exc}", file=sys.stderr)
        return 1

    Path(args.output).write_text(render(days, args.username), encoding="utf-8")
    print(f"wrote {args.output} with {len(days)} days")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
