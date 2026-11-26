#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写作08｜引言与相关工作写作 — a three-part skeleton with quoted evidence.

The intro is assembled from real sentences in the supplied material: what is
known, what is missing, what this work contributes. Slots that have no supporting
sentence stay empty and are reported, so the agent writes prose around verified
content instead of inventing a gap.
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

SKILL = "writing-08-intro"

GAP_CUES = re.compile(
    r"(however|remains? (?:unclear|open|unknown)|limited|few studies|has not been|"
    r"lacks?|suffer from|未能|尚不清楚|仍然(?:是|存在)|不足|缺少|尚未)",
    re.I,
)
CONTRIB_CUES = re.compile(
    r"(we (?:propose|present|introduce|develop|show)|this (?:paper|work) |"
    r"本文|我们(?:提出|开发|构建|设计)|贡献)",
    re.I,
)
BACKGROUND_CUES = re.compile(
    r"(has (?:become|emerged)|is widely|have been (?:used|applied)|recently|"
    r"近年来|广泛应用于|已经成为|随着)",
    re.I,
)


def _collect_sentences(text, pattern, limit=6):
    out = []
    for s in textops.split_sentences(text):
        s = s.strip()
        if len(s) < 20 or len(s) > 400:
            continue
        if pattern.search(s):
            out.append(s)
        if len(out) >= limit:
            break
    return out


def _related_themes(references, top=8):
    """Group references by a crude keyword theme so 'related work' has structure."""
    themes = {}
    for r in references:
        title = r["raw"]
        words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", title)]
        for w in words:
            if w in ("with", "from", "that", "this", "using", "based", "towards", "through"):
                continue
            themes.setdefault(w, []).append(title[:80])
    ranked = sorted(themes.items(), key=lambda kv: -len(kv[1]))
    return [{"theme": k, "count": len(v), "examples": v[:3]} for k, v in ranked[:top] if len(v) >= 2]


def run(ctx):
    case = ctx["case"] or {}
    result = ctx["result"]

    text, name = "", None
    texs = ctx["inputs"].get("tex") or []
    texts = ctx["inputs"].get("text") or []
    pdfs = ctx["inputs"].get("pdf") or []
    if texs or texts:
        path = (texs or texts)[0]
        text = open(path, encoding="utf-8", errors="replace").read()
        name = os.path.basename(path)
    elif pdfs:
        doc = docmodel.load(pdfs[0], ctx.get("max_pages"))
        text = doc.full_text()
        name = os.path.basename(pdfs[0])
        result["uncertainty"].append("输入为 PDF，引用标记按抽取文本识别，可能缺少超链接信息")

    if not text.strip():
        result["uncertainty"].append("没有可用的正文素材")
        return {"status": "failed"}

    background = _collect_sentences(text, BACKGROUND_CUES, 5)
    gaps = _collect_sentences(text, GAP_CUES, 5)
    contributions = _collect_sentences(text, CONTRIB_CUES, 6)

    refs = []
    if pdfs:
        refs = docmodel.load(pdfs[0], ctx.get("max_pages")).references()
    elif "\\bibitem" in text:
        for m in re.finditer(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}(.*?)(?=\\bibitem|\\end\{thebibliography\})", text, re.S):
            refs.append({"raw": textops.normalize_space(m.group(2)), "page": None, "bbox": None})
    themes = _related_themes(refs)

    missing = []
    if not background:
        missing.append("background")
    if not gaps:
        missing.append("gap")
    if not contributions:
        missing.append("contribution")
    if missing:
        result["uncertainty"].append(
            "素材中没有找到这些要素的支撑句：%s；请补充材料或由 Agent 明确标注为待补" % ", ".join(missing)
        )

    skeleton = [
        {
            "part": "1. 背景（已知）",
            "slots": [{"type": "quoted_evidence", "text": s} for s in background],
            "advice": "按「领域现状 → 为什么重要」两段展开；每句结论都要有引用标记",
        },
        {
            "part": "2. 研究缺口（未知）",
            "slots": [{"type": "quoted_evidence", "text": s} for s in gaps],
            "advice": "缺口必须是对现有工作的具体限制，不要写成「此前无人研究」",
        },
        {
            "part": "3. 本文贡献（新增）",
            "slots": [{"type": "quoted_evidence", "text": s} for s in contributions],
            "advice": "每条贡献对应一个可验证证据；不要在引言里承诺正文没有的结果",
        },
    ]
    if themes:
        skeleton.append(
            {
                "part": "4. 相关工作分组",
                "slots": [{"type": "theme", "theme": t["theme"], "count": t["count"], "examples": t["examples"]} for t in themes],
                "advice": "按主题分组评述，每组结尾指出与本文的差异；不要逐篇罗列",
            }
        )

    status = "success" if background and gaps and contributions else "partial"

    return {
        "status": status,
        "skill_name": SKILL,
        "text": "\n".join(
            "[%s] %s" % (part["part"], s["text"])
            for part in skeleton
            for s in part["slots"]
            if s["type"] == "quoted_evidence"
        ),
        "document": {"source": name, **textops.wc(text)},
        "skeleton": skeleton,
        "missing_evidence": missing,
        "related_work_themes": themes,
        "evidence": [],
    }
