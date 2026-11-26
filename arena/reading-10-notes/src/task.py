#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阅读10｜文献总结与结构化笔记 — one-page notes with section-level evidence.

The note is extractive on purpose: every line either quotes the paper or names a
counted item, so a reader can check it against the page. Nothing is paraphrased
into a claim the paper does not make.
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

SKILL = "reading-10-notes"

CLAIM_CUES = re.compile(
    r"(we (?:show|propose|demonstrate|find|argue|introduce|present|observe)|"
    r"本文|我们(?:提出|证明|发现|表明|实验)|实验表明|结果表明|本文贡献)",
    re.I,
)
METRIC_CUES = re.compile(
    r"(\d+(?:\.\d+)?\s*%|\bpp\b|perplexity|accuracy|F1|BLEU|ROUGE|速度|准确率|困惑度|提升|降低)",
    re.I,
)


def _key_sentences(paras, limit=4):
    picked = []
    for p in paras:
        for s in textops.split_sentences(p.text):
            s = s.strip()
            if len(s) < 12:
                continue
            score = 0
            if CLAIM_CUES.search(s):
                score += 3
            if METRIC_CUES.search(s):
                score += 2
            if textops.CITE.search(s):
                score += 1
            if not picked and not any(x["para"] == p.id for x in picked):
                score += 1  # the opening sentence of a section is usually its claim
            if score > 0:
                picked.append({"para": p.id, "page": p.page, "text": s, "score": score})
            if len(picked) >= limit:
                return picked
    return picked


def _numbers_with_anchor(doc, limit=12):
    out = []
    for p in doc.paragraphs:
        if p.kind != "body":
            continue
        for m in re.finditer(r"\d+(?:\.\d+)?\s*(?:%|pp|×|x)?", p.text):
            token = m.group(0).strip()
            if len(token) < 2:
                continue
            if not re.search(r"%|\d\.\d|pp|×|x", token):
                continue
            ctx = p.text[max(0, m.start() - 40): m.end() + 40]
            out.append({"value": token, "page": p.page, "bbox": p.bbox, "context": ctx})
            if len(out) >= limit:
                return out
    return out


def run(ctx):
    case = ctx["case"] or {}
    result = ctx["result"]
    pdfs = ctx["inputs"].get("pdf") or []
    if not pdfs:
        result["uncertainty"].append("case 中没有可读的 PDF 输入")
        return {"status": "failed"}

    if len(pdfs) > 1:
        result["uncertainty"].append(
            "输入包含 %d 篇文献；本模式逐篇生成笔记，跨篇对比见 comparison" % len(pdfs)
        )

    notes = []
    comparison = []
    for path in pdfs[:6]:
        doc = docmodel.load(path, ctx.get("max_pages"))
        sec_notes = []
        for sec in doc.sections:
            if sec.level == 0 and not sec.paragraphs:
                continue
            body = [p for p in sec.paragraphs if p.kind == "body"]
            if not body:
                continue
            sec_notes.append(
                {
                    "section": sec.title[:80],
                    "level": sec.level,
                    "page": sec.page,
                    "paragraph_count": len(body),
                    "key_sentences": _key_sentences(body, limit=3),
                }
            )

        caps = doc.captions()
        figures = [c.text[:100] for c in caps if re.match(r"^\s*(图|Figure|Fig\.?)", c.text, re.I)]
        tables = [c.text[:100] for c in caps if re.match(r"^\s*(表|Table)", c.text, re.I)]

        note = {
            "document": os.path.basename(path),
            "pages": doc.raw.get("page_count"),
            "stats": doc.summary(),
            "sections": sec_notes,
            "key_numbers": _numbers_with_anchor(doc),
            "figures": figures[:10],
            "tables": tables[:10],
            "references_count": len(doc.references()),
            "open_questions": [
                "哪些结论依赖单一数据集，缺少跨领域验证？",
                "原文是否报告了失败案例或负结果？",
                "关键指标的口径（均值/最优/单次）是否写明？",
            ],
        }
        notes.append(note)
        comparison.append(
            {
                "document": note["document"],
                "sections": len(sec_notes),
                "paragraphs": note["stats"]["paragraphs"],
                "figures": len(figures),
                "tables": len(tables),
                "references": note["references_count"],
            }
        )

    outline = []
    for note in notes:
        for sec in note["sections"]:
            for ks in sec["key_sentences"][:1]:
                outline.append(
                    {
                        "heading": sec["section"],
                        "page": ks["page"],
                        "point": ks["text"][:120],
                    }
                )

    primary = notes[0]
    status = "success" if primary["sections"] else "partial"
    if not primary["sections"]:
        result["uncertainty"].append("未识别到章节结构，笔记退化为整篇抽取")

    return {
        "status": status,
        "skill_name": SKILL,
        "text": "\n".join(
            "%s（p%s）：%s" % (o["heading"], o["page"], o["point"]) for o in outline
        ),
        "notes": notes,
        "outline": outline,
        "comparison": comparison if len(comparison) > 1 else [],
        "evidence": [
            {"page": ks["page"], "text_sha1_16": textops.sha1_16(ks["text"])}
            for note in notes
            for sec in note["sections"]
            for ks in sec["key_sentences"][:2]
        ][:40],
    }
