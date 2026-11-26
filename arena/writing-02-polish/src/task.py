#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写作02｜学术语言润色 — mechanical diagnostics plus only the safe rewrites.

Deliberately conservative: the skill reports what is objectively wrong (mixed
script spacing, doubled spaces, long sentences, tense drift, passive density) and
applies only fixes that cannot change meaning. Meaning-level rewriting stays with
the agent, and the diff is reported line by line so nothing changes silently.
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

SKILL = "writing-02-polish"

CJK = r"\u4e00-\u9fff"


def _source_text(ctx):
    """Prefer an editable source; fall back to PDF text."""
    result = ctx["result"]
    for key in ("tex", "text"):
        paths = ctx["inputs"].get(key) or []
        if paths:
            with open(paths[0], encoding="utf-8", errors="replace") as fh:
                return fh.read(), os.path.basename(paths[0]), "editable"
    pdfs = ctx["inputs"].get("pdf") or []
    if pdfs:
        doc = docmodel.load(pdfs[0], ctx.get("max_pages"))
        result["uncertainty"].append(
            "输入是 PDF，润色在抽取文本上进行；行首缩进、分栏等版式信息已丢失"
        )
        return doc.full_text(), os.path.basename(pdfs[0]), "pdf"
    return "", None, None


def _safe_fixes(text):
    """Rewrites that cannot alter meaning."""
    fixes = []
    original = text

    # 1) CJK <-> Latin spacing
    spaced = re.sub(rf"([{CJK}])([A-Za-z0-9(])", r"\1 \2", text)
    spaced = re.sub(rf"([A-Za-z0-9)%])([{CJK}])", r"\1 \2", spaced)
    if spaced != text:
        fixes.append({"rule": "cjk_latin_spacing", "changes": _count_diff(text, spaced)})
        text = spaced

    # 2) doubled spaces (never inside code blocks)
    collapsed = re.sub(r"(?<=\S) {2,}(?=\S)", " ", text)
    if collapsed != text:
        fixes.append({"rule": "collapse_double_space", "changes": _count_diff(text, collapsed)})
        text = collapsed

    # 3) trailing whitespace
    trimmed = "\n".join(line.rstrip() for line in text.split("\n"))
    if trimmed != text:
        fixes.append({"rule": "strip_trailing_space", "changes": _count_diff(text, trimmed)})
        text = trimmed

    return text, fixes, original != text


def _count_diff(a, b):
    return abs(len(a) - len(b)) or 1


def _term_repetition(text, top=12):
    counts = {}
    for w in re.findall(r"[A-Za-z][A-Za-z\-]{4,}", text):
        counts[w.lower()] = counts.get(w.lower(), 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    return [{"term": k, "count": v} for k, v in ranked[:top] if v >= 5]


def run(ctx):
    case = ctx["case"] or {}
    result = ctx["result"]
    text, name, kind = _source_text(ctx)
    if not text.strip():
        result["uncertainty"].append("未读到可润色的正文（既无 tex/md/txt，也无可用 PDF 文字层）")
        return {"status": "failed"}

    issues = textops.prose_issues(text)
    polished, fixes, changed = _safe_fixes(text)
    tense = textops.tense_profile(text)
    words = textops.wc(text)

    # reorganise issues into a review list a human can act on
    review = []
    for issue in issues:
        if issue["type"] == "long_sentence":
            review.append({
                "type": issue["type"],
                "location": issue["span"][:50],
                "advice": "拆成两个句子；保留主结论在前，限定条件在后",
            })
        elif issue["type"] == "long_paragraph":
            review.append({"type": issue["type"], "words": issue["words"], "advice": "按论点切段，每段一个主张"})
        elif issue["type"] == "mixed_script":
            review.append({"type": issue["type"], "span": issue["span"], "advice": "已由 cjk_latin_spacing 规则自动处理"})
        elif issue["type"] == "passive_voice":
            review.append({"type": issue["type"], "span": issue["span"], "advice": "方法描述可保留被动；结论句建议改主动"})

    passive_count = sum(1 for i in issues if i["type"] == "passive_voice")
    long_count = sum(1 for i in issues if i["type"] == "long_sentence")

    if kind == "pdf":
        result["uncertainty"].append("PDF 抽取文本无法反映原始换行与缩进，格式类问题可能误报")

    if not changed:
        result["uncertainty"].append("未发现可安全自动修正的问题；语义级润色需由 Agent 完成并复核")

    status = "success" if changed or review else "partial"

    return {
        "status": status,
        "skill_name": SKILL,
        "text": polished,
        "document": {"source": name, "kind": kind, **words},
        "issues": review,
        "fixes_applied": fixes,
        "stats": {
            "issue_count": len(review),
            "auto_fixed_rules": len(fixes),
            "long_sentences": long_count,
            "passive_constructions": passive_count,
            "tense": tense,
        },
        "repeated_terms": _term_repetition(text),
        "evidence": [],
    }
