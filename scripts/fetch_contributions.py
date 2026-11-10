#!/usr/bin/env python3
"""
Scrape real daily contribution counts from GitHub's public, unauthenticated
contributions endpoint and merge with existing private-repo contribution counts
in data/contributions.json so both public and private repository commits are
preserved when refreshed daily by GitHub Actions.
"""
import datetime
import html
import json
import os
import re
import sys
import urllib.request

USERNAME = os.environ.get("GH_PROFILE_USER", "anhtrantuan2708-beep")
URL = f"https://github.com/users/{USERNAME}/contributions"
OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "contributions.json")


def load_existing_counts():
    counts = {}
    if os.path.exists(OUT_PATH):
        try:
            old = json.load(open(OUT_PATH))
            for d in old.get("days", []):
                if d.get("date") and d.get("count", 0) > 0:
                    counts[d["date"]] = d["count"]
        except Exception:
            pass
    seed_path = "/tmp/real_commit_days.json"
    if os.path.exists(seed_path):
        try:
            seed = json.load(open(seed_path))
            for dt, cnt in seed.items():
                counts[dt] = max(counts.get(dt, 0), int(cnt))
        except Exception:
            pass
    return counts


def fetch_days():
    existing = load_existing_counts()
    req = urllib.request.Request(URL, headers={"User-Agent": "profile-readme-bot/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    td_tags = re.findall(r"<td\b[^>]*ContributionCalendar-day[^>]*>", raw)
    if not td_tags:
        print("no calendar cells found -- github markup may have changed", file=sys.stderr)
        sys.exit(1)

    tooltips = {}
    for m in re.finditer(r'<tool-tip\b[^>]*\bfor="([^"]+)"[^>]*>(.*?)</tool-tip>', raw, re.S):
        tooltips[m.group(1)] = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()

    days = []
    for tag in td_tags:
        date_m = re.search(r'\bdata-date="([^"]+)"', tag)
        if not date_m:
            continue
        date = date_m.group(1)
        id_m = re.search(r'\bid="([^"]+)"', tag)
        lvl_m = re.search(r'\bdata-level="(\d+)"', tag)
        level = int(lvl_m.group(1)) if lvl_m else 0
        text = tooltips.get(id_m.group(1), "") if id_m else ""
        if re.search(r"no contributions", text, re.I):
            count = 0
        else:
            cm = re.match(r"(\d+)", text)
            count = int(cm.group(1)) if cm else (level * 2 if level > 0 else 0)
        count = max(count, existing.get(date, 0))
        if count > 0 and level == 0:
            level = 1 if count <= 2 else 2 if count <= 5 else 3 if count <= 10 else 4
        days.append({"date": date, "count": count, "level": level})

    days.sort(key=lambda d: d["date"])
    return days


def compute_current_streak(days):
    idx = len(days) - 1
    if idx >= 0 and days[idx]["count"] == 0:
        idx -= 1
    streak = 0
    end_idx = idx
    while idx >= 0 and days[idx]["count"] > 0:
        streak += 1
        idx -= 1
    start_idx = idx + 1
    if streak == 0:
        return 0, None, None
    return streak, days[start_idx]["date"], days[end_idx]["date"]


def compute_longest_streak(days):
    longest = run = 0
    longest_start = longest_end = None
    run_start_idx = None
    for i, d in enumerate(days):
        if d["count"] > 0:
            if run == 0:
                run_start_idx = i
            run += 1
            if run > longest:
                longest = run
                longest_start = days[run_start_idx]["date"]
                longest_end = days[i]["date"]
        else:
            run = 0
    return longest, longest_start, longest_end


def build_data(days):
    total = sum(d["count"] for d in days)
    active_days = sum(1 for d in days if d["count"] > 0)
    best = max(days, key=lambda d: d["count"])
    cur_len, cur_start, cur_end = compute_current_streak(days)
    long_len, long_start, long_end = compute_longest_streak(days)

    monthly = {}
    for d in days:
        key = d["date"][:7]
        monthly[key] = monthly.get(key, 0) + d["count"]
    monthly_list = [{"month": k, "total": v} for k, v in sorted(monthly.items())]

    return {
        "username": USERNAME,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "range": {"start": days[0]["date"], "end": days[-1]["date"]},
        "total_contributions": total,
        "active_days": active_days,
        "avg_per_active_day": round(total / active_days, 1) if active_days else 0,
        "current_streak": {"length": cur_len, "start": cur_start, "end": cur_end},
        "longest_streak": {"length": long_len, "start": long_start, "end": long_end},
        "best_day": {"date": best["date"], "count": best["count"]},
        "monthly": monthly_list,
        "days": days,
    }


if __name__ == "__main__":
    days = fetch_days()
    data = build_data(days)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(data, f, indent=2)
    print(f"wrote {OUT_PATH}: {data['total_contributions']} contributions, "
          f"active days {data['active_days']}, "
          f"current streak {data['current_streak']['length']}, "
          f"longest streak {data['longest_streak']['length']}")
