#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Entrypoint: parse the bundled demo PDF and write the result set.

Usage:
    python3 src/reproduce.py [--pdf PATH] [--out DIR]

Produces, under the output directory (default: results/):
    parse_sample.json  full structured parse
    summary.json       small numerical summary used as the run metric
    run.log            appended stdout capture for this run
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import pdf_parse  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default=os.path.join(ROOT, "demo", "sample.pdf"))
    ap.add_argument("--out", default=os.path.join(ROOT, "results"))
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    log_path = os.path.join(args.out, "run.log")

    def log(msg: str) -> None:
        line = "[%s] %s" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), msg)
        print(line)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    started = time.time()
    log("pdf-order reproduce: input=%s" % args.pdf)

    if not os.path.exists(args.pdf):
        log("FAILED: input missing")
        return 2

    result = pdf_parse.extract(args.pdf)
    log(
        "parsed: status=%s pages=%d chars=%d"
        % (result.get("status"), result.get("page_count", 0), result.get("text_char_count", 0))
    )

    out_json = os.path.join(args.out, "parse_sample.json")
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    log("wrote results/parse_sample.json")

    pages = result.get("pages") or []
    cols = [p.get("layout", {}).get("columns", 1) for p in pages]
    blocks = sum(len(p.get("blocks") or []) for p in pages)
    summary = {
        "input_id": result.get("input_id"),
        "status": result.get("status"),
        "pages": len(pages),
        "columns_per_page": cols,
        "block_count": blocks,
        "text_char_count": result.get("text_char_count", 0),
        "uncertainty_count": len(result.get("uncertainty") or []),
        "wall_time_s": round(time.time() - started, 3),
    }
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    log("wrote results/summary.json")

    print(json.dumps(summary, ensure_ascii=False))
    return 0 if result.get("status") in ("success", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(main())
