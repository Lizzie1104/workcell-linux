# WorkCell Linux 基础版

免费的 Linux 离线命令行工作区。用普通用户运行本地 Python、Shell 等批处理任务，只保留独立的 HOME 和 `/workspace`；不需要激活码。

首发版本 **0.1.0**，目标 **Ubuntu 24.04 / x86_64**。需要 Python 3.12+、bubblewrap 0.9.0+、libseccomp2 和可用的非特权用户命名空间。其他发行版和 WSL 尚未实测。验证记录见[发行说明](https://github.com/Lizzie1104/workcell-linux/releases)。

Ubuntu24.04默认AppArmor策略可能要求管理员先启用发行版的bubblewrap专用规则；遇到`RTM_NEWADDR`或用户命名空间拒绝，按[系统准备说明](SECURITY.md#ubuntu2404的用户命名空间支持)处理。

## 开始使用

先通过 Ubuntu 官方软件源准备依赖；只有这一步使用 sudo 和系统网络：

```bash
sudo apt update
sudo apt install --no-install-recommends python3 bubblewrap libseccomp2 git
git clone https://github.com/Lizzie1104/workcell-linux.git
cd workcell-linux
python3 -I -S -B workcell_linux.py init
python3 -I -S -B workcell_linux.py doctor
```

以普通用户运行任务：

```bash
python3 -I -S -B workcell_linux.py run -- python3 -c 'from pathlib import Path; Path("hello.txt").write_text("你好，WorkCell\n"); print(Path("hello.txt").read_text())'
python3 -I -S -B workcell_linux.py run -- bash -c 'pwd; ls -la; printf "saved\n" > "$HOME/note.txt"'
python3 -I -S -B workcell_linux.py status
```

宿主上的文件在 `~/.local/share/workcell-linux/workspace/`，应用 HOME 在同一状态目录的 `home/`。可把需要处理的普通文件复制进 workspace，运行结束后在这里取结果。重复运行和再次执行 `init` 会保留已有文件；没有自动清理功能。

用 `--state /绝对路径` 选择另一份独立状态目录，并在后续命令中使用同一路径：

```bash
python3 -I -S -B workcell_linux.py --state "$HOME/workcell-demo" init
python3 -I -S -B workcell_linux.py --state "$HOME/workcell-demo" run --timeout 60 -- python3 -c 'print("ready")'
```

`init` 会创建权限为700的状态目录及600的 `config.json`；配置格式见[示例](config.example.json)。本版固定断网，不接受额外挂载或联网开关。标准输入关闭，默认最长300秒、最多64MiB终端输出；长任务可指定1–86400秒，大量结果写入 `/workspace`。返回值保留子命令退出码；基础版自身检查失败返回2。

## 范围

本仓库提供独立的离线命令行基础功能，版本与 WorkCell Desktop 分开维护。联网AI服务、桌面/无缝窗口、Windows面板、音频/剪贴板、两跳网络配置和产品自动更新不包含在此发行中。WorkCell Desktop 用户继续使用原产品入口，避免在现有工作环境里叠加安装实验版本。

只把本次任务需要的文件放进工作区。宿主系统工具目录只读挂载，其他宿主 HOME、`/etc`、设备、桌面和服务套接字不加入工作区。应用的写入和删除会作用于这份 HOME/workspace；退出不会撤销这些写入。边界和常见失败见[安全与排错](SECURITY.md)。

自有源码使用 [MIT](LICENSE)。第三方依赖保持各自许可，由系统软件源安装；许可说明及单独材料入口见[第三方说明](THIRD-PARTY.md)。
