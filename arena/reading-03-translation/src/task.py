#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阅读03｜文献翻译 — paragraph-aligned bilingual translation with hard checks.

Design: a translation is produced by the agent, but the skill owns everything a
model is bad at — paragraph inventory that cannot silently drop text, a glossary
that is enforced rather than suggested, and a post-translation audit that compares
numbers, units, citation markers and equation numbers against the source.

Two modes:
  extract  (default) — emit the aligned source inventory + glossary + checklist
  assemble           — the case supplies `translations`; pair them, audit, and
                       emit the bilingual deliverable
"""

from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PKG, "core"))

import docmodel  # noqa: E402
import textops  # noqa: E402

SKILL = "reading-03-translation"

MAX_PARAS = 400


def _pick_pdf(ctx):
    pdfs = ctx["inputs"].get("pdf") or []
    return pdfs[0] if pdfs else None


def _glossary_from_case(case):
    g = case.get("glossary") or case.get("terms") or {}
    if isinstance(g, list):
        out = {}
        for row in g:
            if isinstance(row, dict):
                src = row.get("source") or row.get("term") or row.get("en")
                dst = row.get("target") or row.get("translation") or row.get("zh")
                if src:
                    out[str(src)] = dst
        return out
    return dict(g) if isinstance(g, dict) else {}


def run(ctx):
    case = ctx["case"] or {}
    result = ctx["result"]
    pdf = _pick_pdf(ctx)
    if not pdf:
        result["uncertainty"].append("case 中没有可读的 PDF 输入")
        return {"status": "failed"}

    doc = docmodel.load(pdf, ctx.get("max_pages"))

    # paragraphs that carry prose, with stable ids and page anchors
    paras = [p for p in doc.paragraphs if p.kind in ("body", "caption")]
    if len(paras) > MAX_PARAS:
        result["uncertainty"].append(
            "段落数 %d 超过单次处理上限 %d，只处理前 %d 段" % (len(paras), MAX_PARAS, MAX_PARAS)
        )
        paras = paras[:MAX_PARAS]

    source_text = "\n".join(p.text for p in paras)
    provided = _glossary_from_case(case)
    glossary = textops.extract_glossary(source_text, provided)

    for p in paras:
        p.text = textops.strip_pua(p.text)

    inventory = [
        {
            "id": p.id,
            "page": p.page,
            "bbox": p.bbox,
            "kind": p.kind,
            "source": p.text,
            "protected": textops.protected_tokens(p.text),
            "sha1_16": textops.sha1_16(p.text),
        }
        for p in paras
    ]

    translations = case.get("translations")
    if isinstance(translations, list) and translations:
        return _assemble(ctx, doc, inventory, glossary, translations)

    result["uncertainty"].append(
        "本模式下译文由调用方（Agent）产出；请把译文按段落顺序填入后重新调用，"
        "assembled 模式会执行数字、单位、引用与术语的机械核验。"
    )
    return {
        "status": "partial",
        "skill_name": SKILL,
        "text": source_text,
        "document": {
            "pages": doc.raw.get("page_count"),
            "paragraph_count": len(inventory),
            "sections": [s.as_dict() for s in doc.sections if s.level > 0],
        },
        "bilingual": [
            {
                "index": i,
                "id": row["id"],
                "page": row["page"],
                "bbox": row["bbox"],
                "source": row["source"],
                "translation": None,
                "status": "untranslated",
            }
            for i, row in enumerate(inventory)
        ],
        "glossary": [
            {"source": k, "target": v, "freq": None} for k, v in sorted(glossary.items())
        ],
        "glossary_unmapped": sorted([k for k, v in glossary.items() if not v]),
        "checklist": [
            "逐段翻译，不得合并或拆分段落编号",
            "术语表命中的词必须用表中译名，不得同义替换",
            "数字、单位、文献编号、公式编号原样保留",
            "无法翻译或原文残缺处标注，不要编造",
        ],
        "evidence": [
            {"id": row["id"], "page": row["page"], "bbox": row["bbox"], "sha1_16": row["sha1_16"]}
            for row in inventory[:40]
        ],
    }


def _assemble(ctx, doc, inventory, glossary, translations):
    result = ctx["result"]
    src_paras = [row["source"] for row in inventory]
    missing = max(0, len(src_paras) - len(translations))
    if missing:
        result["uncertainty"].append("有 %d 段原文没有对应译文" % missing)
    if len(translations) > len(src_paras):
        result["uncertainty"].append("译文比原文多出 %d 段，已按顺序截断" % (len(translations) - len(src_paras)))

    pairs = []
    hits = 0
    for i, row in enumerate(inventory):
        src = row["source"]
        dst = translations[i] if i < len(translations) else None
        entry = {
            "index": i,
            "id": row["id"],
            "page": row["page"],
            "bbox": row["bbox"],
            "source": src,
            "translation": dst,
            "status": "ok" if dst else "untranslated",
        }
        if dst:
            lost = textops.preservation_report(src, dst)
            if lost:
                entry["lost"] = lost
                entry["status"] = "needs_review"
            # enforce glossary on the translation
            enforced = dst
            for term, tgt in glossary.items():
                if tgt and re.search(r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])", enforced, re.I):
                    hits += 1
                    enforced = re.sub(
                        r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])", tgt, enforced, flags=re.I
                    )
            if enforced != dst:
                entry["glossary_applied"] = True
                entry["translation"] = enforced
        pairs.append(entry)

    audit = {
        "paragraphs": len(inventory),
        "translated": sum(1 for p in pairs if p["translation"]),
        "needs_review": sum(1 for p in pairs if p["status"] == "needs_review"),
        "untranslated": sum(1 for p in pairs if p["status"] == "untranslated"),
        "glossary_terms": len(glossary),
        "glossary_hits": hits,
        "glossary_unmapped": sorted([k for k, v in glossary.items() if not v]),
    }

    if audit["untranslated"]:
        status = "partial"
    elif audit["needs_review"]:
        status = "partial"
    else:
        status = "success"

    return {
        "status": status,
        "skill_name": SKILL,
        "text": "\n".join(t for t in translations if t),
        "document": {"pages": doc.raw.get("page_count"), "paragraph_count": len(inventory)},
        "bilingual": pairs,
        "audit": audit,
        "glossary": [{"source": k, "target": v} for k, v in sorted(glossary.items())],
        "evidence": [
            {"id": p["id"], "page": p["page"], "bbox": p["bbox"]} for p in pairs[:40]
        ],
    }
