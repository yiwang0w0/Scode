# junk（可逆「屎山化」混淆工具）

把干净的 Python 源码膨胀成一座**故意写烂的屎山**，抬高随手阅读与被自动化工具
解构的成本——然后用一条命令把原版**逐字节**还原回来。

> [English → README.md](./README.md)

## 为什么可以放心地激进

junk **从不解析屎山版来还原**。动手之前，它先把每个原始文件的**逐字节快照**写进
本地、且被 git 忽略的 `.junkmap/` 目录。`junk restore` 直接把这些字节写回去。由于
还原完全无视混淆后的产物，变换可以任意激进，**零信息损失**。

另外两道保险让你不会翻车：

- **AST 级、行为保持的变换**：误导性 docstring、不可达死代码、可证明安全的局部改名
  （绝不碰参数 / 全局 / 闭包 / 反射），以及顺序无关的顶层重排。
- **双 gate + 自动回滚**：混淆后会重新编译每个文件，并（可选）运行**你自己的**
  测试 / 基准命令。任一失败，自动把所有文件回滚到干净快照。

## Agent 迷宫模式

默认变换给每个文件撒的都是同一批泛泛 stock 注释——一个会跨文件交叉引用的 AI agent
很快就学会把它们当噪声忽略。`--narrative` 反其道而行：构造**一个编造但内部自洽的
封面故事**，并渲染进**每一个**表面——注释、docstring、死代码命名、诱饵
`ARCHITECTURE.md`、乃至测试名——全部挂在同一份 glossary 上，同一个实体在任何地方都
拿到同一个假身份。于是 agent 的交叉验证不但不揭穿，反而*确认*了这个谎，最终带着一份
**自信但错误**的理解走人。它攻击的是模型唯一无法从代码本身核验的轴：**为什么**。

```bash
# 在整棵树上渲染一个离线、确定性的封面故事：
junk obfuscate src/ --aggressive --narrative template --tests "python -m pytest -q"

# 同时重命名 test_* 函数、并把 README.md 改写进这个故事：
junk obfuscate src/ --aggressive --narrative template --rename-tests --rewrite-readme
```

故事写在 `.junkmap/narrative.json`（机密——它是钥匙的一部分），`restore` 会清掉它创建
的每个诱饵文件。行为与 gate 一字未动：叙事模式只改投毒**说了什么**，不改**怎么注入**。
`--narrative template` 现已可用、离线且确定；`--narrative llm`（用 Claude 把故事裁得
贴你真实结构）尚在规划。

### 迷宫到底有没有用？——`junk maze-eval`

诚实的适应度函数。它把混淆树丢给一个会用工具（`list_files` / `read_file` / `grep`）的
agent，量它的成本（轮数、工具调用、token），并用 `.junkmap` 里的原文当 ground truth，
判断 agent 是否**自信地错**、或把假域复述了出来。`--baseline` 会在重建的干净树上再跑
一遍，报告迷宫多带来的成本。需要 `ANTHROPIC_API_KEY`。

```bash
junk maze-eval --baseline
```

## 安装

```bash
pip install -e .            # 核心工具
pip install -e '.[redteam]' # 额外装 anthropic SDK，供 `junk redteam` 使用
```

## 用法

```bash
# 安全档（死代码 + 误导注释），默认：
junk obfuscate src/

# 全开，并用你的测试做 gate——失败就回滚：
junk obfuscate src/ --aggressive --tests "python -m pytest -q"

# Agent 迷宫模式：全仓共用一个自洽假叙事：
junk obfuscate src/ --aggressive --narrative template --tests "python -m pytest -q"

# 查看当前哪些文件被混淆：
junk status

# 逐字节还原：
junk restore
```

### 命令

| 命令 | 作用 |
| --- | --- |
| `obfuscate PATHS [--aggressive] [--narrative off\|template\|llm] [--narrative-theme T] [--rename-tests] [--rewrite-readme] [--tests CMD] [--bench CMD] [--seed N] [--dry-run]` | 快照、变换（可选渲染自洽假叙事）、过 gate，失败则回滚。 |
| `restore [PATHS]` | 从 `.junkmap/` 还原原版（省略则还原全部被管理的文件）；同时删除叙事创建的诱饵文档。 |
| `status [PATHS]` | 显示哪些文件被混淆、是否完好。 |
| `redteam PATHS [--rounds N] [--model ID]` | 用 Claude 当「抗还原」适应度函数，挑出最难还原的变体再走 gate 套用。需要 `ANTHROPIC_API_KEY`。 |
| `maze-eval [--task T] [--model ID] [--max-turns N] [--baseline]` | 让一个会用工具的 agent 翻混淆树，报告它的成本（轮数 / 工具调用 / token）以及是否被假叙事带偏。需要 `ANTHROPIC_API_KEY`。 |

## 用示例跑一遍

```bash
junk obfuscate example/sample.py --aggressive --tests "python example/run_checks.py"
junk status
junk restore
# example/sample.py 现在与初始状态完全一致
```

## ⚠️ 务必保密 `.junkmap/`

快照目录是你原始源码的总钥匙——谁拿到它，一条 `junk restore` 就能还原一切。junk 会
自动把 `.junkmap/` 写进 `.gitignore`；切勿提交或外发。

## 模块结构

```
junk/
  cli.py         # 参数解析 + 命令分发
  core.py        # 发现 -> 变换 -> 快照 -> gate -> 回滚/报告
  snapshot.py    # 逐字节的 .junkmap/ 快照库
  transforms.py  # AST 变换：死代码、安全改名、顶层重排、测试重命名
  poison.py      # 误导 docstring（AST）+ 注释（文本注入）
  narrative.py   # 跨文件封面故事：数据模型、主题、绑定、渲染器
  gates.py       # 编译 + 测试 + 基准 校验
  redteam.py     # Claude 当适应度的种子搜索
  maze_eval.py   # agent 成本 harness：迷宫到底有没有把 agent 绕住？
```

## 测试

```bash
python -m pytest -q
```

覆盖核心保证（往返字节一致、gate 失败自动回滚、二次混淆被拦），外加叙事层：
跨文件 / 跨表面一致性、确定性绑定、restore 删除诱饵文档，以及 maze-eval harness 的
离线部分（sandbox 屏蔽 `.junkmap`、上钩检测）。

## 许可证

MIT，见 [LICENSE](./LICENSE)。
