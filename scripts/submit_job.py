#!/usr/bin/env python3
"""Tiny CLI to submit a job to the coordinator.

Usage:
    python scripts/submit_job.py \
        --coordinator http://localhost:8080 \
        --token <admin-token> \
        --links-file links.txt \
        --urls https://google.com https://youtube.com
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coordinator", required=True, help="coordinator base URL")
    ap.add_argument("--token", required=True, help="admin token")
    ap.add_argument("--links-file", required=True, help="file with one connection URL per line")
    ap.add_argument("--urls", nargs="*", default=[], help="sites to test")
    ap.add_argument("--label", default=None, help="optional label")
    args = ap.parse_args()

    with open(args.links_file, encoding="utf-8") as f:
        links = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    body = json.dumps({"links": links, "test_urls": args.urls, "label": args.label}).encode("utf-8")
    req = urllib.request.Request(
        f"{args.coordinator.rstrip('/')}/api/v1/jobs",
        data=body,
        headers={"Authorization": f"Bearer {args.token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        print(resp.read().decode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
