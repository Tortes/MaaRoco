<!-- markdownlint-disable MD033 MD041 -->
<p align="center">
  <img alt="LOGO" src="assets/locales/MaaRoco.png" width="256" height="256" />
</p>

<div align="center">

# MaaRoco

</div>

> 本项目由 **[MaaFramework](https://github.com/MaaXYZ/MaaFramework)** 强力驱动！

一种基于MaaFramework的RocoWorld自动化脚本；

## 即刻开始

参考[MaaFw手册](https://github.com/MaaXYZ/MaaPracticeBoilerplate/blob/main/docs/zh_cn/develop/how_to_develop.md), 使用定制化的[MaaFramework Release](https://github.com/Tortes/MaaFramework/releases)替换原有`deps`目录框架动态库，以支持[Interception](https://github.com/oblitum/Interception)能力；需要提前下载Interception驱动，参考[Interception官方github页面](https://github.com/oblitum/Interception)；

前端默认关闭实时画面，空闲时不会持续截图；任务运行期间由任务流水线按需截图。按 `F11` 可启动或停止当前任务。

正式 Release 版本启动时会通过 GitHub Release 检查 MaaRoco stable 通道，并自动下载、安装更新后重启；debug、dev、CI 和预发布版本不会检查或拉取更新。正式版可在设置的版本更新页面关闭自动更新或手动检查版本。

### 通过 WeGame 启动游戏

1. 将控制器切换为“桌面端 - 游戏启动器”。
2. 选择“启动游戏（WeGame）”任务，在任务设置中填写本机 `wegame.exe` 的完整路径，无需添加引号。
3. 启动任务；流水线会使用 `/StartFor=2002304` 拉起 WeGame，识别并点击右下角“启动”按钮，然后等待《洛克王国：世界》窗口出现。
4. 检测到游戏窗口后，任务会自动创建 Interception 控制器，并连续执行已有的 `BattleHostingStart` pipeline；无需手动切换控制器或另选“战斗托管”任务。

支持：
- [x] 随机/固定丢球模式；
- [x] 固定精灵类型探索捕捉；
  - [x] 月牙雪熊
  - [ ] 噼啪鸟
- [x] 半自动战斗捕捉

TODO:
- [ ] 自动清理背包；
- [ ] 炫彩花种战斗；
- [ ] 炫彩花种炫彩扫描；
- [ ] 大小号刷炫彩； 

完全存在封号可能，Use this script at your own risk.

## Reference

- https://github.com/Makapic/RocoPilot
