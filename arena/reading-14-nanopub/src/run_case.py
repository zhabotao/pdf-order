#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generic runtime adapter for every arena submission.

The task-specific work lives in ``task.run(ctx)``. This file only handles the
runtime contract: locate /input/case.json, classify the real input files, call
the task, and write /app/output/result.json with case_id, status, evidence,
sources and uncertainty.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "core"))

import textops

try:
    import task  # provided by each package
except ImportError:  # pragma: no cover
    task = None


def iso_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def default_out_dir():
    if os.path.isdir("/app"):
        return "/app/output"
    return os.path.join(os.getcwd(), "app", "output")


def find_case(explicit):
    if explicit:
        return explicit
    for p in ("/input/case.json", os.path.join("input", "case.json"), "case.json"):
        if os.path.exists(p):
            return p
    return None


def walk_strings(node, out):
    if isinstance(node, dict):
        for v in node.values():
            walk_strings(v, out)
    elif isinstance(node, list):
        for v in node:
            walk_strings(v, out)
    elif isinstance(node, str):
        out.append(node)


def collect_inputs(case, base_dir):
    """Classify real files referenced by the case; never assume from labels."""
    raw = []
    walk_strings(case, raw)
    bucket = {"pdf": [], "tex": [], "bib": [], "text": [], "other": []}
    seen = set()
    for item in raw:
        low = item.lower()
        if not low.endswith((".pdf", ".tex", ".bib", ".md", ".txt", ".json", ".docx", ".csv")):
            continue
        candidates = [item]
        if not os.path.isabs(item):
            candidates.append(os.path.join(base_dir, item))
            candidates.append(os.path.join(base_dir, os.path.basename(item)))
        for c in candidates:
            if os.path.isfile(c):
                ap = os.path.abspath(c)
                if ap in seen:
                    break
                seen.add(ap)
                ext = os.path.splitext(ap)[1].lower().lstrip(".")
                key = {"pdf": "pdf", "tex": "tex", "bib": "bib", "md": "text", "txt": "text",
                       "json": "text", "csv": "text", "docx": "other"}.get(ext, "other")
                bucket[key].append(ap)
                break
    # last resort: sibling files next to the case
    if not any(bucket.values()):
        for pat, key in (("*.pdf", "pdf"), ("*.tex", "tex"), ("*.bib", "bib"), ("*.md", "text"), ("*.txt", "text")):
            bucket[key].extend(sorted(glob.glob(os.path.join(base_dir, pat))))
    return bucket


FIELD_ALIASES = {
    "text": "text", "full_text": "text", "markdown": "text", "content": "text",
    "translation": "translation", "bilingual": "bilingual",
    "notes": "notes", "summary": "summary", "glossary": "glossary",
    "triples": "triples", "entities": "entities", "relations": "relations",
    "references": "references", "issues": "issues", "patches": "patches",
    "nanopublication": "nanopublication", "claims": "claims",
    "evidence": "evidence", "status": "status", "sections": "sections",
}


def apply_contract(result, contract):
    if not contract:
        return []
    keys = contract.keys() if isinstance(contract, dict) else contract
    unresolved = []
    for key in keys:
        target = FIELD_ALIASES.get(str(key).lower())
        if target and result.get(target) not in (None, "", [], {}):
            result[str(key)] = result[target]
        else:
            result[str(key)] = None
            unresolved.append(str(key))
    return unresolved


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-pages", type=int, default=None)
    args = ap.parse_args(argv)

    started = time.time()
    out_dir = args.out or default_out_dir()
    os.makedirs(out_dir, exist_ok=True)

    result = {
        "skill": {"name": None, "version": "0.1.0"},
        "generated_at": iso_now(),
        "case_id": None,
        "status": "failed",
        "results": {},
        "evidence": [],
        "sources": [],
        "warnings": [],
        "uncertainty": [],
    }

    case_path = find_case(args.case)
    if not case_path or not os.path.exists(case_path):
        result["warnings"].append("case.json not found; looked at /input/case.json and ./input/case.json")
        result["uncertainty"].append("no input case to process")
        return finish(out_dir, result, started)

    base_dir = os.path.dirname(os.path.abspath(case_path))
    try:
        with open(case_path, encoding="utf-8") as fh:
            case = json.load(fh)
    except Exception as exc:
        result["warnings"].append("case.json unreadable: %s: %s" % (type(exc).__name__, exc))
        result["uncertainty"].append("could not parse the case file")
        return finish(out_dir, result, started)

    if isinstance(case, dict):
        result["case_id"] = case.get("case_id") or case.get("id") or case.get("caseId")

    inputs = collect_inputs(case, base_dir)
    result["sources"] = [
        {"kind": k, "path": os.path.basename(p), "bytes": os.path.getsize(p)}
        for k, paths in inputs.items() for p in paths
    ]

    if not any(inputs.values()):
        result["warnings"].append("case.json references no readable file, and none sit beside it")
        result["uncertainty"].append("no input material found")
        return finish(out_dir, result, started)

    if task is None:
        result["warnings"].append("task module missing")
        return finish(out_dir, result, started)

    ctx = {
        "case": case,
        "case_id": result["case_id"],
        "inputs": inputs,
        "base_dir": base_dir,
        "workdir": out_dir,
        "max_pages": args.max_pages,
        "result": result,
    }
    try:
        payload = task.run(ctx)
    except Exception as exc:
        result["warnings"].append("task raised %s: %s" % (type(exc).__name__, exc))
        result["uncertainty"].append("the task aborted; no partial answer is presented as final")
        return finish(out_dir, result, started)

    if isinstance(payload, dict):
        name = payload.pop("skill_name", None)
        if name:
            result["skill"]["name"] = name
        status = payload.pop("status", "success")
        result.update({k: v for k, v in payload.items() if v is not None})
        result["status"] = status

    contract = case.get("output_contract") if isinstance(case, dict) else None
    unresolved = apply_contract(result, contract)
    if unresolved:
        result["unresolved_contract_fields"] = unresolved
        result["uncertainty"].append(
            "output_contract 中以下字段无法由本 Skill 可靠生成，已置为 null：" + ", ".join(unresolved)
        )

    return finish(out_dir, result, started)


def finish(out_dir, result, started):
    result["wall_time_s"] = round(time.time() - started, 3)
    path = os.path.join(out_dir, "result.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(json.dumps({
        "status": result["status"],
        "case_id": result["case_id"],
        "skill": result["skill"].get("name"),
        "out": path,
    }, ensure_ascii=False))
    return 0 if result["status"] in ("success", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(main())
