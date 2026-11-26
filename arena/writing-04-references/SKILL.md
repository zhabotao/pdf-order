---
name: ref-reconcile
description: 核对参考文献与正文引用是否自洽：抽取列表、检测编号风格混用、找出正文引用了但列表缺失（或列表有但正文未引）的编号、去重、标出缺 DOI/缺年份条目，并导出可编译的 BibTeX。当投稿前需要确认"每个引用都指得着"时使用。
---

# ref-reconcile（写作04｜参考文献与引用管理）

引用错位是**静默错误**：`[12]` 还在文里，但列表第 12 条已经被人删了，编译不报错，评审却看不到那篇文献。

## 用法

```bash
python3 src/run_case.py --case input/case.json --out work
```

支持两种输入：`.tex`（解析 `\bibitem`）或 PDF（定位 References 章节并按 `[n]` / `n.` 切条）。

## 输出字段

| 字段 | 含义 |
|---|---|
| `references[]` | 逐条 `raw` / `year` / `doi` / `page` / `bbox` |
| `reconciliation` | `cited_not_listed`、`listed_not_cited`、双向计数 |
| `style` | `bracketed` / `dotted` 计数，`mixed=true` 表示编号风格混用 |
| `duplicates[]` | 判定为重复的条目对 |
| `quality` | 缺 DOI、缺年份的条目序号 |
| `text` | 可直接编译的 BibTeX |

## 判定口径

- **重复**：DOI 相同，或去掉标点小写后的前 60 字符相同。
- **引用编号**：识别 `[1,3-5]`、`（1）` 等形式，区间会展开。
- **自洽**：只有当 `cited_not_listed` 为空才算通过，否则 `status` 为 `partial`。

## 限制（重要）

- PDF 的参考文献抽取依赖章节标题可识别且条目以 `[n]` / `n.` 起头；双栏、无编号、悬挂缩进异常时会漏条，**表现为 `cited_not_listed` 偏多**——这时应先看原文，而不是直接采信报告。
- DOI 只做正则识别，不联网校验真伪。
- BibTeX 字段是尽力而为（author/title/year/doi），期刊卷页等需人工补全。
- 不做格式转换（APA ↔ GB/T 7714），只核对自洽性与风格一致性。

## 最小示例

```bash
python3 src/run_case.py --case demo/case.json --out work
```

输出 `references` 条数与 `reconciliation` 双向差异；`text` 字段是生成的 BibTeX。
