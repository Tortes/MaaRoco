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

使用官方 [MaaFramework v5.13.0](https://github.com/MaaXYZ/MaaFramework/releases/tag/v5.13.0) 的完整 Windows x86-64 运行库，版本及校验值记录在 `maaframework.lock.json`。需要提前安装 [Interception 驱动](https://github.com/oblitum/Interception)。瞄准所需的相对鼠标移动通过内置 Python Interception 执行；连续丢球使用固定按住时长和固定间隔。

前端默认关闭实时画面，空闲时不会持续截图；任务运行期间由任务流水线按需截图。按 `F11` 可启动或停止当前任务。

正式 Release 版本启动时会通过 GitHub Release 检查 MaaRoco stable 通道，并自动下载、安装更新后重启；debug、dev、CI 和预发布版本不会检查或拉取更新。正式版可在设置的版本更新页面关闭自动更新或手动检查版本。

### 通过 WeGame 启动游戏

1. 将控制器切换为“桌面端 - 游戏启动器”。
2. 选择“启动游戏（WeGame）”任务，在任务设置中填写本机 `wegame.exe` 的完整路径，并选择登录源；登录源默认是 QQ。
3. 启动任务；流水线会使用 `/StartFor=2002304` 拉起 WeGame。选择微信时，如果当前显示 QQ，会先打开登录源菜单并切换到微信；随后识别并点击右下角“启动”按钮，等待《洛克王国：世界》窗口出现。
4. 检测到游戏窗口后，任务会自动创建 Interception 控制器，等待并点击登录页的“进入世界”按钮；确认按钮消失后任务即结束，不会继续执行战斗或其它任务。

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
