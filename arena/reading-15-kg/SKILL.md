---
name: paper-kg
description: 从科研 PDF 构建带出处的知识图谱：实体（方法/数据集/指标/概念）、关系（提升/降低/优于/组成/相比）、以及同一对实体被相反断言时的冲突标注。当需要把多段正文组织成可审计的实体-关系表、而不是读一段概括时使用。
---

# paper-kg（阅读15｜文献知识图谱构建）

图谱的每条边都能指回**产生它的那句话和那一页**。规则可见、可改、可测，比一个不透明的抽取结果更适合做知识沉淀。

## 它解决的问题

把论文"读成图谱"最容易出的问题是：

1. **实体合并错**：`Transformer` 与 `transformer` 被当成两个节点，或两个不同模型被合并。
2. **关系无证据**：图上有一条"X 提升 Y"的边，却找不到原文依据。
3. **冲突被抹平**：同一对实体在不同章节被断言提升与降低，图谱只留了其中一条。

本 Skill 做大小写归一以合并同义实体，每条边保留 `sentence`/`page`/`evidence`，并对同源实体的极性冲突单独标注。

## 用法

```bash
python3 src/run_case.py --case input/case.json --out work
```

## 输出字段

| 字段 | 含义 |
|---|---|
| `entities[]` | `id` / `label` / `kind`（method·dataset·metric·concept）/ `mentions` / `pages` / `evidence` |
| `relations[]` | `source` / `target` / `relation` / `sentence` / `page` |
| `graph.kinds` | 各类型实体计数，用来判断抽取是否失衡 |
| `graph.conflicts[]` | 同一对实体同时出现 `improves` 与 `reduces` 的极性冲突 |

关系标签：`improves`、`reduces`、`outperforms`、`requires`、`composed_of`、`compared_with`、`is_a`。

## 怎么判断质量

- `node_count` 高但 `edge_count` 低 → 实体抽到了，谓词没匹配上，图谱退化成实体表（会写进 `uncertainty`）。
- `mentions <= 1` 的实体被点名，单次提及不足以支撑关系。
- `conflicts` 非空时不要直接采信，先看原句。

## 限制

- 实体抽取基于大写词形与缩写规则，**全小写照排的文本会漏抽**。
- 关系只覆盖 7 类谓词，复杂句式（嵌套、双重否定）会漏。
- 不解析表格内部结构，表格里的关系可能丢失。
- 冲突检测只看极性，不判断两个断言是否针对不同设定（例如不同数据集），需人工裁定。

## 最小示例

```bash
python3 src/run_case.py --case demo/case.json --out work
```

输出 `node_count`、`edge_count`、类型分布，以及被标出的低证据实体。
