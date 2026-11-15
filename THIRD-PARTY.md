# 第三方依赖与材料

本仓库发行自有Python源码和配置，不携带Linux镜像、第三方可执行文件、库或上游源码修改。运行依赖通过用户的Ubuntu官方软件源安装。自有MIT许可不改变这些组件的许可。

|依赖|用途|许可/来源|
|---|---|---|
|CPython 3.12+|运行入口和本地Python任务|[PSF及其随附许可](https://github.com/python/cpython/blob/3.12/LICENSE)|
|bubblewrap 0.9.0+|创建工作区命名空间|[LGPL-2.0-or-later](https://github.com/containers/bubblewrap/blob/v0.9.0/COPYING)|
|libseccomp2|生成系统调用过滤器|[LGPL-2.1及原项目条款](https://github.com/seccomp/libseccomp/blob/v2.5.5/LICENSE)|
|Ubuntu系统工具|用户选择运行的Shell/Python等命令|各软件包自身许可；以本机`/usr/share/doc/<包名>/copyright`为准|

单独的 `workcell-linux-0.1.0-third-party-materials.zip` 位于本仓库[发行页面](https://github.com/Lizzie1104/workcell-linux/releases/tag/v0.1.0)。其中包含依赖许可原文、来源和材料范围；无需激活码。

需要系统依赖的精确对应源码时，以用户实际安装版本为准：

```bash
dpkg-query -W python3.12 bubblewrap libseccomp2
```

启用Ubuntu官方源码源后，可在单独目录使用 `apt source python3.12 bubblewrap libseccomp` 获取本机源配置选择的源码，并核对源码版本与上面输出匹配。Ubuntu源码包通常含发行版补丁，不能把上游同名标签当作所有发行版二进制的完整对应源码。

如果以后再分发这些依赖的二进制或修改版，应按实际版本另附相应许可、完整对应源码及必要修改/构建材料。本基础版的材料不替代WorkCell Desktop及其他产品已有的第三方交付义务。
