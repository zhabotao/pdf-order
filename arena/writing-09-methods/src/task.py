#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写作09｜方法与实验章节写作 — derive a method section from results, then audit it.

Writing a method section from what was actually run means answering: what data, what
model, what hyper-parameters, what metric, what baseline. This skill extracts those
five from the supplied material, marks every slot it could not fill, and produces a
reproducibility checklist plus a 300-word compressed variant.
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

SKILL = "writing-09-methods"

DATASET_RE = re.compile(r"\b([A-Z][A-Za-z0-9\-]{2,}(?:-\d+[A-Za-z]*)?)\b(?=[^\n]{0,40}(?:dataset|数据集))")
MODEL_RE = re.compile(r"\b(\d+(?:\.\d+)?[BMK]|[A-Z][A-Za-z\-]{2,}(?:Former|Net|GPT|LM|BERT))\b")
METRIC_RE = re.compile(r"\b(perplexity|accuracy|F1|BLEU|ROUGE|RMSE|AUC|困惑度|准确率)\b", re.I)
PARAM_RE = re.compile(r"\b(?:learning rate|lr|batch size|epochs?|warmup|dropout|weight decay|学习率|批大小|轮数)\b[^.\n]{0,40}", re.I)
BASELINE_RE = re.compile(r"\b(baseline|compared (?:to|with)|vanilla|standard|基线|对比)\b[^.\n]{0,60}", re.I)


def _find(pattern, text, limit=8):
    out = []
    for m in pattern.finditer(text):
        val = textops.normalize_space(m.group(0))
        if val and val not in out:
            out.append(val[:120])
        if len(out) >= limit:
            break
    return out


def _load(ctx):
    texs = ctx["inputs"].get("tex") or []
    texts = ctx["inputs"].get("text") or []
    pdfs = ctx["inputs"].get("pdf") or []
    if texs or texts:
        path = (texs or texts)[0]
        return open(path, encoding="utf-8", errors="replace").read(), os.path.basename(path)
    if pdfs:
        ctx["result"]["uncertainty"].append("输入为 PDF；参数与数据集信息按抽取文本匹配，可能漏掉表格中的超参")
        doc = docmodel.load(pdfs[0], ctx.get("max_pages"))
        return doc.full_text(), os.path.basename(pdfs[0])
    return "", None


def _compress(text, target_words=300):
    """Extractive 300-word version: keep method-bearing sentences in order."""
    cues = re.compile(r"(we (?:train|use|apply|compute|evaluate|fine-tune)|我们(?:训练|使用|采用|计算|评估)|参数|设置|超参)", re.I)
    picked = []
    total = 0
    for s in textops.split_sentences(text):
        s = s.strip()
        if not s:
            continue
        w = len(s.split())
        if cues.search(s) or total < target_words * 0.3:
            if total + w <= target_words:
                picked.append(s)
                total += w
        if total >= target_words:
            break
    return " ".join(picked), total


def run(ctx):
    case = ctx["case"] or {}
    result = ctx["result"]
    text, name = _load(ctx)
    if not text.strip():
        result["uncertainty"].append("没有可用的素材来反推方法章节")
        return {"status": "failed"}

    datasets = _find(DATASET_RE, text)
    models = _find(MODEL_RE, text)
    metrics = sorted({m.group(0).lower() for m in METRIC_RE.finditer(text)})
    params = _find(PARAM_RE, text)
    baselines = _find(BASELINE_RE, text, limit=5)

    skeleton = [
        {"part": "数据", "items": datasets, "advice": "写清规模、切分、预处理；数据集版本要可追溯"},
        {"part": "模型", "items": models, "advice": "给出参数量、层数等可核对的配置，不要只写名字"},
        {"part": "训练配置", "items": params, "advice": "学习率、批大小、轮数、硬件与时长的缺项必须补齐"},
        {"part": "评测", "items": metrics, "advice": "指标口径（均值/最优/重复次数）要写明"},
        {"part": "基线", "items": baselines, "advice": "基线需与本文同数据同口径，注明来源"},
    ]

    empty = [p["part"] for p in skeleton if not p["items"]]
    checklist = [
        {"item": "数据集与版本", "found": bool(datasets)},
        {"item": "模型规模与结构", "found": bool(models)},
        {"item": "学习率/批大小/轮数", "found": bool(params)},
        {"item": "评测指标与口径", "found": bool(metrics)},
        {"item": "基线来源与复现方式", "found": bool(baselines)},
        {"item": "随机种子与重复次数", "found": bool(re.search(r"seed|种子|重复|runs", text, re.I))},
        {"item": "算力与训练时长", "found": bool(re.search(r"GPU|A100|H100|hours|小时|TPU", text, re.I))},
    ]
    missing_items = [c["item"] for c in checklist if not c["found"]]

    if missing_items:
        result["uncertainty"].append(
            "可复现性清单缺少：%s；这些不能被推测补齐，需作者提供" % "、".join(missing_items)
        )
    if empty:
        result["uncertainty"].append("方法骨架中这些部分没有素材支撑：%s" % "、".join(empty))

    compressed, words = _compress(text)

    status = "success" if len(empty) <= 1 else "partial"

    return {
        "status": status,
        "skill_name": SKILL,
        "text": compressed,
        "document": {"source": name, **textops.wc(text)},
        "method_skeleton": skeleton,
        "reproducibility": {"checklist": checklist, "missing": missing_items},
        "compressed_300w": {"text": compressed, "words": words},
        "evidence": [],
    }
