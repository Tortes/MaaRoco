<!-- markdownlint-disable MD033 MD041 -->
<p align="center">
  <img alt="LOGO" src="https://github.com/user-attachments/assets/d07ef4a0-5642-4a2a-94b8-4789e7323bdf" width="256" height="256" />
</p>

<div align="center">

# MaaRoco

</div>

> 本项目由 **[MaaFramework](https://github.com/MaaXYZ/MaaFramework)** 强力驱动！

一种基于MaaFramework的RocoWorld自动化脚本；

## 即刻开始

参考[MaaFw手册](https://github.com/MaaXYZ/MaaPracticeBoilerplate/blob/main/docs/zh_cn/develop/how_to_develop.md), 使用定制化的[MaaFramework Release](https://github.com/Tortes/MaaFramework/releases)替换原有`deps`目录框架动态库，以支持[Interception](https://github.com/oblitum/Interception)能力。

### 安装 Interception 驱动

`Win32-Interception` 控制器需要先安装 [Interception](https://github.com/oblitum/Interception) 驱动。请从本项目 [Latest Release](https://github.com/Tortes/MaaRoco/releases/latest) 下载 `MaaRoco-Interception-Installer.zip`，解压后以**管理员身份**运行 `tools/install_interception.cmd`。脚本会从 Interception 官方 Release 下载驱动并调用官方安装程序；安装完成后请重启 Windows。

该安装脚本仅支持 Windows。Interception 是内核级输入驱动，安装和使用前请确认其风险符合你的使用场景。

支持：
- [x] 随机/固定丢球模式；

TODO:
- [ ] 自动清理背包；
- [ ] 炫彩花种战斗；
- [ ] 炫彩花种炫彩扫描；
- [ ] 大小号刷炫彩； 

完全存在封号可能，Use this script at your own risk.

## Reference

- https://github.com/Makapic/RocoPilot
