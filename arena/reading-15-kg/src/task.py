#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阅读15｜文献知识图谱构建 — entities, relations and conflict annotation.

Rule-based on purpose: rules can be audited, and every edge keeps the page it
came from. Extraction quality is reported as counts plus the sentences that
produced each edge, so a reviewer can measure precision without trusting prose.
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

SKILL = "reading-15-kg"

# predicate cues: (regex, relation label)
PREDICATES = [
    (re.compile(r"\b(improves?|提升|提高|改善)\b", re.I), "improves"),
    (re.compile(r"\b(reduces?|降低|减少)\b", re.I), "reduces"),
    (re.compile(r"\b(outperforms?|优于|超过)\b", re.I), "outperforms"),
    (re.compile(r"\b(requires?|依赖|需要)\b", re.I), "requires"),
    (re.compile(r"\b(consists? of|composed of|由.{0,6}组成)\b", re.I), "composed_of"),
    (re.compile(r"\b(compared (?:to|with)|相比|对比)\b", re.I), "compared_with"),
    (re.compile(r"\b(is a|are a|是一种|属于)\b", re.I), "is_a"),
]

METHOD_HINT = re.compile(
    r"(Transformer|Sinkhorn|attention|softmax|BERT|GPT|LLM|CNN|RNN|GAN|diffusion|"
    r"模型|算法|框架|方法|注意力)", re.I
)
METRIC_HINT = re.compile(r"(%|pp|perplexity|accuracy|F1|BLEU|ROUGE|困惑度|准确率)", re.I)
DATASET_HINT = re.compile(r"(RULER|GLUE|SQuAD|ImageNet|WikiText|C4|数据集|benchmark)", re.I)


def _entity_kind(name):
    if DATASET_HINT.search(name):
        return "dataset"
    if METRIC_HINT.search(name):
        return "metric"
    if METHOD_HINT.search(name):
        return "method"
    return "concept"


def _norm(name):
    return re.sub(r"\s+", " ", name.strip().strip("，,.;:")).lower()


def _extract_entities(doc):
    seen = {}
    patterns = [
        (re.compile(r"\b([A-Z][A-Za-z0-9\-]{2,}(?:\s+[A-Z][A-Za-z0-9\-]{2,}){0,2})\b"), None),
        (re.compile(r"\b([A-Z]{2,}[0-9]{0,3})\b"), None),
    ]
    for p in doc.paragraphs:
        if p.kind not in ("body", "caption"):
            continue
        for pattern, _ in patterns:
            for m in pattern.finditer(p.text):
                name = m.group(1).strip()
                if len(name) < 3 or name.isdigit():
                    continue
                if name.lower() in ("the", "this", "we", "figure", "table"):
                    continue
                key = _norm(name)
                ent = seen.get(key)
                if ent:
                    ent["mentions"] += 1
                    if p.page not in ent["pages"]:
                        ent["pages"].append(p.page)
                else:
                    seen[key] = {
                        "id": "e%d" % (len(seen) + 1),
                        "label": name,
                        "kind": _entity_kind(name),
                        "mentions": 1,
                        "pages": [p.page],
                        "evidence": {"para": p.id, "page": p.page, "bbox": p.bbox},
                    }
    return list(seen.values())


def _extract_relations(doc, entities):
    by_label = { _norm(e["label"]): e for e in entities }
    edges = []
    for p in doc.paragraphs:
        if p.kind != "body":
            continue
        for s in textops.split_sentences(p.text):
            hits = [e for key, e in by_label.items() if key in _norm(s)]
            if len(hits) < 2:
                continue
            for pattern, label in PREDICATES:
                if not pattern.search(s):
                    continue
                a, b = hits[0], hits[1]
                if a["id"] == b["id"]:
                    continue
                edges.append(
                    {
                        "source": a["id"],
                        "target": b["id"],
                        "relation": label,
                        "sentence": s[:160],
                        "page": p.page,
                        "evidence": p.id,
                    }
                )
                break
            if len(edges) >= 60:
                return edges
    return edges


def _conflicts(doc, edges):
    """Same subject+target pair asserted with opposite polarity."""
    out = []
    pairs = {}
    for e in edges:
        pairs.setdefault((e["source"], e["target"]), []).append(e)
    for (s, t), rows in pairs.items():
        rels = {r["relation"] for r in rows}
        if {"improves", "reduces"} <= rels:
            out.append(
                {
                    "type": "polarity_conflict",
                    "source": s,
                    "target": t,
                    "relations": sorted(rels),
                    "pages": sorted({r["page"] for r in rows}),
                }
            )
    return out


def run(ctx):
    case = ctx["case"] or {}
    result = ctx["result"]
    pdfs = ctx["inputs"].get("pdf") or []
    if not pdfs:
        result["uncertainty"].append("case 中没有可读的 PDF 输入")
        return {"status": "failed"}

    doc = docmodel.load(pdfs[0], ctx.get("max_pages"))
    entities = _extract_entities(doc)
    if not entities:
        result["uncertainty"].append("未抽到实体，检查文字层或放宽实体规则")
        return {"status": "failed"}

    entities.sort(key=lambda e: -e["mentions"])
    entities = entities[:80]
    edges = _extract_relations(doc, entities)
    conflicts = _conflicts(doc, edges)

    low = [e["label"] for e in entities if e["mentions"] <= 1]
    if low:
        result["uncertainty"].append(
            "%d 个实体只出现一次（%s…），单选提及不足以支撑图谱关系"
            % (len(low), ", ".join(low[:5]))
        )
    if conflicts:
        result["uncertainty"].append(
            "发现 %d 处极性冲突（同一对实体同时被断言提升与降低），已标注待人工裁定" % len(conflicts)
        )
    if not edges:
        result["uncertainty"].append("实体已抽取但未匹配到关系谓词，图谱退化为实体表")

    kinds = {}
    for e in entities:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1

    status = "success" if edges and len(entities) >= 5 else "partial"

    return {
        "status": status,
        "skill_name": SKILL,
        "text": "\n".join("%s -[%s]-> %s" % (e["source"], e["relation"], e["target"]) for e in edges),
        "entities": entities,
        "relations": edges,
        "graph": {
            "node_count": len(entities),
            "edge_count": len(edges),
            "kinds": kinds,
            "conflicts": conflicts,
        },
        "evidence": (
            [e["evidence"] for e in entities][:20]
            + [{"para": r["evidence"], "page": r["page"]} for r in edges][:20]
        ),
    }
