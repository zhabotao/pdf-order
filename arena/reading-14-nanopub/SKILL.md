---
name: claim-nanopub
description: 从科研 PDF 中抽取可归属的断言，打包成 nanopublication 三段结构（assertion / provenance / publication），每条断言保留页码、bbox 与原文句子。当需要把论文结论拆成可引用、可追溯、可拒信的最小知识单元时使用。
---

# claim-nanopub（阅读14｜Nanopublication）

Nanopublication 的价值在于**断言比论文小、出处比断言硬**。所以这里只做两件事：把句子识别成可归属的断言，并把它的出处钉死。

## 它解决的问题

直接摘句当结论，有三个隐患：

1. **无出处**：读者无法判断这句话是本文发现，还是转述别人的工作。
2. **混层级**：把"我们计划尝试"与"我们在三个数据集上验证"写成同一力度。
3. **不可拒信**：没有置信度与失败边界，下游无法知道该不该信。

本 Skill 的每条断言都带 `citations`（原文文献标记）、`quantities`（数值）、`confidence`，并区分"有引文支撑"与"仅为正文陈述"。

## 用法

```bash
python3 src/run_case.py --case input/case.json --out work
```

## 输出结构

```json
{
  "nanopublication": {
    "assertion":  { "claims": [...], "relations": [...], "claim_count": 0, "relation_count": 0 },
    "provenance": { "source_document": "", "extraction": {...}, "derived_from": {...} },
    "publication":{ "nanopub_id": "np:...", "generated_at": "...", "license_note": "..." }
  }
}
```

| 字段 | 含义 |
|---|---|
| `claims[].assertion` | 原句，未改写 |
| `claims[].citations` | 句中出现的文献标记 |
| `claims[].quantities` | 句中的数值 |
| `claims[].confidence` | 由断言线索、数值、引文共同决定的 0–1 值 |
| `claims[].evidence` | `page` / `bbox` / `para` |
| `relations[]` | `improves` / `is_a` / `depends_on` 关系，附原句 |

## 置信度怎么来的

基线 0.4；命中断言线索（`we show / propose / 实验表明`）+0.3；含数值 +0.15；含文献标记 +0.1；上限 0.95。低于 0.55 的会在 `uncertainty` 里点名，建议人工确认后再对外发布。

## 限制（重要）

- **抽取式**：不重述、不归纳，因此长句会原样保留。
- 无可见文献标记的断言会被标出来——它们依赖正文陈述，不等同于有引文支撑。
- 关系抽取是规则匹配，只覆盖少数谓词，召回有限；`graph.relation_count` 可用来判断是否够用。
- 不判断断言是否与文献实际结论一致，只保证"原文确实这么写过"。
- 再分发断言文本前请确认原文许可，`publication.license_note` 已提示。

## 最小示例

```bash
python3 src/run_case.py --case demo/case.json --out work
```

输出 `claim_count`、`relation_count`，以及被标出的低置信度断言。
