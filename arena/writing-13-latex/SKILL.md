---
name: latex-check
description: 不编译就检查 LaTeX 源码：花括号/环境是否配对、\ref 指向的 label 是否存在、\cite 是否在 .bib 里有条目、表格是否缺 \centering/\caption、公式是否缺 \label、中文标点是否混入拉丁文；自动修空白与 \cite 键列表，其余给行号补丁。当投稿前要快速排掉会导致编译失败或显示 ?? 的问题时使用。
---

# latex-check（写作13｜LaTeX 写作与编译）

不跑编译器，因此结果是**确定性**的：每条问题都能用 grep 在源码里复现。

## 用法

```bash
python3 src/run_case.py --case input/case.json --out work
```

`inputs` 需给 `.tex`；有 `.bib` 会一并核对。纯 PDF 输入会被拒绝并说明原因。

## 会阻断编译的问题

| 检查 | 说明 |
|---|---|
| `unbalanced_brace` | `{` / `}` 不配对 |
| `unbalanced_environment` | `\begin{x}` 与 `\end{x}` 数量不一致 |
| `undefined_refs` | `\ref` 的目标 label 不存在（显示 ??） |
| `cites_missing_in_bib` | `\cite` 的键在 .bib 里没有 |

## 只影响观感的问题

`missing_centering`（表格/图未居中）、`table_without_caption`、`bare_hline_in_table`（未用 booktabs）、`equation_without_label`、`fullwidth_punct_in_latin`、`empty_ref`。

## 自动修的四类

合并多余空行、去行尾空白、合并连续空格、把 `\cite{a, b}` 规范为 `\cite{a,b}`。全部不改变内容。

## 输出字段

| 字段 | 含义 |
|---|---|
| `checks[]` | 结构与引用检查结果 |
| `style_issues[]` | 样式问题，带 `line` 行号 |
| `patches[]` | 可执行补丁清单（安全修正 + 待人工处理项） |
| `stats` | `blocking` / `style` / `auto_fixed` 计数 |
| `text` | 已应用安全修正的源码 |

## 限制（重要）

- **不做真实编译**：宏包冲突、字体缺失、`biblatex` 与 `bibtex` 流程差异都查不出来。
- 不校验参考文献条目真伪，只校验键是否对齐。
- 不解析 `\input` / `\include` 的子文件，多文件项目需逐个跑。
- 行号基于单文件，与合并后编译的行号不一致。

## 最小示例

```bash
python3 src/run_case.py --case demo/case.json --out work
```

输出 `blocking` 数量为 0 时，说明结构性错误已清空，可以进入编译阶段。
