# MaaEnd → MaaRoco 自动化能力迁移建议

记录日期：2026-10-03。

本建议基于 MaaEnd 源码快照 [`aa44b0aecf8e5bd6428cafba1bc57f5348e641bf`](https://github.com/MaaEnd/MaaEnd/tree/aa44b0aecf8e5bd6428cafba1bc57f5348e641bf)，对照 MaaRoco `feat/mxu-migration` 分支当时的工作区。以下内容是迁移方案，未表示相应功能已经实现；成本是基于代码耦合程度的相对估计。

后续技术分析：[MaaEnd 如何识别三维场景中的目标](maaend-3d-target-recognition.md)。

## 目标与当前缺口

优先迁移场景恢复、任务自动结束、补给与背包管理、自动巡点，使 MaaRoco 能够自主完成一整套目标。

MaaRoco 已有 MXU 任务队列与定时入口、游戏启动、战斗托管、花种战斗、目标检测与瞄准，以及战斗中的炫彩停机保护。这些能力可以作为后续扩展的基础。

当前主要缺口：

- [`TargetPetThrow.json`](../assets/resource/pipeline/TargetPetThrow.json) 持续循环执行目标投球，错误分支也返回同一循环；尚未根据捕获结果、球数或目标数量决定下一步。
- [`target_pet.cpp`](../agent/cpp/target_pet.cpp) 已有目标跟踪、视角扫描、丢失容忍和瞄准，但该流程没有角色巡点与补给处理。
- 连续投球和战斗托管等挂机任务缺少正常结束条件，会持续占用顺序任务队列。手动停止不能代替任务正常完成。

## 优先级与迁移内容

| 优先级 | MaaEnd 能力 | MaaRoco 适配方向 | 相对成本 |
| --- | --- | --- | --- |
| P0 | InScene / SceneManager：统一场景识别与跳转 | 识别大世界、战斗、背包、登录、加载和已知弹窗；自动进入任务要求的界面，减少手动准备 | 中 |
| P0 | 定次数执行与完成出口 | 为投球和花种战斗增加次数、时长、资源下限、目标达成条件；完成后进入队列下一项 | 低—中 |
| P0 | FailureCollector：失败收集与恢复子任务 | 普通点位失败后执行对应恢复、跳过或继续，结束时汇总失败点 | 中 |
| P1 | IMS：库存同步和条件判断 | 识别球、花种及背包余量；不足时补给或结束，达到目标库存时跳过任务 | 中 |
| P1 | RecoGrid / GridTracker：网格扫描与翻页去重 | 支撑背包整理、精灵列表扫描和筛选，避免翻页重叠导致重复处理、漏项或误判到底 | 中—高 |
| P1 | CharacterController：靠近目标与局部搜索 | 根据已有目标框移动；目标太远时靠近，交互点丢失时小范围搜索，先覆盖一个固定捕捉区域 | 中 |
| P2 | MapLocator / MapNavigator：定位、路线执行与脱困 | 自动前往捕捉点、多点轮巡、返回补给点；根据实际位置判断卡住并尝试脱困或重新规划 | 高 |
| P2 | DailyRewards / 场景预设 | 根据洛克实际界面补充邮件、日常奖励领取，组合“上线日常”“花种捕捉”等一键方案 | 低—中 |

### 1. 场景识别与恢复

MaaEnd 用纯识别节点描述当前场景，再通过公共入口和 `[JumpBack]` 组织跳转。业务任务只提出“进入某个场景”的要求，公共流程负责加载、弹窗、返回和进入。

迁移时优先建立洛克自己的场景识别库，并为每次交互增加结果确认。只能对已识别的状态执行恢复动作。炫彩保护的判断优先级必须高于普通场景恢复。

参考：[公共场景入口](https://github.com/MaaEnd/MaaEnd/blob/aa44b0aecf8e5bd6428cafba1bc57f5348e641bf/assets/resource/pipeline/Interface/Scene.json)、[设计说明](https://github.com/MaaEnd/MaaEnd/blob/aa44b0aecf8e5bd6428cafba1bc57f5348e641bf/docs/zh_cn/developers/scene-manager.md)。

### 2. 有限任务与结果语义

借鉴 MaaEnd 定次数刷取和完成出口，为现有无限挂机模式增加可选的有限执行模式。

- 投掷次数与捕获成功数分别统计；捕获数只在结果确认后增加。
- 支持达到数量、耗时或资源阈值后正常结束。
- 区分正常完成、资源不足、普通失败、用户停止、炫彩保护等结果。
- F11 和炫彩保护应停止整个执行链，不能被恢复或“失败后继续”机制吞掉。

参考：[AutoEssence 次数选项](https://github.com/MaaEnd/MaaEnd/blob/aa44b0aecf8e5bd6428cafba1bc57f5348e641bf/assets/tasks/AutoEssence/AutoEssence.json)、[完成出口](https://github.com/MaaEnd/MaaEnd/blob/aa44b0aecf8e5bd6428cafba1bc57f5348e641bf/assets/resource/pipeline/AutoEssence/CommonNodes/AutoEssence.json)。上述结果分类是 MaaRoco 的适配建议，不是 MaaEnd 现成接口。

### 3. 失败收集与恢复

MaaEnd 的 FailureCollector 可以执行子任务、记录失败、调用可选恢复任务，并在最后汇总失败。

适用于多个相互独立的采集点或日常子任务。迁移到 MaaRoco 时，应按已识别的失败原因选择恢复流程，并设置恢复预算；未知故障不能无限重试。普通子任务失败与全局停止需要独立处理。

参考：[FailureCollector 实现](https://github.com/MaaEnd/MaaEnd/blob/aa44b0aecf8e5bd6428cafba1bc57f5348e641bf/agent/go-service/common/failurecollector/action.go)。

### 4. 库存与背包

IMS 的价值在于“扫描—记录—判断—执行”的组织方式，包括缓存有效性和完整扫描后提交。RecoGrid / GridTracker 则提供单帧网格识别、滚动重叠对齐、去重和到底确认。

第一版只需覆盖球数、花种数量和容量判断；再逐步加入补给与精灵筛选。洛克的稀有、锁定、保留数量等业务规则，以及整理后的结果确认，需要独立适配。

参考：[IMS](https://github.com/MaaEnd/MaaEnd/blob/aa44b0aecf8e5bd6428cafba1bc57f5348e641bf/docs/zh_cn/developers/components/ims.md)、[RecoGrid / GridTracker](https://github.com/MaaEnd/MaaEnd/blob/aa44b0aecf8e5bd6428cafba1bc57f5348e641bf/docs/zh_cn/developers/components/recogrid-engine.md)。

### 5. 从局部移动到地图导航

先借鉴 CharacterController：根据目标框相对屏幕的位置调整朝向，根据画面尺度做局部靠近，再次识别后继续。具体阈值需要洛克实测。

地图导航放在后续阶段。MaaEnd 的 MapLocator 利用小地图、模型和底图进行定位；MapNavigator 利用定位结果、路线或导航网格控制角色移动，并包含卡住检测与脱困。现成的终末地模型、底图、地图拓扑和输入参数不能直接用于洛克。

参考：[CharacterController](https://github.com/MaaEnd/MaaEnd/blob/aa44b0aecf8e5bd6428cafba1bc57f5348e641bf/docs/zh_cn/developers/components/character-controller.md)、[MapLocator](https://github.com/MaaEnd/MaaEnd/blob/aa44b0aecf8e5bd6428cafba1bc57f5348e641bf/docs/zh_cn/developers/components/map-locator.md)、[MapNavigator](https://github.com/MaaEnd/MaaEnd/blob/aa44b0aecf8e5bd6428cafba1bc57f5348e641bf/docs/zh_cn/developers/components/map-navigator.md)。

### 6. 日常领取与预设

按洛克现有界面补充邮件、日常奖励等流程，再通过现有 MXU 队列与定时能力组织。MaaEnd 的快速日常预设可以作为任务与选项组合方式的参考。

参考：[DailyRewards](https://github.com/MaaEnd/MaaEnd/blob/aa44b0aecf8e5bd6428cafba1bc57f5348e641bf/assets/resource/pipeline/DailyRewards.json)、[QuickDaily](https://github.com/MaaEnd/MaaEnd/blob/aa44b0aecf8e5bd6428cafba1bc57f5348e641bf/assets/tasks/preset/QuickDaily.json)。

## 建议实施阶段

### 第一阶段：单点捕捉闭环

进入正确场景 → 检查球数与容量 → 搜索、投球或战斗 → 确认结果 → 更新计数 → 判断继续、补给或完成。

先在一个固定捕捉区域验证场景恢复、结果识别、资源判断和队列衔接。

### 第二阶段：局部移动与固定路线

增加靠近目标、有限范围搜索和少量固定点位轮巡。每个点位具有成功、失败和恢复出口。

### 第三阶段：地图定位与多点调度

在洛克定位数据可靠后，引入路线编辑、自动导航、脱困和补给往返。

## 实现边界

- 保留 MaaRoco 的 C++ Agent 架构。流程组织优先用现有 Pipeline 实现；网格、定位等 C++ 算法可评估抽取，简单 Go 辅助逻辑可按需要改写。
- 当前 MaaRoco 会在队列任务之间重建运行实例。跨任务的库存、路线进度和捕获统计不能只依赖进程内缓存，需要明确保存、刷新、账号归属和失效时机。
- 场景模板、OCR 规则、模型、地图底图、导航数据和移动参数均需洛克适配，不能以替换任务名称代替迁移。
- 本次只做源码对照分析，没有通过实机验证这些方案在洛克中的效果。

## 验证建议

沿用 MaaRoco 已有的炫彩识别验证，再借鉴 MaaEnd 的截图节点回归测试，扩展场景、缺球、背包满和捕获结果的正负样本。静态截图验证识别结果，实机验证交互时序与完整任务。

参考：[MaaEnd 节点测试](https://github.com/MaaEnd/MaaEnd/blob/aa44b0aecf8e5bd6428cafba1bc57f5348e641bf/docs/zh_cn/developers/node-testing.md)。
