# 构建与复现

构建对象是自定义 ARM 扩展。厂商 `.04` 仍是必要的二进制输入，仓库没有厂商完整源码，也没有重新构建其 USB 引导程序。

## 环境

本次在 Linux x86-64、Python 3 上复现。依赖固定为 `ziglang==0.17.1` 和 `unicorn==2.1.4`，见根目录 `requirements.txt`。其他系统的 Python 包可用性、编译产物一致性未在本次确认。构建脚本在可用时优先使用 Python 的 ziglang 包，避免无意调用不同版本的系统 Zig。

在仓库根目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 tools/fetch_stock.py
python3 tools/reproduce.py
```

下载脚本从厂商 HTTPS 地址取得 `.04`，并严格检查大小和 SHA-256。已有正确镜像时直接复用；已有文件不匹配时拒绝覆盖。

如果已自行从厂商取得原版，可跳过下载，直接执行：

```bash
python3 tools/reproduce.py --stock /path/to/Ver.04.bin
```

官方输入必须满足：

```text
大小：13956 bytes
SHA-256：28c30d003a8b2a399cf7c019dfc400dcae751c24dc17bc653f325244a3310c09
```

## 执行内容

`tools/reproduce.py` 会依次：

1. 核对输入镜像与依赖版本。
2. 从 `history/0.51` 至 `history/0.54` 编译旧扩展，核对固定输出哈希，将对照镜像放到 `src/baseline/`。
3. 用 `src/build.py` 生成六个镜头预设并编译 0.55，将扩展放进原版镜像的固定区域。
4. 核对 0.55 与当前发布 BIN 的大小和 SHA-256 一致。
5. 运行 `src/verify.py`，执行真实编译的 ARM 指令，要求全部 8208 项检查通过。

所有操作只读写电脑中的文件，不连接或写入接环。旧镜像只作为仿真对照；尤其不要刷入有已知控制缺陷的 0.51。

主要输出：

| 路径 | 用途 |
| --- | --- |
| `src/dist/GTE_ALL_EXP055.bin` | 本次重建的可刷镜像，应与发布文件逐字节相同 |
| `src/dist/manifest.json` | 构建策略、补丁位置和哈希 |
| `src/dist/verification.json` | CPU 检查结果 |
| `src/build/patch.elf` | 自定义扩展的 ELF 与调试信息 |
| `src/build/symbols.json` | 符号地址 |
| `src/baseline/` | 自动构建的历史仿真对照，不作为安装推荐 |

`build/`、`dist/`、原版镜像和临时对照文件已加入忽略规则。`release/v0.55-exp/` 则是固定的发布文件。

## 单独执行

```bash
python3 tools/prepare_baselines.py vendor/Ver.04.bin
python3 src/build.py vendor/Ver.04.bin
python3 src/verify.py vendor/Ver.04.bin
```

单独运行 `build.py` 后的 manifest 中，硬件测试字段描述构建过程的证据范围；后续用户反馈见 `release_status.json` 和 [VALIDATION.md](VALIDATION.md)。`hardware_tested: false` 也明确表示 CPU 仿真程序没有操作实物。

## 保持发布文件一致

本次只整理公开仓库和文档，没有改写 0.55 的控制逻辑或 BIN。编译器选择顺序仅用于优先选择固定依赖，不影响本次镜像字节。若修改源码或工具链，先保留旧版，重新核对生成的镜像、地址布局、保护条件和实际测试结果，再使用新的版本号发布；不要以相同文件名静默替换已发布镜像。
