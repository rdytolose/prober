#!/usr/bin/env python3
"""Watch a job in your terminal with a live progress bar.

Usage:
    python scripts/watch_job.py --coordinator https://host --token <admin> --job-id <id>
    # or submit + watch in one shot:
    python scripts/watch_job.py --coordinator https://host --token <admin> \
        --links-file links.txt --urls https://google.com https://cloudflare.com
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request


def _get(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(url: str, token: str, body: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _bar(done: int, total: int, width: int = 40) -> str:
    if total <= 0:
        return "[" + " " * width + "]"
    n = int(width * done / total)
    return "[" + "█" * n + "·" * (width - n) + "]"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coordinator", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--job-id", default=None, help="watch an existing job; if omitted, submit a new one")
    ap.add_argument("--links-file", default=None)
    ap.add_argument("--urls", nargs="*", default=[])
    ap.add_argument("--label", default=None)
    ap.add_argument("--interval", type=float, default=2.0)
    args = ap.parse_args()

    base = args.coordinator.rstrip("/")
    job_id = args.job_id

    if job_id is None:
        if not args.links_file:
            print("either --job-id or --links-file is required", file=sys.stderr)
            return 2
        with open(args.links_file, encoding="utf-8") as f:
            links = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        if not links:
            print("links file is empty", file=sys.stderr)
            return 2
        resp = _post(f"{base}/api/v1/jobs", args.token,
                     {"links": links, "test_urls": args.urls, "label": args.label})
        job_id = resp["id"]
        print(f"submitted job {job_id} with {len(links)} links")

    started = time.monotonic()
    last_done = -1
    while True:
        try:
            data = _get(f"{base}/api/v1/jobs/{job_id}", args.token)
        except Exception as exc:
            print(f"\nerror: {exc}", file=sys.stderr)
            time.sleep(args.interval)
            continue
        done = data.get("done", 0)
        total = data.get("total", 0)
        ok = data.get("ok", 0)
        fail = data.get("fail", 0)
        status = data.get("status", "?")
        pct = data.get("percent", 0.0)
        rate = done / max(time.monotonic() - started, 0.001)
        eta = (total - done) / rate if rate > 0 else 0
        if done != last_done or status in ("done", "failed", "cancelled"):
            sys.stdout.write(
                "\r" + _bar(done, total) +
                f" {done:>6}/{total:<6} {pct:5.1f}%  "
                f"ok={ok}  fail={fail}  {rate:.2f}/s  eta={int(eta)}s  status={status}     "
            )
            sys.stdout.flush()
            last_done = done
        if status in ("done", "failed", "cancelled"):
            print()
            print(f"final: status={status}, ok={ok}, fail={fail}, total={total}")
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
