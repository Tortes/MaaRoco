# MaaRoco macOS 预览版

这是桌面窗口控制的实验版，尚未完成真实游戏验证。要求 macOS 14 或更高版本。
M 系列芯片下载 `macos-aarch64`，Intel 芯片下载 `macos-x86_64`。

## 启动与授权

1. 解压整个发布包，将 `MaaRoco.app` 放到你有写入权限的固定目录。
2. 双击 `MaaRoco.app`。包内已有 .NET 和 C++ Agent，不需要安装 Python、Interception 或额外的 .NET。
3. 本预览版使用 ad-hoc 签名，未经 Apple 公证。如果 Gatekeeper 阻止运行，在“系统设置 → 隐私与安全性”中允许打开。若仍提示损坏，可在终端输入 `xattr -dr com.apple.quarantine `（末尾空格），将**本包的 MaaRoco.app** 拖进去后回车，再重新打开。
4. 在“系统设置 → 隐私与安全性”中，为 MaaRoco 授予“屏幕录制”（新系统可能叫“屏幕与系统音频录制”）和“辅助功能”权限，然后完全退出并重新启动。
5. 如果日志提示 Agent 缺少辅助功能权限，使用 Finder 的“显示包内容”找到 `Contents/MacOS/runtimes/osx-arm64/native/MaaRocoAgent`（Intel 为 `osx-x64`），将其加入辅助功能列表。
6. 手动启动游戏，在 MaaRoco 选择“macOS 游戏窗口（实验性）”，刷新窗口列表并选中游戏。先确认截图正常，再运行任务。

## 建议试用顺序

- 先使用窗口模式、16:9 画面，确认识别画面与 Windows 版布局相同；Retina 缩放或客户端 UI 差异可能需要重新校准。
- 先测普通丢球，再测战斗按键，最后测目标搜索与瞄准。任务默认不勾选，自动更新关闭。
- `F11` 为开始/停止快捷键；若系统将它分配给“显示桌面”，使用界面的停止按钮。
- 停止后确认鼠标和按键已释放。不要同时操作其他应用，因为此版本会激活选中的游戏进程。

## 当前范围与限制

- 使用 MaaFramework ScreenCaptureKit 截图与 GlobalEvent 输入；Windows 键码已转换为 macOS 键码。
- 保留战斗、普通/组合丢球、月牙雪熊与通用目标探索的桌面流程。
- 瞄准使用带相对位移的 macOS CGEvent，接口调用成功不代表游戏接受事件；兼容层和游戏自身的输入处理需要真机验证。
- 不包含 WeGame 一键启动；请手动启动并进入游戏。
- 这不是针对 iOS 触控布局重写的脚本，也未接入 PlayCover 专用协议。若使用 iOS 版游戏，需要提供运行方式、键鼠映射与截图后进一步适配。
- 预览包与 Windows stable 通道隔离，不会覆盖 Windows 正式版。

## 反馈

请提供 Mac 芯片、macOS 版本、游戏运行方式（原生/PlayCover/CrossOver 等）、失败任务，以及
`MaaRoco.app/Contents/MacOS/debug` 和 `logs` 下对应日志。尤其说明截图是否正常、按键是否生效、视角是否跟随瞄准移动。

## 构建依据

- [MaaFramework macOS 控制方式](https://github.com/MaaXYZ/MaaFramework/blob/v5.13.0/docs/en_us/2.4-ControlMethods.md)
- [Apple CGEvent](https://developer.apple.com/documentation/coregraphics/cgevent)

原生二进制由 GitHub macOS runner 编译并执行策略与 IPC 测试；这些检查不能替代真实游戏验证。
