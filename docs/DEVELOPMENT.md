# PeaseBar 开发文档

> 一个 macOS 27 菜单栏图标管理器（Pease 产品线）。业务逻辑参照开源项目
> [Thaw](https://github.com/thaw-app/Thaw)，但**全部用 Python + PyObjC 重新实现**，
> 界面中文优先、选项精简、以"刘海救援"为核心差异化。
>
> **文档定位**：功能说明 + 技术事实 + 路线图 + 进度快照。机器重启后按
> [§9 续作指引](#9-续作指引重启后从这里开始) 继续即可。

---

## 1. 项目定位与用户核心诉求

| # | 诉求（用户原话提炼） | 对应能力 |
|---|---|---|
| U1 | "可以编辑菜单栏的顺序" | 顺序编辑器（读取实际顺序 + ⌘拖拽写入新顺序） |
| U2 | "被刘海（齐头帘）遮挡的图标，点菜单栏按钮在下方弹窗显示出来" | **救援面板**（核心创新，v1 旗舰功能） |
| U3 | "至少比摄像头遮挡好" | 用救援面板替代遮挡类方案（Alcove/TopNotch 等） |
| U4 | Thaw"中文翻译不全、选项奇怪、bug 多" | 中文优先 UI、选项只留必要的、每功能真机测试 |
| U5 | "使用 python 或者 go 直接重新，理解他的业务逻辑" | Python + PyObjC 全新实现（选型理由见 §4） |

**一句话定位**：菜单栏图标永远不会"丢"——不管它被刘海挡住、被系统收纳，
还是被刻意藏起，都能从 PeaseBar 的救援面板一键找回并触发。

## 2. Thaw 业务逻辑梳理（参照对象，不照抄实现）

Thaw 3（macOS 27 分支）的核心业务闭环：

```
读（AX/MenuBarAgent 窗口） → 盘点图标（归属/名称/坐标/位图）
  → 分区决策（可见 / 隐藏 / 永久隐藏，纯函数规划器）
  → 写（移动：菜单栏顺序文件 或 合成 ⌘拖拽；隐藏：MenuBarAgent per-app）
  → 呈现（控制图标点击 un-stack / Search 面板 / Thaw Bar）
  → 维持（自动收回、快捷键、屏幕录制时自动藏、显示/空间变化自愈）
```

我们采纳的业务模型：**分区（三区）+ 控制图标 + 点按显现 + 面板直达 + 自动收回**。
我们不采纳/无法采纳的部分：PlatformRuntimeKit（闭源）、设置子进程、⌥空格 Search 的
私有实现、外观魔改（Glass/tint）等 —— v2 再议。

## 3. 功能清单

### 3.1 v1（MVP，当前阶段）

| ID | 功能 | 说明与交互 | 验收标准 |
|----|------|-----------|---------|
| F1 | **图标盘点引擎** | AX 枚举 MenuBarAgent（系统图标+原生收纳按钮）与各运行 App 的 `AXExtrasMenuBar`；每项含 owner、名称、坐标、刘海遮挡判定 | 与菜单栏实际图标一致；遮挡判定与截图对得上 |
| F2 | **控制图标** | PeaseBar 自己的 NSStatusItem；左键弹救援面板，右键系统菜单 | 图标常驻；可被用户用系统拖拽改位；左键/右键行为正确 |
| F3 | **救援面板** | 无边框 NSPanel 出现在控制图标正下方；网格展示全部图标（名称+归属+刘海徽标）；单击=对真实图标 AXPress 弹出其原生菜单 | 面板出现在按钮下方；点击面板内图标能弹出对应菜单；含刘海遮挡项 |
| F4 | **分区模型** | visible / hidden / always-hidden 三区，配置键 = bundleId+图标名；面板可按区过滤 | 标记为 hidden 的图标在面板中归入隐藏区并持久化 |
| F5 | **自动收回** | 点击面板外即关；可配超时（默认 8s，0=不超时） | 失焦即收；超时行为正确 |
| F6 | **全局快捷键** | 默认 ⌥⌘B 切换面板；可在配置改键 | 快捷键全局有效（其他 App 在前台也生效） |
| F7 | **权限引导** | 启动检测辅助功能权限；缺失则弹窗带"打开系统设置"按钮 | 无权限时有明确中文指引，不静默失效 |
| F8 | **顺序编辑器（只读视图）** | 面板列出当前实际顺序（按 x 排序） | 与真实顺序一致 |
| F9 | **状态持久化** | 配置存 `~/Library/Application Support/PeaseBar/config.json` | 重启 PeaseBar 分区/设置保留 |
| F10 | **单实例 + 退出** | 二次启动唤起已有实例；右键菜单可退出 | 双开不出现两个控制图标 |

### 3.2 v1.x（顺序写入与真隐藏，依赖 Phase 0 实验 E1–E3 结论）

| ID | 功能 | 依赖 | 说明 |
|----|------|------|------|
| F11 | **顺序写入（⌘拖拽合成）** | E2 | 编辑器支持上移/下移/拖拽排序，用合成 ⌘拖拽写入真实菜单栏 |
| F12 | **原生收纳联动** | E1 | 面板显示系统收纳的图标；提供"一键展开/收回"调原生按钮 |
| F13 | **per-app 原生隐藏写入** | E3 | 若 per-app 开关存储可写：分区内直接隐藏对应 App 图标 |
| F14 | **打包 .app + 开机自启** | — | py2app 打包；SMAppService 注册登录项；图标资产落地 |

### 3.3 v2 及以后（ backlog，暂不排期）

- 图标位图捕获（ScreenCaptureKit + 屏幕录制权限，面板显示真实图标皮肤）
- 屏幕录制时自动藏（防泄漏，Thaw 同款）
- Zen 模式、外观（间距/背景）、多配置 Profile、菜单栏搜索（keystroke 直达）
- `peasebar://` URL 自动化

## 4. 技术选型与理由

**选择：Python 3.14 + PyObjC（pyobjc-framework-Cocoa/Quartz/ApplicationServices）**

- 菜单栏管理的本质是 AppKit/AX/CGEvent 调用，PyObjC 全部原生可用（已实测）；
- Go 做 macOS GUI 需 cgo + ObjC shim，开发/调试成本数倍，且无成熟 NSStatusItem/AX 生态；
- 后续打包用 py2app 产出独立 .app，运行不依赖系统 Python（Phase 4 处理）。

依赖（已安装）：`pyobjc-framework-Cocoa`、`pyobjc-framework-Quartz`、
`pyobjc-framework-ApplicationServices`、`pyobjc-framework-ScreenCaptureKit`（v2 备用）。

## 5. macOS 27 技术事实（探测结论，本机取证）

> 证据文件：`tmp/probe_ax.py`、`tmp/probe_result.json`、`tmp/probe_reveal.py`（重跑中）。
> 本机：macOS 27.2.1 (26B131)，M4 Max 16"（逻辑分辨率 2056×1329，"更多空间"档）。

| # | 事实 | 影响 |
|---|------|------|
| T1 | 辅助功能权限：`AXIsProcessTrusted()=True`（当前运行环境已授权） | AX 读/按压/合成拖拽可用；打包成 .app 后需对新 bundle 重新授权 |
| T2 | 系统图标由 **MenuBarAgent**（com.apple.MenuBarAgent）托管：AXExtrasMenuBar 下是若干 `AXGroup`（各含 1 个 `AXMenuBarItem`：Wi‑Fi/控制中心/时钟）+ 1 个 `AXButton`"显示隐藏菜单栏项目"（AXPress 可用） | 系统图标枚举与"原生收纳联动"入口；27 存在**原生溢出收纳机制** |
| T3 | 第三方图标仍留在**各自 App 进程**的 `AXExtrasMenuBar`（实测 13 个 App 全部枚举成功，`AXPress` 全可用） | 读与触发双通道可用；第三方不需要 MenuBarAgent |
| T4 | MenuBarAgent 与第三方上报的坐标**均为 CG 坐标（左上原点，y 向下）**；转 AppKit：`y_appkit = screenH - y_cg - h` | 面板定位、遮挡判定统一用 CG，出口再转 |
| T5 | AXValue 解码：`AS.AXValueGetValue(val, kAXValueCGPointType, None) → (ok, CGPoint)`（PyObjC 自动出结构体；`val.x` 不存在） | axutil 封装 |
| T6 | `AXExtrasMenuBar` 属性返回值可能是单容器元素（取其 `AXChildren`）也可能直接是数组；MenuBarAgent 是 Group 包 Item，第三方直接是 Item | 盘点器做两级兼容 |
| T7 | 刘海区：`NSScreen.auxiliaryTopLeftArea/auxiliaryTopRightArea` 拼不满整行即为有刘海；本机刘海 x∈[918,1138]（宽 220pt），菜单栏高 38pt；`safeAreaInsets` 在 27 只报 top，**不能**用 | 遮挡判定 = 图标矩形与刘海矩形相交 |
| T8 | CGWindowList 层 24/25 在 27 上只剩 Window Server 的 "Menubar" 背景条；**图标没有自己的窗口** | 位图/位置不能走窗口列表，只能走 AX |
| T9 | `NSStatusItem Preferred Position` 经典存储仅个别域残留（TextInputMenuAgent、CleanMyMac5.Menu） | 顺序写入不靠它；走 ⌘拖拽合成（E2）或 27 顺序文件（需"菜单栏布局访问"TCC，Python 难授权，列为受限路线） |
| T10 | 屏幕录制权限：未验证（E4）。`screencapture -x` 是否出图待证 | 影响测试取证与 v2 位图捕获 |

## 6. 隐藏与顺序的实现策略（按可行性递减，实验后定型）

| 策略 | 机制 | 状态 |
|------|------|------|
| A 原生收纳引导 | 把图标 ⌘拖进刘海区触发系统收纳（原生按钮出现，面板仍可触发） | 待 E1/E2 |
| B per-app 开关写入 | 找到 26/27"在菜单栏中允许"开关的 defaults 域，直接写 + 重载 MenuBarAgent | 待 E3 |
| C 面板代持（兜底） | 图标不动，"隐藏"只是面板分区过滤 + 救援触发；顺序编辑只读 | **v1 保底，一定可用** |

## 7. 架构与模块

```
PeaseBar/
├── peasebar/
│   ├── __main__.py      # 入口：单实例检查 → 权限检查 → 启动
│   ├── app.py           # NSApplication 生命周期、Accessory 策略、模块装配
│   ├── axutil.py        # AX 基础封装：copy/children/point/size/actions/press + CG↔AppKit
│   ├── inventory.py     # F1 盘点引擎：MenuBarAgent + 各 App，轮询 + 变更回调
│   ├── control_item.py  # F2 控制图标：NSStatusItem、左右键分发
│   ├── panel.py         # F3 救援面板：NSPanel、图标网格、点击 AXPress、失焦/超时收回
│   ├── sections.py      # F4 三区模型：配置键、分区过滤、持久化
│   ├── mover.py         # F11 ⌘拖拽合成写入（Phase 3，实验通过后启用）
│   ├── hotkeys.py       # F6 全局快捷键（Carbon RegisterEventHotKey）
│   ├── settings.py      # F9 配置读写
│   └── ui/              # F14 设置窗口（Phase 4）
├── docs/DEVELOPMENT.md  # 本文档
├── tmp/                 # 探测/测试脚本、截图、test-plan.md（gitignore，不提交）
├── tests/               # 纯逻辑单测（分区规划、遮挡判定，不依赖 GUI）
└── README.md
```

分层原则（学自 Thaw）：**盘点（读）→ 规划（纯逻辑）→ 应用（写）→ 呈现（UI）**，
规划层不碰 AX，方便单测。

## 8. 路线图（每阶段 = 实现 → 测试计划 → 真机取证 → 修复 → commit）

### Phase 0 可行性与骨架
- [x] P0.1 探测 AX 权限 / MenuBarAgent 结构 / 第三方 AX / 刘海检测 / 坐标解码（§5 T1–T9 已取证）
- [ ] P0.2 **E1**：重跑 `tmp/probe_reveal.py`，AXPress 原生收纳按钮，取证收纳图标的呈现形态（上次被重启打断）
- [ ] P0.3 **E2**：`tmp/probe_drag.py` 合成 ⌘拖拽移动一个第三方图标（选 PeaseClash），前/后 x 坐标 + 截图取证
- [ ] P0.4 **E3**：`tmp/probe_native_hide.py` 引导用户手动切一次 per-app 菜单栏开关，diff defaults 域定位存储
- [ ] P0.5 **E4**：验证 `screencapture` 条带截图可用性（测试取证依赖）
- [ ] P0.6 骨架：`__main__/app.py` AppKit 生命周期 + Accessory + 单实例 + 右键菜单可退出 → **节点提交**

### Phase 1 v1 核心（F1–F3, F8）
- [ ] P1.1 `axutil.py` + `inventory.py`（含遮挡判定、两级结构兼容、轮询刷新）
- [ ] P1.2 `control_item.py`（左键/右键）
- [ ] P1.3 `panel.py` 救援面板（网格、刘海徽标、AXPress 触发、失焦收回）
- [ ] P1.4 `tmp/test-plan.md` 逐条真机执行 + 截图取证 → **节点提交**

### Phase 2 分区与维持（F4–F7, F9–F10）
- [ ] P2.1 `sections.py`（三区 + JSON 持久化）+ 面板分区过滤
- [ ] P2.2 自动收回（失焦/超时）+ `hotkeys.py`（⌥⌘B）
- [ ] P2.3 权限引导窗 + 单实例
- [ ] P2.4 tests/ 纯逻辑单测（分区规划、遮挡判定）→ **节点提交**

### Phase 3 顺序写入（F11–F12，视 E2/E1 结论）
- [ ] P3.1 `mover.py` ⌘拖拽写入 + 编辑器上移/下移/拖拽
- [ ] P3.2 原生收纳联动（面板按钮调原生 AXPress）
- [ ] P3.3 真机顺序编辑回归（移 3 个图标并复原）→ **节点提交**

### Phase 4 完整化（F13–F14）
- [ ] P4.1 设置窗口（中文、简单模式默认）
- [ ] P4.2 py2app 打包 + AppIcon 资产 + SMAppService 开机自启
- [ ] P4.3 全量回归 + README 使用说明 → **v1.0 发布节点**

## 9. 续作指引（重启后从这里开始）

1. `cd /Users/daydream/Project/PeaseBar`
2. 读本文档 §8 找到第一个未勾选项；进度快照见 §10
3. 环境自检：`python3 -c "import ApplicationServices as AS; print(AS.AXIsProcessTrusted())"` 应为 True；
   依赖缺失则 `python3 -m pip install --user pyobjc-framework-Cocoa pyobjc-framework-Quartz pyobjc-framework-ApplicationServices`
4. 临时/测试产物一律放 `tmp/`（已 gitignore）；提交节奏 = 每个 Phase 节点 commit+push（remote: `PeaseAPI/PeaseBar`）
5. 代码注释一律中文（Pease 产品线规范）；UI 文案中文优先

## 10. 进度快照

- **2026-11-22**：完成 §5 全部探测（T1–T9 已取证，`tmp/probe_ax.py`/`tmp/probe_result.json`）；
  E1 首跑被机器重启打断，待重跑（P0.2）。**下一步：P0.2 → P0.6 → Phase 1。**
- 已知风险：
  - 打包成 .app 后辅助功能权限需对新 bundle 重新授权（T1 边界）；
  - macOS 27 小版本可能改动 MenuBarAgent AX 树（每次系统升级后重跑 `tmp/probe_ax.py`）；
  - 图标识别键 = bundleId+AXDescription，同一 App 双图标（如多个 Clash 实例）需在 F4 用 owner 序号消歧（Phase 2 处理）。

## 11. 测试与取证规范

- 交付 UI/交互功能前先写 `tmp/test-plan.md`（逐条用例 + 预期），真机逐条执行并截图到 `tmp/`；
- 涉及图标移动的实验必须可复原：记录前/后坐标，测试后把图标拖回原位；
- 不在未授权的机器上静默降级——权限缺失时给出中文指引。
