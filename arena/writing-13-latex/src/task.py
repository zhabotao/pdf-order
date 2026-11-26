#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写作13｜LaTeX 写作与编译 — static checks and safe patches.

No compiler, no network: everything here is decidable from the source text. That
keeps the result deterministic and lets a reviewer reproduce every reported issue
by grepping the file.
"""

from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PKG, "core"))

import textops  # noqa: E402

SKILL = "writing-13-latex"

TABLE_CHECKS = [
    (re.compile(r"\\begin\{(table|figure)\*?\}(?:(?!\\centering).){0,200}", re.S), "missing_centering"),
    (re.compile(r"\\begin\{table\*?\}(?:(?!\\caption).){0,400}\\end\{table\*?\}", re.S), "table_without_caption"),
    (re.compile(r"\\caption\{(?![^{}]*\})"), "caption_brace"),
]


def _line_of(src, offset):
    return src.count("\n", 0, offset) + 1


def _safe_fixes(src):
    fixes = []
    out = src

    m = re.search(r"\n{4,}", out)
    if m:
        out = re.sub(r"\n{4,}", "\n\n\n", out)
        fixes.append({"rule": "collapse_blank_lines"})

    trimmed = "\n".join(l.rstrip() for l in out.split("\n"))
    if trimmed != out:
        out = trimmed
        fixes.append({"rule": "strip_trailing_space"})

    spaced = re.sub(r"(?<=\S) {2,}(?=\S)", " ", out)
    if spaced != out:
        out = spaced
        fixes.append({"rule": "collapse_double_space"})

    # \cite{a, b} -> \cite{a,b} (space inside key list breaks some styles)
    key_spaced = re.sub(r"\\cite([a-z]*)\{([^}]*)\}", lambda m: "\\cite%s{%s}" % (m.group(1), re.sub(r"\s*,\s*", ",", m.group(2))), out)
    if key_spaced != out:
        out = key_spaced
        fixes.append({"rule": "normalize_cite_keys"})

    return out, fixes


def _style_issues(src):
    issues = []
    for pattern, name in TABLE_CHECKS:
        for m in pattern.finditer(src):
            issues.append({"type": name, "line": _line_of(src, m.start())})

    # booktabs vs \hline in tabular
    for m in re.finditer(r"\\begin\{tabular\}.*?\\end\{tabular\}", src, re.S):
        block = m.group(0)
        if "\\hline" in block and "\\toprule" not in block:
            issues.append({"type": "bare_hline_in_table", "line": _line_of(src, m.start())})

    # equation environments without label
    for m in re.finditer(r"\\begin\{(equation|align)\}(.*?)\\end\{\1\}", src, re.S):
        if "\\label" not in m.group(2):
            issues.append({"type": "equation_without_label", "line": _line_of(src, m.start())})

    # double punctuation / stray full-width chars in latin text
    for m in re.finditer(r"[a-zA-Z]\s*[，。；：]", src):
        issues.append({"type": "fullwidth_punct_in_latin", "line": _line_of(src, m.start()), "span": m.group(0)})

    # \ref to a label defined later is fine; but \ref{} empty is not
    for m in re.finditer(r"\\ref\{\s*\}", src):
        issues.append({"type": "empty_ref", "line": _line_of(src, m.start())})

    return issues


def run(ctx):
    case = ctx["case"] or {}
    result = ctx["result"]

    texs = ctx["inputs"].get("tex") or []
    if not texs:
        result["uncertainty"].append("case 中没有 .tex 源文件；本 Skill 只处理 LaTeX 源码，不处理 PDF")
        return {"status": "failed"}

    src = open(texs[0], encoding="utf-8", errors="replace").read()
    name = os.path.basename(texs[0])

    bib = ""
    bibs = ctx["inputs"].get("bib") or []
    if bibs:
        bib = open(bibs[0], encoding="utf-8", errors="replace").read()

    static = textops.latex_checks(src + ("\n" + bib if bib else ""))
    style = _style_issues(src)
    fixed, fixes = _safe_fixes(src)

    hard = [i for i in static if i["type"] in ("unbalanced_brace", "unbalanced_environment", "undefined_refs", "cites_missing_in_bib")]
    blocking = [i for i in hard if i.get("items") or i.get("offset")]

    if blocking:
        result["uncertainty"].append(
            "%d 类问题会导致编译失败或参考文献显示 ?，优先修" % len(blocking)
        )
    if not bibs:
        result["uncertainty"].append("未提供 .bib 文件，只核对了 \\cite 与 \\bibitem 的自洽性，未验证条目真实存在")
    if style:
        result["uncertainty"].append("样式类问题 %d 处（如表格未居中、公式缺 label），不影响编译但影响评审观感" % len(style))

    patches = []
    if fixed != src:
        patches.append(
            {
                "type": "safe_fix",
                "rules": [f["rule"] for f in fixes],
                "note": "仅合并多余空行/空白与规范 \\cite 键列表，不改变内容",
            }
        )
    for issue in style[:20]:
        patches.append({"type": "manual", "issue": issue["type"], "line": issue["line"]})

    status = "success" if not blocking else "partial"

    return {
        "status": status,
        "skill_name": SKILL,
        "text": fixed,
        "document": {"source": name, "lines": src.count("\n") + 1, "bytes": len(src)},
        "checks": static,
        "style_issues": style,
        "patches": patches,
        "fixes_applied": fixes,
        "stats": {
            "blocking": len(blocking),
            "style": len(style),
            "auto_fixed": len(fixes),
        },
        "evidence": [],
    }
