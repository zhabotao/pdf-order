---
name: pdf-order
description: 从 PDF 提取正文并还原多栏阅读顺序，输出带页码与 bbox 证据的结构化 JSON。当需要把论文/技术 PDF 的正文、章节、表格文字按原版面顺序转成可复核的结构时使用。Use when an agent must read a PDF into text whose reading order, page anchors and per-block evidence can be verified.
---

# pdf-order

把一份 PDF 读成「按原版面顺序排列的文本块」，每块都带页码和 bbox，便于回到原文核对。

只用 Python 标准库，不依赖 PyMuPDF、pdfplumber、pdfminer 等第三方包。

## 何时用

- 要把论文、报告、扫描前处理过的 PDF 转成可下游处理的文本或结构化字段。
- 关心**阅读顺序**：双栏/多栏论文按 y 排序会串栏，必须按栏切分。
- 关心**可核验**：结论需要能指回页码与页面区域，而不只是一段"看起来像全文"的文本。

不适合：纯图片、无文字层的扫描件（会如实报告 `uncertainty`，不会猜字）。

## 输入 / 输出

输入：一个 PDF 文件路径。

输出：一个 JSON 对象，主要字段：

| 字段 | 含义 |
|---|---|
| `input_id` | 输入标识：文件名 + 内容 sha256 前 12 位 |
| `status` | `success` / `partial` / `failed` |
| `page_count` | 实际输出的页数 |
| `text_char_count` | 提取到的正文字符数 |
| `pages[]` | 每页的 `layout.columns`（栏数）、`layout.order`（排序方法）与 `blocks[]` |
| `pages[].blocks[]` | 每块含 `id`、`order`、`bbox`（页面坐标）、`font_size`、`text`、`line_count` |
| `text` | 拼接后的全文（`--no-text` 可关闭） |
| `warnings` | 解析层面的异常（文件损坏、无文字层等） |
| `uncertainty` | 逐页的不确定项，例如「第 3 页无可提取文字层」 |

`bbox` 采用 PDF 用户空间坐标，原点在页面左下角。

## 怎么用

```bash
python3 src/pdf_parse.py input.pdf -o out.json
```

常用参数：

```bash
python3 src/pdf_parse.py input.pdf --max-pages 5 --no-text      # 快速看前 5 页
python3 src/pdf_parse.py input.pdf -o out.json --quiet          # 脚本里调用
```

退出码：`0` 表示 success 或 partial，`1` 表示 failed，`2` 表示文件不存在。

## 评测运行时接口（case.json → result.json）

任务运行时会把输入放在 `/input/case.json`（同目录通常还有 `task.md`），并要求把最终结果写到 `/app/output/result.json`。用适配层对接这个契约：

```bash
python3 src/run_case.py
# 等价默认值：--case /input/case.json --out /app/output
```

它做四件事：

1. 读 `case.json`，递归找出所有以 `.pdf` 结尾的路径，相对路径按 case 文件所在目录解析；找不到时回退到 case 目录下的 `*.pdf`。
2. 对每个 PDF 调用 `extract()`，逐份写出 `parse_<文件名>.json` 供复核。
3. 汇总成 `result.json`：`case_id`、`status`、`documents[]`、`text`、`evidence[]`（页码 + bbox + 文本指纹）、`warnings[]`、`uncertainty[]`。
4. 若 `case.json` 带 `output_contract`，把其中可映射的字段（`text` / `pages` / `blocks` / `reading_order` / `layout` / `evidence` / `status`）**填成实际值**；无法可靠生成的字段置 `null`，并列入 `unresolved_contract_fields` 加进 `uncertainty` —— 不猜、不编。

输入缺失时不会崩：写出一份 `status: failed` 的 `result.json` 并以退出码 `1` 结束。

**不会**假定标签即是内容：只读真实存在的文件；读不到就记进 `warnings`。

## 原理（三句话）

1. 自己解析 PDF 对象、内容流与 ToUnicode CMap，得到每个文本片段的文字、坐标与字号。
2. 按基线聚成行；**同一行内横向间隙超过约 0.9 em 就切开**，否则两栏文字会被拼成一句。
3. 递归 XY-cut 排序：找「只有少数行跨越」的窄带作为栏缝切开；双栏页最后做一次稳定分区，保证左栏全部在右栏之前。

## 限制（请如实对待）

- **扫描件/纯图 PDF 没有文字层**：返回 `status: failed` 或该页记入 `uncertainty`，不输出猜测内容。
- **矢量轮廓文字**（文字被转成曲线）：同样提取不到，会报告出来。
- 字体缺 `/Widths` 时退化为平均字宽估算，行尾位置可能有偏差，跨栏判断可能受影响。
- 图片、表格线、公式的**结构**不做识别，只按文本块处理；阅读顺序围绕文字，不围绕图表理解。
- 跨栏图表所在的页，局部顺序仍可能不准；每块的 bbox 可用于人工复核。
- 加密 PDF、对象流（`/ObjStm`）压缩的交叉引用表支持有限。

## 失败处理

- 文件不存在 → 退出码 2，stderr 提示，不产出文件。
- 解析抛异常 → 输出 `status: failed` 且 `warnings` 记录异常类型，**不会**返回半真半假的结果。
- 部分页无文字 → `status: partial`，其余页照常输出。

## 最小示例

```bash
python3 demo/make_sample.py            # 生成示例输入 demo/sample.pdf
python3 src/pdf_parse.py demo/sample.pdf -o sample.json
python3 -c "import json;d=json.load(open('sample.json'));print(d['pages'][0]['layout']['columns']);print([b['text'][:40] for b in d['pages'][0]['blocks']][:4])"
```

示例 PDF 是一页双栏排版，正确输出应为：标题 → 左栏三段 → 右栏三段 → 页码，且 `layout.columns` 为 2。
