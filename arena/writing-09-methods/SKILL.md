---
name: method-audit
description: 从已有结果与草稿反推方法章节骨架（数据 / 模型 / 训练配置 / 评测 / 基线），做可复现性清单核对并点名缺项，同时给出 300 词压缩版。当要把"实际跑过什么"写成方法章节、又不想漏掉关键配置时使用。
---

# method-audit（写作09｜方法与实验章节写作）

方法章的价值在于**别人能否照着重跑**。所以本 Skill 的产出不是漂亮段落，而是"哪五项里还缺哪项"。

## 用法

```bash
python3 src/run_case.py --case input/case.json --out work
```

输入为 `.tex` / `.md` / `.txt` 草稿或 PDF 论文。

## 五个必填项

| 部分 | 抽取线索 |
|---|---|
| 数据 | 数据集名 + "dataset" / "数据集" 邻近词 |
| 模型 | 参数量（160M/7B）、模型族（Transformer/GPT/BERT） |
| 训练配置 | learning rate / batch size / epochs / 学习率 等 |
| 评测 | perplexity / accuracy / F1 / BLEU / 准确率 等 |
| 基线 | baseline / compared with / 基线 / 对比 |

## 可复现性清单

除上述五项外还核对：**随机种子与重复次数**、**算力与训练时长**。

未命中的项进入 `reproducibility.missing` 并写进 `uncertainty`——这些项**不会被推测补齐**，因为填错比留空更糟。

## 输出字段

| 字段 | 含义 |
|---|---|
| `method_skeleton[]` | 各部分抽到的条目与写作建议 |
| `reproducibility` | 清单逐项 `found`，以及 `missing` 列表 |
| `compressed_300w` | 抽取式 300 词压缩版（保留方法线索句） |
| `text` | 压缩版正文 |

## 限制

- **抽取式压缩**：300 词版是从原文挑句拼接，不是重写，语句间可能不连贯，需人工润色。
- 超参若只存在表格里，PDF 抽取后可能匹配不到，表现为 `missing` 偏多——请核对原文表格。
- 不判断方法是否合理，只核对"是否写全"。
- 中英文线索词都有，但混排文本可能重复计数。

## 最小示例

```bash
python3 src/run_case.py --case demo/case.json --out work
```

输出给出五项各自条目数、缺项清单与压缩版词数。
