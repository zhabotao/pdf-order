#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阅读14｜Nanopublication — pack claims into assertion / provenance / publication.

A nanopublication is only useful if its assertion is smaller than the paper and
its provenance is checkable. So: every assertion keeps a page + bbox anchor and
the sentence it came from, and each item carries an explicit confidence rather
than an implied one.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PKG, "core"))

import docmodel  # noqa: E402
import textops  # noqa: E402

SKILL = "reading-14-nanopub"

ASSERTION_CUES = re.compile(
    r"(we (?:show|propose|demonstrate|find|introduce|observe|argue)|"
    r"本文|我们(?:提出|证明|发现|表明)|实验(?:表明|结果)|results? (?:show|suggest|indicate))",
    re.I,
)
REL_PATTERNS = [
    (re.compile(r"\b(\w[\w\-]{2,})\s+(improves?|reduces?|increases?|outperforms?|enables?)\s+([\w\- ]{3,40})", re.I),
     "improves"),
    (re.compile(r"\b(\w[\w\-]{2,})\s+(is|are)\s+(?:a|an)\s+([\w\- ]{3,40})", re.I), "is_a"),
    (re.compile(r"\b(\w[\w\-]{2,})\s+(requires?|depends on|builds on)\s+([\w\- ]{3,40})", re.I), "depends_on"),
]


def _claim_texts(doc, limit=40):
    out = []
    for p in doc.paragraphs:
        if p.kind not in ("body", "caption"):
            continue
        for s in textops.split_sentences(p.text):
            s = s.strip()
            if len(s) < 25:
                continue
            if ASSERTION_CUES.search(s) or (textops.CITE.search(s) and re.search(r"\d", s)):
                out.append({"sentence": s, "page": p.page, "bbox": p.bbox, "para": p.id})
            if len(out) >= limit:
                return out
    return out


def _to_claim(item, idx):
    s = item["sentence"]
    numbers = re.findall(r"\d+(?:\.\d+)?\s*(?:%|pp)?", s)
    confidence = 0.4
    if ASSERTION_CUES.search(s):
        confidence += 0.3
    if numbers:
        confidence += 0.15
    if textops.CITE.search(s):
        confidence += 0.1
    return {
        "id": "a%d" % idx,
        "assertion": s,
        "subject_hint": (re.findall(r"^([A-Z][\w\-]+(?:\s+[A-Z][\w\-]+)?)", s) or [None])[0],
        "quantities": numbers,
        "citations": [m.group(0) for m in textops.CITE.finditer(s)],
        "confidence": round(min(confidence, 0.95), 2),
        "evidence": {"page": item["page"], "bbox": item["bbox"], "para": item["para"]},
    }


def _relations(doc, limit=25):
    out = []
    for p in doc.paragraphs:
        if p.kind != "body":
            continue
        for pattern, label in REL_PATTERNS:
            for m in pattern.finditer(p.text):
                out.append(
                    {
                        "subject": m.group(1).strip(),
                        "predicate": label,
                        "object": m.group(3).strip()[:60],
                        "page": p.page,
                        "evidence": p.id,
                    }
                )
                if len(out) >= limit:
                    return out
    return out


def _nanopub_id(case_id, doc_name):
    h = hashlib.sha1(("%s|%s" % (case_id, doc_name)).encode()).hexdigest()[:16]
    return "np:" + h


def run(ctx):
    case = ctx["case"] or {}
    result = ctx["result"]
    pdfs = ctx["inputs"].get("pdf") or []
    if not pdfs:
        result["uncertainty"].append("case 中没有可读的 PDF 输入")
        return {"status": "failed"}

    path = pdfs[0]
    doc = docmodel.load(path, ctx.get("max_pages"))
    doc_name = os.path.basename(path)

    claims = [_to_claim(c, i) for i, c in enumerate(_claim_texts(doc))]
    if not claims:
        result["uncertainty"].append("未抽取到可归因的断言句，建议放宽 ASSERTION_CUES 或检查文字层")
        return {"status": "failed"}

    low_conf = [c["id"] for c in claims if c["confidence"] < 0.55]
    relations = _relations(doc)

    refs = doc.references()
    provenance = {
        "source_document": doc_name,
        "pages": doc.raw.get("page_count"),
        "extraction": {
            "method": "layout-aware PDF text extraction + sentence-level cue matching",
            "tool": "pdf-order / docmodel",
            "deterministic": True,
        },
        "derived_from": {
            "paragraphs": doc.summary()["paragraphs"],
            "sections": [s.title[:60] for s in doc.sections if s.level > 0][:8],
            "references": len(refs),
        },
    }
    publication = {
        "nanopub_id": _nanopub_id(ctx.get("case_id") or "case", doc_name),
        "generated_at": result.get("generated_at"),
        "license_note": "断言文本引用自原文；再分发前请确认原文许可",
        "creator": "reading-14-nanopub skill",
    }

    assertions = {
        "claims": claims,
        "relations": relations,
        "claim_count": len(claims),
        "relation_count": len(relations),
    }

    uncited = [c["id"] for c in claims if not c["citations"]]
    if uncited:
        result["uncertainty"].append(
            "%d 条断言在原文中没有可见文献标记（%s），它们依赖正文陈述而非引文"
            % (len(uncited), ", ".join(uncited[:5]))
        )
    if low_conf:
        result["uncertainty"].append(
            "%d 条断言置信度低于 0.55（%s），建议人工确认后再对外发布"
            % (len(low_conf), ", ".join(low_conf[:5]))
        )

    status = "success" if len(claims) >= 3 else "partial"

    return {
        "status": status,
        "skill_name": SKILL,
        "text": "\n".join(c["assertion"] for c in claims),
        "nanopublication": {
            "assertion": assertions,
            "provenance": provenance,
            "publication": publication,
        },
        "claims": claims,
        "relations": relations,
        "evidence": [c["evidence"] for c in claims][:40],
    }
