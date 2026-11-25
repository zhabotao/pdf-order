# pdf-order

零依赖 PDF 正文提取与多栏阅读顺序还原。

- 只用 Python 标准库（3.8+），不需要 PyMuPDF / pdfplumber / pdfminer。
- 输出带页码与 bbox 的结构化 JSON，便于回到原文核验。
- 双栏论文按栏切分，不会把左右栏拼成一句。

## 快速开始

```bash
python3 demo/make_sample.py                  # 生成示例输入
python3 src/pdf_parse.py demo/sample.pdf -o out.json
```

或直接跑端到端复现脚本：

```bash
python3 src/reproduce.py                     # 产出 results/
```

## 目录

| 路径 | 说明 |
|---|---|
| `SKILL.md` | Skill 定义：用途、触发条件、输入输出、限制 |
| `src/pdf_parse.py` | 解析器与命令行入口 |
| `src/run_case.py` | 评测运行时适配：`/input/case.json` → `/app/output/result.json` |
| `src/reproduce.py` | 端到端复现脚本，产出 `results/` |
| `demo/make_sample.py` | 生成示例 PDF（无第三方内容） |
| `demo/sample.pdf` | 示例输入：一页双栏排版 |
| `demo/case.json` | 示例 case，演示运行时契约 |
| `results/` | 上次真实运行的产物与日志 |

## 为什么需要它

多数 PDF 提取工具按纵坐标排序文本，遇到双栏论文会左右交替输出，得到「句子从一栏开头、在另一栏结尾」的文本。下游的翻译、问答、结构化都会因此出错，而且这种错误很难察觉。

本 Skill 的做法：

1. 解析 PDF 对象、内容流与 ToUnicode CMap，拿到每段文字的坐标与字号；
2. 按基线聚行，**同一行内横向间隙超过约 0.9 em 就切开**；
3. 用递归 XY-cut 找「只有少数行跨越」的窄带作为栏缝；
4. 双栏页最后做一次稳定分区，保证左栏全部先于右栏。

## 已知限制

- 无文字层的扫描件、矢量轮廓文字：不会猜字，记入 `uncertainty` 或返回 `failed`。
- 字体缺 `/Widths` 时按平均字宽估算，行尾位置可能有偏差。
- 图表、公式的结构不识别，只做文本块切分。
- 跨栏图表所在页可能仍有局部顺序问题；每块 bbox 可用于人工复核。
- 加密 PDF 与 `/ObjStm` 压缩交叉引用表支持有限。

## 运行环境

Python 3.8 及以上，无第三方依赖。Windows / Linux / macOS 均可。
