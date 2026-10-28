# 仓库约定

## 提交信息

不要添加 `Co-Authored-By` 署名行。提交作者与提交信息只写本仓库维护者，不要附加任何 AI 协作标注或生成工具署名。

## 提交语言

提交信息用中文，格式为 `类型: 简述`。类型沿用 feat、fix、docs、chore、test、refactor。正文说明改了什么、为什么改；没有必要的细节不必展开。

## 文档风格

- 中文正文里的数字、英文单词、指标名紧贴中文，不加空格。详见 `references/writing-style.md`。
- 指标名保留行业通用写法：ACOS、TACOS、ROAS、CPC、CTR、CPA 不翻译。
- 不写具体费率、后台按钮位置这类会随平台更新失效的内容，写判断原则。

## 改动前的检查

- 改 `scripts/render_report.py` 后跑 `python -m unittest discover -s tests -v`。
- 改示例数据或报告结构后重新生成 `examples/sample-report.pdf`，并逐页检查分页、表头重现和图表。
- 新增参考文件时同步更新 `SKILL.md` 的「按需参考」表和 `README.md` 的目录结构。
