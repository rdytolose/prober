#!/usr/bin/env python3
"""Split a huge links file into batches and submit them as separate jobs.

Each batch becomes its own job, so the coordinator can hand them out to many
probers in parallel and the dashboard shows progress per batch.

Usage:
    python scripts/split_and_submit.py \
        --coordinator https://host --token <admin> \
        --links-file big.txt --batch-size 500 \
        --urls https://google.com https://cloudflare.com \
        --label weekly-check
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request


def _post(url: str, token: str, body: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coordinator", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--links-file", required=True)
    ap.add_argument("--urls", nargs="*", default=[])
    ap.add_argument("--label", default="")
    ap.add_argument("--batch-size", type=int, default=500)
    args = ap.parse_args()

    with open(args.links_file, encoding="utf-8") as f:
        links = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    if not links:
        print("no links found", file=sys.stderr)
        return 2

    base = args.coordinator.rstrip("/")
    total = len(links)
    batch = max(1, args.batch_size)
    submitted = 0
    for i in range(0, total, batch):
        chunk = links[i : i + batch]
        label = f"{args.label or 'batch'} {i // batch + 1}/{(total + batch - 1) // batch}".strip()
        resp = _post(
            f"{base}/api/v1/jobs",
            args.token,
            {"links": chunk, "test_urls": args.urls, "label": label},
        )
        submitted += 1
        print(f"[{submitted}] {label}: {len(chunk)} links → job {resp['id']}")
    print(f"done: submitted {submitted} jobs covering {total} links")
    return 0


if __name__ == "__main__":
    sys.exit(main())
