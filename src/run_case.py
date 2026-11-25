#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evaluator entrypoint: /input/case.json -> /app/output/result.json.

The task runtime contract hands this skill an input directory and collects a
result file. This adapter bridges that contract to pdf_parse.extract():

    python3 src/run_case.py                 # container defaults
    python3 src/run_case.py --case X.json --out DIR

It reads the real input files, never assumes source content from labels, and
records what it could not determine instead of guessing.
"""

import argparse
import glob
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pdf_parse  # noqa: E402

SKILL_NAME = "pdf-order"
SKILL_VERSION = "0.1.0"

# Names an output_contract field may plausibly use for the things we do produce.
FIELD_ALIASES = {
    "text": "text",
    "full_text": "text",
    "plain_text": "text",
    "markdown": "text",
    "content": "text",
    "pages": "pages",
    "blocks": "blocks",
    "reading_order": "reading_order",
    "layout": "layout",
    "evidence": "evidence",
    "status": "status",
    "confidence": "confidence",
}


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def default_out_dir() -> str:
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


def collect_pdf_paths(obj, base_dir):
    """Every string in the case file that points at a PDF, resolved on disk."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str):
            if node.lower().endswith(".pdf"):
                found.append(node)

    walk(obj)
    resolved = []
    for raw in found:
        candidates = [raw]
        if not os.path.isabs(raw):
            candidates.append(os.path.join(base_dir, raw))
            candidates.append(os.path.join(base_dir, os.path.basename(raw)))
        for c in candidates:
            if os.path.isfile(c):
                if os.path.abspath(c) not in resolved:
                    resolved.append(os.path.abspath(c))
                break
    return resolved


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]


def build_evidence(documents, limit=40):
    """Page + bbox anchors a reviewer can check against the original."""
    out = []
    for doc in documents:
        for page in doc.get("pages", []):
            for block in page.get("blocks", []):
                out.append(
                    {
                        "doc": doc.get("input_id"),
                        "page": page.get("page"),
                        "bbox": block.get("bbox"),
                        "text_sha1_16": sha1(block.get("text", "")),
                        "preview": (block.get("text") or "")[:80],
                    }
                )
                if len(out) >= limit:
                    return out
    return out


def apply_contract(result, contract):
    """Fill the keys the case's output_contract asks for, honestly."""
    if not contract:
        return []
    keys = list(contract.keys()) if isinstance(contract, dict) else list(contract)
    unresolved = []
    lookup = {
        "text": result.get("text"),
        "pages": [p for d in result["documents"] for p in d.get("pages", [])],
        "blocks": [b for d in result["documents"] for p in d.get("pages", []) for b in p.get("blocks", [])],
        "reading_order": [
            {"page": p.get("page"), "order": i}
            for d in result["documents"]
            for p in d.get("pages", [])
            for i, _ in enumerate(p.get("blocks", []))
        ],
        "layout": [{"page": p.get("page"), **p.get("layout", {})} for d in result["documents"] for p in d.get("pages", [])],
        "evidence": result.get("evidence"),
        "status": result.get("status"),
        "confidence": None,
    }
    if not lookup["pages"]:
        lookup["pages"] = None
    for key in keys:
        target = FIELD_ALIASES.get(str(key).lower())
        if target and lookup.get(target) is not None:
            result[str(key)] = lookup[target]
        else:
            result[str(key)] = None
            unresolved.append(str(key))
    return unresolved


def main(argv=None):
    ap = argparse.ArgumentParser(prog="run_case")
    ap.add_argument("--case", default=None, help="path to case.json")
    ap.add_argument("--out", default=None, help="output directory")
    ap.add_argument("--max-pages", type=int, default=None)
    args = ap.parse_args(argv)

    started = time.time()
    out_dir = args.out or default_out_dir()
    os.makedirs(out_dir, exist_ok=True)

    case_path = find_case(args.case)
    result = {
        "skill": {"name": SKILL_NAME, "version": SKILL_VERSION},
        "generated_at": iso_now(),
        "case_id": None,
        "status": "failed",
        "documents": [],
        "evidence": [],
        "warnings": [],
        "uncertainty": [],
    }

    if not case_path or not os.path.exists(case_path):
        result["warnings"].append("case.json not found; looked at /input/case.json and ./input/case.json")
        result["uncertainty"].append("no input case to process")
        write_result(out_dir, result)
        return 1

    base_dir = os.path.dirname(os.path.abspath(case_path))
    try:
        with open(case_path, encoding="utf-8") as fh:
            case = json.load(fh)
    except Exception as exc:
        result["warnings"].append("case.json unreadable: %s: %s" % (type(exc).__name__, exc))
        result["uncertainty"].append("could not parse the case file")
        write_result(out_dir, result)
        return 1

    if isinstance(case, dict):
        result["case_id"] = case.get("case_id") or case.get("id") or case.get("caseId")

    pdfs = collect_pdf_paths(case, base_dir)
    if not pdfs:
        # last resort: any PDF sitting next to the case file
        pdfs = sorted(glob.glob(os.path.join(base_dir, "*.pdf")))
    if not pdfs:
        result["warnings"].append("no PDF referenced by case.json and none found beside it")
        result["uncertainty"].append("no readable PDF input")
        write_result(out_dir, result)
        return 1

    all_text = []
    statuses = []
    for path in pdfs:
        doc = pdf_parse.extract(path, args.max_pages)
        result["documents"].append(doc)
        statuses.append(doc.get("status"))
        if doc.get("text"):
            all_text.append(doc["text"])
        for w in doc.get("warnings") or []:
            result["warnings"].append("%s: %s" % (os.path.basename(path), w))
        for u in doc.get("uncertainty") or []:
            result["uncertainty"].append("%s: %s" % (os.path.basename(path), u))

        # keep an auditable per-document parse next to the result
        stem = os.path.splitext(os.path.basename(path))[0]
        with open(os.path.join(out_dir, "parse_%s.json" % stem), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)

    result["text"] = "\n".join(all_text)
    if any(s == "success" for s in statuses):
        result["status"] = "success" if all(s == "success" for s in statuses) else "partial"
    elif any(s == "partial" for s in statuses):
        result["status"] = "partial"
    else:
        result["status"] = "failed"

    result["evidence"] = build_evidence(result["documents"])

    contract = case.get("output_contract") if isinstance(case, dict) else None
    unresolved = apply_contract(result, contract)
    if unresolved:
        result["unresolved_contract_fields"] = unresolved
        result["uncertainty"].append(
            "output_contract 中以下字段无法由本 Skill 可靠生成，已置为 null：" + ", ".join(unresolved)
        )

    result["wall_time_s"] = round(time.time() - started, 3)
    write_result(out_dir, result)

    print(
        json.dumps(
            {
                "status": result["status"],
                "case_id": result["case_id"],
                "documents": len(result["documents"]),
                "chars": len(result["text"]),
                "out": os.path.join(out_dir, "result.json"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if result["status"] in ("success", "partial") else 1


def write_result(out_dir, result):
    path = os.path.join(out_dir, "result.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print("wrote %s" % path, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
