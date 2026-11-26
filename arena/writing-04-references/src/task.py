#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写作04｜参考文献与引用管理 — parse, reconcile, dedupe, export BibTeX.

The failure this targets is silent: a citation number in the body that no longer
points at the right entry, or a reference that was deleted from the list while the
body still cites it. Both are reported as explicit sets, not as prose.
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

SKILL = "writing-04-references"


def _load(ctx):
    """Return (body_text, references, source_name)."""
    result = ctx["result"]
    texs = ctx["inputs"].get("tex") or []
    if texs:
        src = open(texs[0], encoding="utf-8", errors="replace").read()
        body = re.sub(r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}", "", src, flags=re.S)
        refs = []
        for m in re.finditer(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}(.*?)(?=\\bibitem|\\end\{thebibliography\})", src, re.S):
            refs.append({"raw": textops.normalize_space(m.group(2)), "key": m.group(1), "page": None, "bbox": None})
        if not refs:
            for m in re.finditer(r"\\(?:bibitem|item)\s*\{(.*?)\}", src, re.S):
                refs.append({"raw": textops.normalize_space(m.group(1)), "page": None, "bbox": None})
        return body, refs, os.path.basename(texs[0])

    pdfs = ctx["inputs"].get("pdf") or []
    if pdfs:
        doc = docmodel.load(pdfs[0], ctx.get("max_pages"))
        refs = [
            {"raw": r["text"], "page": r.get("page"), "bbox": r.get("bbox")}
            for r in doc.references()
        ]
        body = "\n".join(p.text for p in doc.paragraphs if p.kind == "body")
        if not refs:
            result["uncertainty"].append("未在 PDF 中定位到参考文献章节，可能标题写法不同或为双栏排版")
        return body, refs, os.path.basename(pdfs[0])

    return "", [], None


def _bibtex(refs):
    """Emit minimal, valid BibTeX; mark what could not be inferred."""
    out = []
    used = set()
    for i, r in enumerate(refs, 1):
        parsed = textops.parse_reference(r["raw"])
        year = parsed.get("year") or "0000"
        first = re.match(r"^\s*(?:\[\d+\]|\d+[.)])?\s*([A-Za-z\-]+)", r["raw"])
        author = first.group(1) if first else "ref"
        key = re.sub(r"\W+", "", "%s%s" % (author, year)).lower() or "ref%d" % i
        base = key
        n = 1
        while key in used:
            n += 1
            key = "%s%s" % (base, n)
        used.add(key)

        title = re.sub(r"^\s*(?:\[\d+\]|\d+[.)])\s*", "", r["raw"])
        title = re.sub(r"\s+", " ", title)
        fields = [
            "  author = {%s}" % (author,),
            "  title  = {%s}" % (title[:180].replace("{", "").replace("}", ""),),
        ]
        if parsed.get("year"):
            fields.append("  year   = {%s}" % parsed["year"])
        if parsed.get("doi"):
            fields.append("  doi    = {%s}" % parsed["doi"])
        out.append("@misc{%s,\n%s\n}" % (key, ",\n".join(fields)))
    return "\n\n".join(out)


def _dedupe(refs):
    seen = {}
    dupes = []
    for r in refs:
        parsed = textops.parse_reference(r["raw"])
        key = parsed["key"]
        if key in seen:
            dupes.append({"kept": seen[key]["raw"][:60], "dropped": r["raw"][:60]})
        else:
            seen[key] = r
    return list(seen.values()), dupes


def run(ctx):
    case = ctx["case"] or {}
    result = ctx["result"]
    body, refs, name = _load(ctx)
    if not refs and not body.strip():
        result["uncertainty"].append("未找到正文或参考文献")
        return {"status": "failed"}

    for r in refs:
        r.pop("key", None)

    unique, dupes = _dedupe(refs)
    style = textops.format_style_profile(unique)
    recon = textops.reconcile_citations(body, unique)

    missing_doi = [i for i, r in enumerate(unique, 1) if not textops.parse_reference(r["raw"]).get("doi")]
    missing_year = [i for i, r in enumerate(unique, 1) if not textops.parse_reference(r["raw"]).get("year")]

    if style["mixed"]:
        result["uncertainty"].append(
            "参考文献列表混用了两种编号风格（[n] %d 条 / n. %d 条），投稿前需统一" % (style["bracketed"], style["dotted"])
        )
    if recon["cited_not_listed"]:
        result["uncertainty"].append(
            "正文引用了但列表里没有的编号：%s" % ", ".join(str(x) for x in recon["cited_not_listed"][:10])
        )
    if recon["listed_not_cited"]:
        result["uncertainty"].append(
            "列表里有但正文未引用的编号：%s" % ", ".join(str(x) for x in recon["listed_not_cited"][:10])
        )
    if dupes:
        result["uncertainty"].append("检测到 %d 组重复条目，已去重" % len(dupes))

    status = "success" if unique and not recon["cited_not_listed"] else "partial"

    return {
        "status": status,
        "skill_name": SKILL,
        "text": _bibtex(unique),
        "references": [
            {
                "index": i,
                "raw": r["raw"],
                "year": textops.parse_reference(r["raw"]).get("year"),
                "doi": textops.parse_reference(r["raw"]).get("doi"),
                "page": r.get("page"),
                "bbox": r.get("bbox"),
            }
            for i, r in enumerate(unique, 1)
        ],
        "reconciliation": recon,
        "style": style,
        "duplicates": dupes,
        "quality": {
            "total": len(unique),
            "without_doi": missing_doi[:20],
            "without_year": missing_year[:20],
        },
        "evidence": [{"page": r.get("page"), "bbox": r.get("bbox")} for r in unique if r.get("page")][:30],
    }
