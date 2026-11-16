#!/usr/bin/env python3
"""Aggregate Clanker's public token feed into leaderboard.json for MugentClank.

Fetches the newest 500 tokens from clanker.world/api/tokens, groups them by
creator (admin), scores each creator, and writes leaderboard.json next to the
repo root. Run by .github/workflows/leaderboard.yml every 5 minutes; the page
(index.html) fetches leaderboard.json same-origin.
"""
import json
import math
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

API = "https://www.clanker.world/api/tokens?limit=20"
PAGES = 25
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def fetch(url):
    last = None
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001 - retry then surface
            last = e
            time.sleep(2)
    raise last


def x_handle(tok):
    urls = []
    for link in tok.get("socialLinks") or []:
        if isinstance(link, dict) and link.get("url"):
            urls.append(link["url"])
    meta = tok.get("metadata") or {}
    for u in meta.get("socialMediaUrls") or []:
        if isinstance(u, str):
            urls.append(u)
    for u in urls:
        m = re.match(r"^https?://(www\.)?x\.com/([A-Za-z0-9_]{1,30})/?$", u or "")
        if m:
            return "@" + m.group(2)
    return None


def score(c):
    s = (40 * min(1.0, math.log10(c["vol24h"] + 1) / 5)
         + 30 * min(1.0, math.log10(c["bestMcap"] + 1) / 6)
         + 15 * min(1.0, math.log10(c["holders"] + 1) / 3)
         + min(c["launches"] * 2, 10)
         + (5 if c["verified"] else 0))
    return min(100, round(s))


def main():
    tokens = []
    cursor = None
    for _ in range(PAGES):
        url = API + (("&cursor=" + cursor) if cursor else "")
        page = fetch(url)
        data = page.get("data") or []
        tokens.extend(data)
        cursor = page.get("cursor")
        if not cursor or not data:
            break

    creators = {}
    for t in tokens:
        admin = (t.get("admin") or "").lower()
        if not admin:
            continue
        mkt = t.get("related", {}).get("market", {}) or {}
        c = creators.setdefault(admin, {
            "address": admin, "handle": None, "launches": 0, "vol24h": 0.0,
            "bestMcap": 0.0, "bestSymbol": "", "bestName": "", "bestToken": "",
            "holders": 0, "verified": False,
        })
        c["launches"] += 1
        c["vol24h"] += float(mkt.get("volume24h") or 0)
        mc = float(mkt.get("marketCap") or 0)
        if mc > c["bestMcap"]:
            c["bestMcap"] = mc
            c["bestSymbol"] = t.get("symbol") or ""
            c["bestName"] = t.get("name") or ""
            c["bestToken"] = t.get("contract_address") or ""
            c["holders"] = int(mkt.get("holders") or 0)
        if (t.get("tags") or {}).get("verified"):
            c["verified"] = True
        if not c["handle"]:
            c["handle"] = x_handle(t)

    ranked = []
    for c in creators.values():
        c["vol24h"] = round(c["vol24h"], 2)
        c["bestMcap"] = round(c["bestMcap"], 2)
        c["score"] = score(c)
        c["status"] = ("Trusted" if c["score"] >= 55
                       else "Builder" if c["score"] >= 28 else "Risky")
        ranked.append(c)
    ranked.sort(key=lambda c: -c["score"])

    latest = [{
        "name": t.get("name") or "", "symbol": t.get("symbol") or "",
        "token": t.get("contract_address") or "",
        "img": t.get("img_url") or "",
        "marketCap": float((t.get("related", {}).get("market", {}) or {})
                           .get("marketCap") or 0),
        "vol24h": float((t.get("related", {}).get("market", {}) or {})
                        .get("volume24h") or 0),
        "createdAt": t.get("created_at") or "",
    } for t in tokens[:12]]

    out = {
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scanned": len(tokens),
        "creatorsIndexed": len(creators),
        "creators": ranked[:50],
        "latest": latest,
    }
    with open("leaderboard.json", "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print("wrote leaderboard.json:", out["scanned"], "tokens,",
          out["creatorsIndexed"], "creators")
    return 0


if __name__ == "__main__":
    sys.exit(main())
