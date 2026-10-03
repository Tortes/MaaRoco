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

下载：[GitHub Release](https://github.com/Tortes/MaaRoco/releases) · [Gitee 镜像 Release](https://gitee.com/tortes/maa-roco/releases)。Gitee 保留最新正式版和预览版的分卷安装包，请按对应 Release 附件中的 `GITEE_DOWNLOAD.md` 合并、校验后解压；历史版本提供 GitHub 原包链接。同步规则见 [Gitee 镜像说明](docs/gitee-sync.md)。

使用官方 [MaaFramework v5.13.0](https://github.com/MaaXYZ/MaaFramework/releases/tag/v5.13.0) 的完整 Windows x86-64 运行库，版本及校验值记录在 `maaframework.lock.json`。需要提前安装 [Interception 驱动](https://github.com/oblitum/Interception)。瞄准所需的相对鼠标移动通过C++ Agent 直接调用 Interception 驱动 执行；连续丢球使用固定按住时长和固定间隔。

前端默认关闭实时画面，空闲时不会持续截图；任务运行期间由任务流水线按需截图。

安装包提供两个任务模式标签页，共用原有 JSON pipeline 和 C++ Agent：

- **单任务**：点击目标任务即可启动，仅执行该任务；按 `F11` 停止。每个任务的选项单独保存。
- **任务队列**：从“全部任务” dock 将任务拖入列表，勾选要执行的任务并拖拽排序，然后按开始按钮或 `F11` 按顺序执行；运行时按 `F11` 停止。

两个标签页的任务选项相互独立。升级时保留原任务队列和用户新增的标签页；旧“启动游戏”标签页中的 WeGame 路径、登录源迁移到“单任务”，完整旧配置保存在 `config/backups/launch-game.json`。被启用的定时任务使用的旧启动标签页会保留。

Windows 下控制器仅提供 **Interception**；启动游戏和后续游戏任务会自动连接所需的桌面或游戏窗口，无需配置、选择“游戏启动器”控制器。升级会将现有标签页的控制器配置迁移到 Interception，并保留任务选项、顺序、勾选状态及定时任务。

正式 Release 版本启动时会通过 GitHub Release 检查 MaaRoco stable 通道，并自动下载、安装更新后重启；debug、dev、CI 和预发布版本不会检查或拉取更新。正式版可在设置的版本更新页面关闭自动更新或手动检查版本。

### 安装 Interception 驱动

Windows 用户可以从本仓库下载并以管理员身份运行 [tools/install_interception.cmd](tools/install_interception.cmd)。脚本会从 Interception 官方 Release 下载并运行驱动安装程序；安装完成后请重启 Windows。

### 通过 WeGame 启动游戏

“启动游戏（WeGame）”与其它任务一起出现在“全部任务” dock 中；初始任务队列也包含它，默认不勾选。单任务模式点击即可运行，任务队列模式可拖入并排在其它任务之前。界面会在启动游戏前自动连接 Windows 桌面，运行后续游戏任务前自动连接游戏窗口，全程使用 Interception。

1. 在“单任务”或“任务队列”标签页的任务设置中填写本机 `wegame.exe` 的完整路径，并选择登录源；登录源默认是 QQ。
2. 在“单任务”标签页点击“启动游戏（WeGame）”；或在“任务队列”中勾选它并开始执行。
3. 流水线会使用 `/StartFor=2002304` 拉起 WeGame。选择微信时，如果当前显示 QQ，会先打开登录源菜单并切换到微信；随后识别并点击右下角“启动”按钮，等待《洛克王国：世界》窗口出现。
4. 检测到游戏窗口后，任务会自动创建 Interception 控制器，等待并点击登录页的“进入世界”按钮；确认按钮消失后任务即结束，不会继续执行战斗或其它任务。
5. 需要继续使用战斗或丢球任务时，在“单任务”中点击目标任务；或将它们放在“任务队列”的启动游戏任务之后。

支持：
- [x] 随机/固定丢球模式；
- [x] 固定精灵类型探索捕捉；
  - [x] 月牙雪熊
- [x] 半自动战斗捕捉

TODO:
- [ ] 自动清理背包；
- [ ] 炫彩花种战斗；
- [ ] 炫彩花种炫彩扫描；
- [ ] 大小号刷炫彩； 

完全存在封号可能，Use this script at your own risk.

## Reference

- https://github.com/Makapic/RocoPilot

## 原生 Agent 与构建

发布包中的自定义逻辑使用 C++20：启动游戏、战斗焦点按键、月牙雪熊瞄准和通用精灵探索。
用户不需要安装 Python，包内也不包含 Python、NumPy 或 Python OpenCV。
Windows UI 基于 MXU v2.7.1 增加单任务模式和任务 dock，MaaFramework 继续使用锁定版本；运行需要 WebView2，输入需要 Interception 驱动。

定制 UI 的上游版本锁定在 `frontend.lock.json`，界面修改保存在 `tools/frontend/mxu.patch`。开发者安装 Node.js 22、pnpm 10.28.0、Rust 和 Visual Studio C++ Build Tools 后，可以单独构建 UI：

```powershell
python tools/build_frontend.py
```

完整安装使用 `python tools/install.py <version> win x86_64`，会构建并安装定制 UI 和原生 Agent；安装会保留已有任务队列和任务参数。

开发构建需要 CMake、Windows x64 C++ 工具链（Visual Studio C++ Build Tools），以及放在 `deps` 下的锁定版 MaaFramework SDK：

```powershell
./tools/build_native_agent.ps1
```

资源打包、测试和模型训练脚本仍使用开发机 Python，不会分发给用户。
打包工具依赖见 `tools/requirements.txt`，训练依赖见 `tools/training-requirements.txt`。
Windows 下 `MaaRocoAgent.exe` 和 `MaaRocoRunner.exe` 安装到 `maafw`，与 MXU 共用该目录的 MaaFramework DLL；不分发调试符号。
首次从 MFA 升级会保留原配置并创建完整备份，再导入任务队列、单任务参数和自定义标签页。详细构建与迁移说明见 [MXU 迁移说明](docs/mxu-migration.md)。
噼啪鸟功能和模型已移除；月牙雪熊与通用目标探索保留。

发布前执行 `python tools/validate_native_package.py install`，检查模板、模型、框架校验值及原生入口。
