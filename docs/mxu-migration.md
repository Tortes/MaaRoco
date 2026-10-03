# MXU 迁移

Windows 前端锁定 MXU v2.7.1（`frontend.lock.json` 中记录完整提交），修改保存为 `tools/frontend/mxu.patch`。原有任务 JSON、pipeline 和 C++ Agent 继续使用，MaaFramework 锁定 v5.13.0。

## 使用

- “单任务”标签页点击任务标题立即执行；切换到另一个任务时先停止当前任务。任务选项独立保存。
- “任务队列”按列表顺序执行已勾选任务。“全部任务”面板支持拖入列表指定位置和列表内排序。
- F11 全局停止当前运行任务，切换标签页后仍能停止。默认关闭实时画面，避免空闲持续截图。
- Windows 只使用 Interception。启动游戏任务自动连接桌面，后续任务重新查找游戏窗口并连接，不需选择启动器控制器。
- 正式 `vX.Y.Z` 版本从 MaaRoco 的 GitHub stable Release 检查更新；开发、CI 和预发布包不检查更新。

运行需要 Windows x64、WebView2 和 Interception 驱动。用户不需要 .NET 或 Python。MXU 的 WebView2 启动检查会在缺少运行库时提供安装入口。

## 配置迁移

MXU 使用 `config/mxu-MaaRoco.json`。安装脚本或客户端首次启动检测到旧 MFA 配置时，会先将原文件逐字节备份到 `config/backups/mfa-to-mxu-<hash>/`，随后转换任务参数、勾选状态、队列顺序、资源选择、窗口信息、单任务和自定义标签页。

旧文件保留在原位置。已经存在的 MXU 配置不会被迁移覆盖。备份目录中的 `migration-report.json` 记录未映射字段与无法迁移的定时策略：每日、每周的开始定时可导入；每月、停止任务、关机等策略保留原始备份供人工重建。旧 MFA 加密密钥不会直接作为 MXU 明文密钥导入。

覆盖安装前，安装器还会完整备份旧 `interface.json`，并保留路径仍然存在的自定义资源定义。成功安装后只清理明确的 MFA 运行文件；旧运行目录中的用户配置、调试数据和自定义资源继续保留。

发布 ZIP 不含用户 `config`，避免覆盖用户设置并确保在实际升级机器上执行首次迁移。全新安装自动建立单任务和任务队列两个标签页，仍可创建自定义标签页。

## 构建

开发工具：Python（只用于构建）、Node.js 22、pnpm 10.28.0、Rust stable、Visual Studio C++ Build Tools、CMake，以及 `deps` 下通过 `maaframework.lock.json` 校验的 MaaFramework SDK。

```powershell
python -m pip install -r tools/requirements.txt
python tools/build_frontend.py
python tools/install.py v0.0.0-mxu-dev win x86_64 --install-dir build/mxu-preview
python tools/validate_native_package.py build/mxu-preview
```

`build_frontend.py` 校验完整源码树与锁定提交加补丁一致，并运行前端测试；安装器重新核验可执行文件和运行依赖的 SHA-256。开发机使用便携工具链时可指定 `--pnpm-cli`、`--rust-bin` 和 `--rust-target`。CI 使用 MSVC；本地 GNU 构建会额外携带锁定依赖中的 `WebView2Loader.dll`。

目录布局：

```text
MaaRoco.exe / MaaRoco.cmd
interface.json
maafw/                   # 框架 DLL、插件和原生 Agent/Runner
resource/ / tasks/ / locales/
frontend.lock.json / maaroco-frontend.json
frontend-source/mxu.patch
licenses/MXU-AGPL-3.0.txt
config/mxu-MaaRoco.json   # 首次启动生成；不放入发布 ZIP
```

MXU 采用 AGPL-3.0，其许可证、上游提交和定制补丁随包提供。MaaRoco 的任务资源和 Agent 保持原有许可证。

## 本次验证

Windows 本地 GNU 预览包已编译通过。Python 64 项、Rust 57 项、前端 20 项测试通过；原生 Agent IPC 使用合成帧验证。独立空操作流水线验证了实际后端的顺序执行、逐任务重建控制器、保留全部任务映射、取消后不启动下一任务，以及 Web UI 在切换控制器期间持续报告运行中。

浏览器界面验证了固定标签页、点击任务启动、任务面板添加和队列内拖拽排序。Windows 原生 HTML 拖拽已按 Tauri 要求关闭文件拖放拦截。原生窗口的面板拖入和全局 F11、真实游戏流程，以及 CI 的 MSVC 构建尚未现场验证；此预览包供后续实机验证，版本不会触发正式版自动更新。

本地输出为 `build/mxu-preview/` 和 `build/MaaRoco-win-x86_64-v0.0.0-mxu-dev.zip`。ZIP 已检查 CRC、前端与补丁哈希，且不包含 `config`、`cache` 或调试日志。自动化测试日志和界面截图保存于 `build` 目录。
