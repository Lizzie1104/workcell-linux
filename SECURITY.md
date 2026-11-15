# 安全边界与排错

此基础版用于普通用户的离线批处理任务。启动依赖用户、挂载、PID、IPC、网络和UTS命名空间，丢弃能力并加载seccomp限制。保护准备失败时停止，不自动降级到宿主执行或开启联网。

工作区只有独立HOME、`/workspace`、只读系统工具/库、私有临时目录及最小设备。环境变量从固定值建立；宿主代理、SSH代理、登录HOME、D-Bus、显示、音频和Windows磁盘不传入。任务输出作为过滤后的文字输出，标准输入和交互终端不传入。

这仍共享宿主Linux内核，不能代替独立虚拟机；宿主管理员及同一宿主UID下的程序属于可信边界。没有独立磁盘/内存配额，任务可能耗尽所在账户的资源。不要在同一工作区放入账号、密钥、私人文件或其他项目。新网络命名空间和系统调用限制均关闭联网，因此无法直接运行需要在线服务的Claude等AI客户端。

常见处理：

- 找不到bwrap/libseccomp：按README通过官方软件源安装依赖，不下载陌生替代执行文件。
- 用户命名空间、AppArmor或管理员策略拒绝：保留错误，让系统管理员核对该系统对发行版bubblewrap的支持。不使用sudo运行本程序，不全局关闭AppArmor或修改内核策略绕过。Ubuntu24.04的`loopback: Failed RTM_NEWADDR`可能表示缺少bubblewrap专用AppArmor配置，准备步骤见下文。
- 状态目录权限、链接或配置不正确：使用新空目录验证；原数据保留，不通过递归chmod/chown或删除目录修复。配置只接受示例中的固定字段。
- 文件找不到：先复制到宿主状态目录的workspace，再使用工作区内的 `/workspace` 路径。宿主绝对路径不会自动映射。
- 任务超时：已关闭本次工作区进程；HOME/workspace仍保留。确认任务用途后调整 `--timeout`，不要将中断误认为回退文件。

反馈时提供基础版版本、Linux发行版、依赖版本和错误类型。不要在公开Issue粘贴凭据、私人文件或原始敏感日志。发现安全问题时先使用GitHub提供的私密漏洞报告入口（若已启用），不要公开利用所需的私人数据。

## Ubuntu24.04的用户命名空间支持

如果`doctor`报告上述AppArmor错误，由管理员先查看`sudo aa-status`和已有的`/etc/apparmor.d/*bwrap*`。已有匹配规则时让管理员检查，不叠加覆盖其他软件的规则。

只有确认本机没有匹配规则，且同意为系统bubblewrap加载发行版提供的专用规则时，才执行：

```bash
sudo apt install apparmor-profiles
test -f /usr/share/apparmor/extra-profiles/bwrap-userns-restrict
test ! -e /etc/apparmor.d/bwrap-userns-restrict
sudo install -m 0644 /usr/share/apparmor/extra-profiles/bwrap-userns-restrict /etc/apparmor.d/bwrap-userns-restrict
sudo apparmor_parser -r /etc/apparmor.d/bwrap-userns-restrict
```

任一步失败就停止；此规则限定系统`/usr/bin/bwrap`，影响其他使用同一bubblewrap的工具，属于管理员的系统设置选择。保持全局AppArmor和`kernel.apparmor_restrict_unprivileged_userns`原值，程序本身不会修改这些设置。完成后回到普通用户运行`doctor`。若管理员不允许这项准备，此系统暂不能运行本基础版。
