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

# 查看当前哪些文件被混淆：
junk status

# 逐字节还原：
junk restore
```

### 命令

| 命令 | 作用 |
| --- | --- |
| `obfuscate PATHS [--aggressive] [--tests CMD] [--bench CMD] [--seed N] [--dry-run]` | 快照、变换、过 gate，失败则回滚。 |
| `restore [PATHS]` | 从 `.junkmap/` 还原原版（省略则还原全部被管理的文件）。 |
| `status [PATHS]` | 显示哪些文件被混淆、是否完好。 |
| `redteam PATHS [--rounds N] [--model ID]` | 用 Claude 当「抗还原」适应度函数，挑出最难还原的变体再走 gate 套用。需要 `ANTHROPIC_API_KEY`。 |

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
  transforms.py  # AST 变换：死代码、安全改名、顶层重排
  poison.py      # 误导 docstring（AST）+ 注释（文本注入）
  gates.py       # 编译 + 测试 + 基准 校验
  redteam.py     # Claude 当适应度的种子搜索
```

## 测试

```bash
python -m pytest -q
```

覆盖三条核心保证：往返字节一致、gate 失败自动回滚、二次混淆被拦。

## 许可证

MIT，见 [LICENSE](./LICENSE)。
