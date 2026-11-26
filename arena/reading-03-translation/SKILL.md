---
name: citation-translate
description: 把英文科研 PDF 逐段译成中文，输出段落级双语对照，并机械核验数字、单位、文献编号、公式编号与术语一致性。当需要把一篇论文翻译成可核对的中文版本、而不是一段读起来通顺的概括时使用。
---

# citation-translate（阅读03｜文献翻译）

翻译由 Agent 完成，但**段落清单、术语锁定、译后核验**由脚本负责——这三件事恰好是模型最容易悄悄做错的地方。

## 它解决的问题

翻译长论文时有三种错误很难被发现：

1. **漏段**：跨页、跨栏处少译一段，读起来通顺，实际信息缺失。
2. **术语漂移**：同一个 `attention` 在摘要译作"注意力"、正文译作"关注度"。
3. **事实丢失**：数字、单位、文献编号、公式编号在翻译中变形。

本 Skill 把段落先编号锁死，再用术语表强制替换，最后逐段比对源文与译文中的受保护符号。

## 用法

### 第一步：抽取对齐原文

```bash
python3 src/run_case.py --case input/case.json --out work
```

输出 `/app/output/result.json`，其中 `bilingual[]` 是逐段清单：每段带 `id`、`page`、`bbox`、`source`、`protected`（该段必须保留的数字/单位/引用/公式编号）。

把 `bilingual[i].translation` 按顺序填好，存回 case：

```json
{
  "case_id": "...",
  "inputs": [{"role": "paper", "path": "paper.pdf"}],
  "glossary": {"attention": "注意力", "perplexity": "困惑度"},
  "translations": ["第一段译文", "第二段译文", "..."]
}
```

### 第二步：回填并核验

```bash
python3 src/run_case.py --case input/case.json --out work
```

此时进入 assemble 模式，输出带核验结果的双语对照。

## 输出字段

| 字段 | 含义 |
|---|---|
| `bilingual[]` | 逐段 `source` / `translation` / `status` / `evidence(page,bbox)` |
| `bilingual[].status` | `ok` / `needs_review`（受保护符号丢失）/ `untranslated` |
| `bilingual[].lost` | 丢失的具体数字、单位、引用或公式编号 |
| `audit` | 段数、已译、待复核、未译、术语命中数 |
| `glossary_unmapped` | 高频但还没有指定译名的术语，必须先定名 |

## 术语表规则

- `case.glossary` 里给出的译名是**强制**的，命中即替换，不做同义改写。
- 未在表中但在原文出现 ≥2 次的候选术语会进入 `glossary_unmapped`，提醒先定名再译，避免边译边造词。

## 限制（如实说明）

- 不内置机器翻译，译文由 Agent 产出；本 Skill 保证结构、一致性与可核验性。
- 扫描件、无文字层 PDF 无法抽取，会在 `uncertainty` 里说明。
- 公式只比对编号与符号，不判断公式语义是否正确。
- 段落切分依据版面（字号与行距）判断，极端排版下可能把标题并入正文。

## 最小示例

```bash
python3 src/run_case.py --case ../../skill/demo/case.json --out work
```

示例 case 只有一段双栏演示文本，输出会显示逐段清单与 `glossary_unmapped`，`status` 为 `partial`（尚未提供译文）。
