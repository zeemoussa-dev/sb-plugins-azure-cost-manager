"""Growth and churn signals for one customer (operator, 2026-10-21): which
customers are growing, which are falling away, and what stopped or started.

Read from closed months only -- the current month is partial. Totals are the
measured figure the Overview uses (usage + Marketplace - credits); services and
solution plays are Cost Management's actual cost, as in Breakdown.
"""
from __future__ import annotations

from . import solution_plays

# A change this large either way over three months is a signal.
CHANGE_PCT = 20.0
# Below this, a service's coming or going is noise, not a signal.
MATERIAL = 1000.0
# Last month under this share of the three before it is a sharp drop.
SHARP_DROP_SHARE = 0.5
# A service now under this share of what it was has stopped.
STOPPED_SHARE = 0.1
LISTED = 5


def _pct(new: float, old: float) -> float | None:
    return round((new - old) / old * 100, 1) if old else None


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def analyse(trend: list[dict], merged: dict, plays: dict[str, str]) -> dict:
    closed = [row for row in trend if not row["partial"]]
    if not closed:
        return {"status": "no data", "signals": [], "last_month": None}
    last = closed[-1]
    recent, before = closed[-3:], closed[-6:-3]
    recent_avg, before_avg = _average([row["actual"] for row in recent]), _average([row["actual"] for row in before])
    last12, prior12 = closed[-12:], closed[-24:-12]
    year_ago = next((row for row in closed if row["month"] == f"{int(last['month'][:4]) - 1:04d}{last['month'][4:]}"), None)
    change_3m = _pct(recent_avg, before_avg) if len(before) == 3 else None
    change_12m = (_pct(sum(row["actual"] for row in last12), sum(row["actual"] for row in prior12))
                  if len(prior12) == 12 else None)

    signals: list[dict] = []
    if change_3m is not None and change_3m >= CHANGE_PCT:
        signals.append({"kind": "growing", "text": f"Up {change_3m}% over three months"})
    if change_3m is not None and change_3m <= -CHANGE_PCT:
        signals.append({"kind": "declining", "text": f"Down {abs(change_3m)}% over three months"})
    previous3 = closed[-4:-1]
    previous_avg = _average([row["actual"] for row in previous3])
    if len(previous3) == 3 and previous_avg >= MATERIAL and last["actual"] < previous_avg * SHARP_DROP_SHARE:
        signals.append({"kind": "drop", "text": f"Last month at {round(last['actual'] / previous_avg * 100)}% "
                                                f"of the three months before"})

    def services_of(month: str) -> dict[str, float]:
        return ((merged.get(month) or {}).get("actual") or {}).get("service") or {}

    last_services = services_of(last["month"])
    earlier = [services_of(row["month"]) for row in previous3]
    earlier_avg = {name: _average([month.get(name, 0.0) for month in earlier])
                   for name in {name for month in earlier for name in month}}
    stopped = sorted(({"service": name, "before": round(avg, 2), "last": round(last_services.get(name, 0.0), 2)}
                      for name, avg in earlier_avg.items()
                      if avg >= MATERIAL and last_services.get(name, 0.0) < avg * STOPPED_SHARE),
                     key=lambda row: -row["before"])
    started = sorted(({"service": name, "last": round(cost, 2)} for name, cost in last_services.items()
                      if cost >= MATERIAL and not any(month.get(name) for month in earlier)),
                     key=lambda row: -row["last"])
    if stopped:
        signals.append({"kind": "stopped", "text": f"{len(stopped)} service(s) stopped: "
                                                   + ", ".join(row["service"] for row in stopped[:3])})
    if started:
        signals.append({"kind": "new", "text": f"{len(started)} new service(s): "
                                               + ", ".join(row["service"] for row in started[:3])})

    def plays_of(rows: list[dict]) -> dict[str, float]:
        totals: dict[str, float] = {}
        for row in rows:
            month = merged.get(row["month"]) or {}
            for play, cost in solution_plays.split(services_of(row["month"]), month.get("meters"), plays,
                                                   (month.get("measured") or {}).get("marketplace")).items():
                totals[play] = totals.get(play, 0.0) + cost / len(rows)
        return totals

    recent_plays, before_plays = plays_of(recent), plays_of(before) if len(before) == 3 else {}
    by_play = sorted(({"play": play, "recent": round(recent_plays.get(play, 0.0), 2),
                       "before": round(before_plays.get(play, 0.0), 2),
                       "change": round(recent_plays.get(play, 0.0) - before_plays.get(play, 0.0), 2),
                       "change_pct": _pct(recent_plays.get(play, 0.0), before_plays.get(play, 0.0))}
                      for play in set(recent_plays) | set(before_plays)), key=lambda row: -abs(row["change"]))

    status = ("new" if len(closed) < 6 else "growing" if change_3m is not None and change_3m >= CHANGE_PCT
              else "declining" if change_3m is not None and change_3m <= -CHANGE_PCT else "steady")
    return {
        "status": status,
        "last_month": last["month"],
        "last_total": last["actual"],
        "recent_monthly": round(recent_avg, 2),
        "before_monthly": round(before_avg, 2) if len(before) == 3 else None,
        "change_3m_pct": change_3m,
        "change_12m_pct": change_12m,
        "yoy_pct": _pct(last["actual"], year_ago["actual"]) if year_ago else None,
        "signals": signals,
        "stopped": stopped[:LISTED],
        "started": started[:LISTED],
        "by_play": by_play,
    }
