# PeaseBar = 对开源 Thaw 的 1:1 移植（Swift）

本目录记录产品方向的重大变更（用户 2026-11-23 定调：「一比一重写人家项目」）。

## 决策
- 放弃此前用 Python/PyObjC 近似复刻的做法（其隐藏/排序只是 ⌘-拖 近似，非 Thaw 真实机制）。
- 改为直接移植真正的 **Thaw**（Swift + AppKit + SwiftUI，GPL-3.0）：源码完整 vendored 到 [`swift/`](swift/)。
- 旧的 Python 实现（`peasebar/`、`tests/`）暂时保留作参考，不再作为交付产品。

## 已验证（本机 macOS 27.2 / Xcode 27.2 / Swift 6.4.2）
- Thaw 3（对应 macOS 27）可完整构建并运行：
  ```sh
  cd swift
  sh scripts/install-swiftlint.sh        # 构建阶段要求 SwiftLint 0.65.1（pinned）
  ./scripts/devrun.sh --ad-hoc           # 解析依赖→构建→装到 /Applications/Thaw Debug.app→启动
  ```
  实测：依赖解析 ~276s，构建成功，产物 `Thaw Debug` 3.0.0-beta.7（bundle `com.stonerl.Thaw.debug`）已启动。
- 产物内嵌真引擎：**PlatformRuntimeKit.framework**（预编译 `prk-bin`，Thaw 靠它按 App 隐藏/排序菜单栏项）
  + MenuBarModel / ThawAXCore / Sparkle / ThawControls.appex。

## 使用前置（需人工授权，脚本无法代劳）
首次启动会弹权限引导，需在「系统设置 → 隐私与安全性」给 **Thaw Debug** 勾选：
1. **辅助功能（Accessibility）**：读取并触发菜单栏图标；
2. **菜单栏布局访问（Menu Bar Layout Access）**：读写系统保存的图标顺序；
3.（可选）**屏幕录制**：抓取图标真实像素。

> 注意：Thaw Debug 会真实改动你的菜单栏布局；调试版与正式版 Thaw 用不同 bundle id，互不覆盖设置。

## 许可合规
- Thaw 源码为 **GPL-3.0**，附带 `swift/LICENSE-EXCEPTION`（GPL §7 附加许可）：明确允许与闭源
  PlatformRuntimeKit 链接并**再分发组合结果**，且该组合的非源码形式无需公开 prk 源码。
- 因此以本仓库分发移植版合规，前提是保留 GPL-3.0 许可、`LICENSE-EXCEPTION`、版权与 `CREDITS.md`，
  并公开对应源码（本 `swift/` 目录即对应源码）。上游：https://github.com/thaw-app/Thaw （development@69a66b9）。

## 交付路线回调（Phase 11，用户 2026-11 定调）
- **问题**：Swift 移植版以 ad-hoc 签名的 `Thaw Debug.app` 运行，未授辅助功能权限时**连菜单栏都读不到**，
  作为交付物不可用；用户要求「照 Thaw 截图 + 读代码的认知重写」。
- **决定**：回到能稳定读菜单栏的 **Python/PyObjC 端**作为当前交付产品，把设置窗从 5 页
  扩到 Thaw 的 **12 页**，逐页 1:1 对标 `tmp/thaw_ref/` 的 AX 树与截图（侧栏分组、每页
  heading/卡片/控件/help、子页签、权限状态、配置管理真实存/应用/删除）。
- **取证**：168 单测全绿；离屏渲染全 12 页无异常；真机（源码跑真窗口）逐页截图目视核对 PASS，
  详见 `tmp/test-plan-phase11.md` 与 `tmp/shots/p00..p11.png`。
- **Swift 端**：`swift/` 继续保留为上游参考与后续原生引擎候选（PlatformRuntimeKit 的真实隐藏/排序机制），
  但在解决「ad-hoc bundle 授权后即可读菜单栏」之前不作为交付形态。

## 后续（全量对标路线）
1. 品牌化：bundle id / 产品名 / 图标由 Thaw 调整为 PeaseBar（改 `THAW_BUNDLE_ID_SUFFIX`、product name、资源）。
2. 功能与 UI 以 Thaw 原版为准（面板、设置多页、快捷键、收纳、救援、profiles、Zen Mode、thaw:// 链接等）——移植版天然自带。
3. 构建/发布脚本对齐 Pease 产品线（签名、公证、更新源）。
