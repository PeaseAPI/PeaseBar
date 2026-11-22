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
| F3 | **救援面板** | 无边框 NSPanel 出现在控制图标正下方；网格展示全部图标（名称+归属+刘海徽标）；单击=对真实图标**合成右键**弹出其原生状态菜单（T17：AXPress/左键无效），面板随即收起 | 面板出现在按钮下方；点击面板内图标能弹出对应菜单；含刘海遮挡项 |
| F4 | **分区模型** | visible / hidden / always-hidden 三区，配置键 = bundleId+图标名；面板按区分组展示（空区不占位），格子**右键菜单移区**（NSView.menu，T27）即时持久化 | ✅ 真机 P21–P25 全 PASS：移区即时生效、重启保持、回可见区删键 |
| F5 | **自动收回** | 点击面板外即关（**全局鼠标监听**实现，T19——不依赖 key 状态）；超时自动关（默认 8s，config.json `panel_timeout` 可改，0=不超时；交互续期） | ✅ 失焦即收（T9）；超时 3.0s 精确取证（P27） |
| F6 | **全局快捷键** | 默认 ⌥⌘B 切换面板；**CGEventTap 实现**（T23：Carbon 不可用，事件 tap 只需已有辅助功能权限）；改键设置留 Phase 4 | ✅ 真机 P26 PASS：其他 App 前台时合成 ⌥⌘B 开/关往返成立 |
| F7 | **权限引导** | 辅助功能权限缺失时**不阻塞启动**：状态项正常显示，菜单项「检查辅助功能权限」提供状态反馈与“打开系统设置”按钮（图标显示本身不需要 AX 权限，见 T12） | 无权限时功能受限但不静默：图标在、盘点入口有中文指引 |
| F8 | **顺序编辑器（只读视图）** | 面板列出当前实际顺序（按 x 排序） | 与真实顺序一致 |
| F9 | **状态持久化** | 配置存 `~/Library/Application Support/PeaseBar/config.json` | 重启 PeaseBar 分区/设置保留 |
| F10 | **单实例 + 退出** | 二次启动唤起已有实例（哨兵端口 52877，0.5s 轮询 accept → 弹面板）；右键菜单可退出。注意：普通 `open` 对已运行应用被 LaunchServices 合并、不产生第二进程（T26），哨兵主要服务 CLI/`open -n`/崩溃僵尸场景 | ✅ 真机 P28 PASS：`open -n` 双开 → 第二实例退出、首实例弹面板 |

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
| T6 | `AXExtrasMenuBar` 属性返回值可能是单容器元素（取其 `AXChildren`）也可能直接是数组；MenuBarAgent 是 Group 包 Item，第三方直接是 Item。**PyObjC 关键怪癖**：AX 数组是 `__NSArrayM/NSMutableArray`，`isinstance(x, (list, tuple))` 判不出来，必须用可迭代性判断（axutil._as_list）；MenuBarAgent 子树为**懒加载**，闲置后查询返回空 Group，反复轮询可唤醒 | 盘点器统一走 axutil.copy_children + 空树重试 |
| T7 | 刘海区：`NSScreen.auxiliaryTopLeftArea/auxiliaryTopRightArea` 拼不满整行即为有刘海；本机刘海 x∈[918,1138]（宽 220pt），菜单栏高 38pt；`safeAreaInsets` 在 27 只报 top，**不能**用 | 遮挡判定 = 图标矩形与刘海矩形相交 |
| T8 | CGWindowList 层 24/25 在 27 上只剩 Window Server 的 "Menubar" 背景条；**图标没有自己的窗口** | 位图/位置不能走窗口列表，只能走 AX |
| T9 | `NSStatusItem Preferred Position` 经典存储仅个别域残留（TextInputMenuAgent、CleanMyMac5.Menu） | 顺序写入不靠它；走 ⌘拖拽合成（E2）或 27 顺序文件（需"菜单栏布局访问"TCC，Python 难授权，列为受限路线） |
| T10 | 屏幕录制权限：终端已具备，`screencapture -x`/`-R` 出图正常（E4） | 测试取证与 v2 位图捕获可行 |
| T11 | **菜单栏准入门**（系统设置→菜单栏→允许在菜单栏显示）：列表**自动注册**——App 首次成功创建状态项即入列（TestItem/PeaseBar 均实测）；无“+”手动添加按钮；每 App 一个开关（默认开），关闭后“无法再在菜单栏显示” | 无需引导用户手动放行；但必须保证状态项**尽早创建**（见 T12） |
| T12 | **状态项显示三要素**（E5 对照实验：最小 Swift App TestItem vs PeaseBar）：① 启动不能被模态弹窗阻塞——runModal 卡在状态项创建之前 → 图标永不出现且永不入准入门（修复前 PeaseBar 正是此因）；② 必须走 LaunchServices 正规启动（`open`/Finder/launchd），终端 `nohup` 直启 bundle 二进制时 StatusBarServer 拒绝记账 → 图标不显示且进程 `AXExtrasMenuBar` 报 -25212；③ 图标过多时新图标被**自动收纳**进溢出区（« 按钮）——正常业务非故障 | app.py 启动顺序已按此修复（状态项先建、权限检查非阻塞）；测试/运行一律 `open` 启动 |
| T13 | **AX 可见性联动**：图标被收纳（不可见）时，其 owner 进程 `AXExtrasMenuBar` 返回 -25212；原生按钮展开后同一进程 err=0。即 E1 “被收纳图标不在 AX”的扩展：**连 owner 自己的 AX 树都没有它** | F1 盘点需“展开收纳区→枚举→diff→收起”舞步（含 PeaseBar 自举）；-25212 可用作“图标当前不可见”信号 |
| T14 | **第三方 AX 通道依赖菜单栏可见性**：全屏 App 隐藏菜单栏时，**所有**第三方进程 `AXExtrasMenuBar` 报 -25212（含可见图标）；MenuBarAgent 托管的系统图标树不受影响。激活非全屏 App 恢复菜单栏后立即恢复。且 -25212 无法区分「无状态项 / 被收纳 / 菜单栏隐藏」，盘点器不做精确判定 | 盘点/移动前先确认非全屏；后台守护（activationPolicy==2）直接跳过枚举 |
| T15 | **open/LaunchServices 启动环境 locale 是 ASCII**：日志文件 `open()` 不显式指定编码时，写中文 print 抛 UnicodeEncodeError，且崩在 `app.run()` 之前——表象是 py2app "Launch error" 弹窗 + 状态项永不出现 + 终端跑同一脚本正常（环境差异） | app.py 日志落盘显式 `encoding="utf-8", errors="replace"`；排障看 `~/Library/Logs/PeaseBar.log` |
| T16 | **bundle 需独立辅助功能授权**（授权终端不继承 open 启动的 .app）；权限组在新版系统设置「设备控制和数据访问」页；修改 TCC 开关必须 Touch ID/密码人类认证（无法绕过）；自动化流程：AX 定位 PeaseBar 行的 AXCheckBox → AXPress 可弹认证框（合成点击只能选中行） | bundle 授权后盘点/合成事件全部可用；重装/换 bundle 需重走授权 |
| T17 | ~~状态项菜单无法被程序触发，右键合成是唯一有效路~~ —— **两半都错**（见 T59/T60 与 T65/T66）：27.2.1 上图标由 MenuBarAgent 托管，合成右键只对**部分** App 有效（实测 8/25），既不是万能也没全线失效 | 触发改走 trigger.py 阶梯（AXPress → AXShowMenu → 合成右键）；frame 仍为 CG 坐标与 CGEvent 同系 |
| T18 | **NSPanel.hidesOnDeactivate 默认 YES**：App 失活时系统自动藏面板，但**不翻转 isVisible()、不触发 resignKey**——toggle 状态机错乱（CGWindowList/AX 已无此窗、App 内仍认为可见）。必须显式 `setHidesOnDeactivate_(False)` | panel.py 显式关闭；失焦收回改走全局监听（T19） |
| T19 | **合成事件场景 App 激活是半吊子**：`frontmostApplication` 名义上切换了，但 `NSApp.isActive()=False`、面板 `isKeyWindow()` 永远 False（先 makeKey 后 activate / 先 activate 后 makeKey 都一样）→ resignKey 路线不可靠。改用 **NSEvent 全局鼠标按下监听**（不依赖 key 状态，合成/真实场景都有效）；注意 App 未激活时 global monitor **也会收到状态图标自身的点击**，必须忽略图标区域与面板内部，否则与 toggle 双火（刚开就被收回） | panel.py `_outsideClick_`：面板内/控制图标区域忽略，其余左键按下即收回 |
| T20 | **NSWindow 没有 `setFrame:` 选择子**（PyObjC 无 `setFrame_`），只有 `setFrame:display:`；直接调 `setFrame_` 抛 AttributeError。且面板复用路径（关闭后再开，`setReleasedWhenClosed_(False)` 对象存活）才会走到这段——首建路径不触发，toggle 测试才暴露 | panel.py `_ensure_panel` 复用分支用 `setFrame_display_(rect, True)` |
| T21 | **NSMenuItem 必须显式 `setTarget_`**：nil-targeted action 沿响应链查找，而 ControlItem 不在响应链里——点击菜单项后 action 落空（菜单正常关闭但处理函数永不执行，无任何报错） | control_item.py build() 对三个菜单项 setTarget_(self) |
| T22 | **并行 AX 枚举**：串行遍历 ~80 进程查 AXExtrasMenuBar 耗 ~19.8s（大量 helper 进程响应慢是瓶颈），ThreadPoolExecutor(max_workers=16) 并行 + NSWorkspace 元信息主线程预取 → **~2.1s**（结果一致）；无 AX 权限时逐进程查询会长时间阻塞，`list_items()` 先 `AXIsProcessTrusted()` 快速失败 | inventory.py 并行化与快速失败路径 |
| T23 | **PyObjC 无 Carbon 绑定**（`from Carbon.HIToolbox import RegisterEventHotKey` → ModuleNotFoundError）；NSEvent 全局键盘监听又需要「输入监控」新授权。正解：**CGEventTap**（kCGSessionEventTap + listen-only + keyDown mask）——只依赖已有的辅助功能权限，不拦截事件，回调经 CFRunLoopSource 挂主 runloop 与 UI 同线程 | hotkeys.py ⌥⌘B；真机 P26 验证成立 |
| T24 | **`imageWithSystemSymbolName_accessibilityDescription_` 第二参传 None → 状态项 AXDescription 回落 SF Symbol 系统默认描述**（"ellipsis.circle.fill" → 「更多」），盘点 label、配置键、面板格子全被污染且无任何报错 | control_item.py 显式传 "PeaseBar"；状态项图标必须自带可读 accessibilityDescription |
| T25 | **NSWorkspace.runningApplications 列表秒级滞后**：已死 pid 不移除、新 pid 不收录（实测 pkill+open 后 15s 仍只返回僵尸 pid）——做进程重启/双开交接验证会误判 | 测试脚本验证进程存活/交接一律用 `pgrep -f`（内核进程表，无缓存） |
| T26 | **`open App.app` 对已运行应用被 LaunchServices 合并，不产生第二进程**（实测无任何哨兵/已有实例日志）——二次启动唤醒路径在普通 open 下永远走不到；真实用户从 Dock/Finder 再开同样被合并 | 双开测试用 `open -n` 强制新实例；哨兵价值在 CLI/崩溃僵尸场景 |
| T27 | **NSView.menu（setMenu_）右键自动弹出且不干扰左键 action**；菜单项同样必须 setTarget_（T21），合成左键点菜单项有效（延续 T14 模式）；测试中点击落空会残留菜单吞掉下一轮右键（菜单 tracking 捕获所有鼠标事件），需 Escape 兜底 | panel.py `_cell_menu` 格子右键移分区 |
| T28 | **macOS 27 状态项窗口不进 CGWindowList**（25 项全部匹配不到自己的窗口）——图标像素只能「截整条菜单栏条带 + 按 AX frame 裁剪」；屏幕录制权限同样按 bundle 记账（T16 同族） | capture.py 条带管线；无权限时走图标兜底链，绝不退化成显示名字 |
| T41 | **自家状态项收不到合成点击**（别家图标部分能收到，见 T66；自家这条只能靠 AXPress 投递）：右键→「设置…」这条路弹不出菜单；另踩 **PyObjC 方法命名坑**：不以 `_` 结尾的带参方法（`_move(self,a,b)`）在建类时报 BadPrototypeError，启动即死且无日志 | 测试旁路 ⌥⌘S 直达设置；真实鼠标可用性待人工复核；内部带参方法定名 `applyMove_to_` |
| T44/T45 | **NSImage 符号图只能用类方法** `imageWithSystemSymbolName_accessibilityDescription_`（`alloc().initWithSymbolName_` 不存在，静默返回 None → 格子空白）；蓝牙/AirDrop 只在**私有符号集**，走 `imageWithPrivateSystemSymbolName_...`（getattr 软调用） | capture.py `_symbol_image`；兜底链永远给图 |
| T46 | **-25212 是 kAXErrorNoValue（「这个属性没值」），不是「被收纳」**：本机 92 个进程的 `AXExtrasMenuBar` 全部报 -25212（含自家状态项），只有 MenuBarAgent 报 0——旧盘点通道因此塌到 4 项。Thaw 同样用它区分「这个 App 没图标」 | 自有通道降为兜底；「被收纳」改由收纳按钮横坐标判定 |
| T47/T48/T53 | **macOS 27 的真相：图标全部由 MenuBarAgent 托管在自己窗口里画**（照搬 Thaw `MenuBarAgentWindow`）：`MenuBarAgent → AXWindows → AXWindow(0,0,2056,39) → 每图标一个 AXGroup 槽位 → 槽位内是跳进程引用元素`；`AXUIElementGetPid(该元素)` 直接给出归属 App 的 pid——**读一个进程就看清整条菜单栏**（实测 0.05s）。两张面：一张内层 AXApplication（只给身份），一张内层 AXButton（可 AXPress、带真字形矩形）；系统模块则是 `AXGroup(AXHostingView) → AXMenuBarItem(AXMenuExtra)` | inventory.py `_slot_inspect`/`_collect_hosted_items`（按 (pid,x,w) 归并，同 pid 已有可点元素时丢空壳） |
| T52/T54 | **托管按钮只 advertise `AXPress`**（无 AXShowMenu，系统模块除外）；AXPress 能真投递到自家状态项，但受话方 `NSApp.currentEvent` 为 **None**（MenuBarAgent 经 `addTarget:action:forControlEvents:` 转发语义主点击，不转发右键） | control_item.py `onStatusClick_`：无事件的 action 一律当主点击，否则面板/设置永远点不开 |
| T55 | **图标 label 常常是「会变的活文本」**（TG Pro=温度、PeaseClash=刚复制的命令、QQ 标题=未读数）——拿它当配置键会使每次盘点都不是同一个图标；展开收纳区后旧位会残留「只有身份无可点元素」的重复项 | MenuItem 新增 `key_part`（反向域名形状的 AXIdentifier 优先，否则应名）+ `stashed`；同 App 双图标按横坐标加 `#rank`；实测两态均 25 项/24 项可 AX 点/无重复键 |
| T59/T60 | ~~合成 HID 点击在 27.2.1 上彻底失效~~ —— **概括过度，已被 T65/T66 更正**：当时只试了 OneDrive/微信/控制中心/时钟（恰好都是不吃合成点击的一家）与**被收纳**的图标（坐标本就不可信），据此下了全称结论 | 结论保留的部分：触发不能只靠坐标；作废的部分：见 T65/T66 |
| T61 | **AXPress 逐图标效果图谱**（25 项全试）：ToDesk/EdgeShelf/Alcove/钉钉/PeaseClash/TG Pro/One Switch/TextInputMenuAgent → 弹原生菜单（layer 101）；微信/QQ/Synology → 弹 App 主窗口（左键语义）；控制中心/Wi‑Fi → 展开面板；**err=-25204（cannotComplete）照样弹菜单，err=0 也可能只做了不开窗的默认动作**——错误码不能当判据 | trigger.py：按「有没有新窗口」分级试 AXPress → AXShowMenu → 合成右键（同 Thaw ConcealedItemOpenMethod/LearnedOpenMethods 思路） |
| T62/T63 | **设置格子用 PushOnPushOff 切换态（`setButtonType_(1)`）→ AX 报成 `AXCheckBox` 而不是 `AXButton`**；测试若按角色认格子会全盘找不到。另：上一用例留着的设置窗口会让 `cells()` 把两边格子混在一起（假 FAIL） | 取证脚本按**窗口作用域**取格子（panel_win/settings_win_el），角色不再参与判定 |
| T65/T66 | **合成点击没死，是按 App 家族分裂**（25 项 AXPress×合成右键对照）：AXPress 开窗 17/25、合成右键 8/25；**只有点击有效**=LaunchOS、Little Snitch Agent（后者根本不给 AX 元素），只有 AXPress 有效=Qoder/欧路词典/ToDesk/EdgeShelf/Alcove/TextInputMenuAgent/CleanMyMac/AlDente/控制中心；**被收纳的 9 项点击 0/9**（frame 不是画出来的位置，点击落邻居槽位）=与 Thaw `isElectronItem`「Electron 系忽略合成点击必须 AX press」同源。字段工法另有三条硬坑：投 session tap 而非 HID tap、必须打 `kCGEventTargetUnixProcessID`、down 的 clickState=1/up=0 且 mouseUp 发两次；**照 Thaw 塞 windowID/「指针下窗口」字段（我们只能塞假哈希）会让钉钉的菜单不弹，`CGEventPostToPid` 同样归零** | trigger.py 阶梯补第三档（可见且 AXPress 无窗 → 补一次合成右键，P55 取证 LaunchOS 生效）；被收纳项显式不试坐标点击 |
| T67/T68 | **量「对端主线程忙不忙」只能用会抵达对端执行的动作，读属性一律不灵**：把 PeaseBar `SIGSTOP` 住 0.5s，`AXWindows`/`AXChildren` 仍然 0.000s 秒回（客户端不等对端）；而对自家状态项 `AXPress` 会排队：空载 0.111s vs 被冻 0.746s | P56 用 AXPress 往返时长当探针，证明阶梯搬后台后主线程不再被占 |
| T69/T70 | **两个 AppKit 枚举值把「只显示图标」悄悄破坏了**：`setImagePosition_(5)` 当时按「NSImageOverlaps」写，其实 5=**NSImageAbove**（图在标题上方），空标题下图标被顶到格子**上沿**（t72 亮像素定位：距顶 2pt），居中要 `NSImageOnly`=1（修后 14pt=(40−12)/2）；`setImageScaling_(3)` 同理是 **ProportionallyUpOrDown**（把 18pt 小图撑满整格），ProportionallyDown=0。另：`NSButton` 的 rounded 胶囊会在图标后面垫一块灰底（真 bug 构建实测格内 65% 像素不是面板背景）——必须 `setBordered_(False)`；设置窗口的选中态改为自己画一层 layer 淡底（选中仍由 state 承载，AX 仍报 AXCheckBox，T63 不破） | panel.py `_make_cell` / settings.py `_make_tile`+`_paint_tile`；枚举一律用命名常量，不写字面量 |
| T71 | **无边框 NSButton 不执行 imageScaling**：宽图标（网速/温度这类文字条，裁出来 80–104pt）直接溢出格子压邻居。宽度收口只能在抓取端做：`fit_box()` 改 NSImage 的**点尺寸**（只缩不放）；Retina 下裁图像素是点尺寸 2 倍，缩点尺寸反而更清晰 | capture.py `GLYPH_MAX_W=40` + `fit_box()`（3 条单测） |
| T72 | **本机刘海在 macOS 27 上是死区**：内建屏 notch=(918,1138)，但 26 项全落在刘海两侧可用区（收纳项 x≈1167–1176、收纳按钮 1190、可见项 1222–1999）→ `notched` 恒 False，系统把挤不下的图标塞进收纳（stashed）而不是画到刘海底下。Thaw 同判断：`LayoutSolver.planNotchOverflow` 把溢出项移到 hidden 区，并在**设置页**用 `OutOfRoomWarning`（"Some items don't fit in the menu bar" + "Move to Hidden"）/`.outOfReach` 提示，不在格子上打角标 | P43 用构造项验证角标本体；Phase 4 设置页照此加「挤不下/够不着」提示行 |
| T73 | **托管元素会失效，拿旧元素按只能等到超时**：`inventory.list_items()` 返回的 MenuBarAgent 树元素在菜单栏一变（展开收纳区/图标增减）就过期，对它 `AXPress` 不报错而是耗满 messaging 超时（P56 因此假 FAIL 成 1.501s；t73 分解证明阶梯中读/按两条通道都 <0.11s） | 探针每轮重新 `list_items()` 取元素，并筛 `role == "AXButton"` 的可点面 |
| T74 | **屏幕录制权限按 bundle 记账且 ad-hoc 重建后保留**：终端 python3 preflight=True 不代表 App 有；App 必须主动调过 `CGRequestScreenCaptureAccess()` 才进系统列表，授权后要重启进程；`py2app -A` 重建（cdhash 变）后授权仍在（实测两个新实例都能截到像素）。另：**像素度量必须在真 bug 构建上标定**——人工涂色两次骗过我们（先涂了个与背景同色，后是涂的位置与真胶囊内缩不一致，度量对真 bug 直接报 0.00）；把 panel.py 改回 `setBordered_(True)` 跑真机才定下阈值 | t74_block.py 标定（缺陷 0.35–0.53 vs 修复 0.87–0.96，断点 0.70）；P42 判据 `_block_check` |
| T75 | **1.501s 是 messaging 超时的固定价，不是时长证据**：`err=-25204`（元素没答话）也花 1.501s，所以计时探针必须**同时记 err**；t76 对照组（同一时刻别家图标：搜狗拼音基线 1.501s/-25204、随后三轮 0.001s）证明这是托管树/别家进程的事。另：**App 被 SIGSTOP 时，MenuBarAgent 会把自家可点元素从托管树里摘掉**（t77 三轮全取不到元素）——所以下一次 P56 的 1.5s 既可能是“我们主线程真卡住”也可能是“探针没落到能答话的元素上”，单靠时长分不开 | P56 判据重写：只看 err=0 的样本、阶梯中采 3 轮取最好值，异常值当场补对照组；灵敏度由 t77 验证（真冻住时 err=0 样本为 0 → 判 FAIL） |
| T76 | **菜单栏被全屏 App 遮住时，整条条带是纯黑的**（连 `screencapture -R 0,0,2056,24` 也全零），而 `CGPreflightScreenCaptureAccess()` 照样返回 True——「有权限」与「菜单栏此刻画没画图标」是两件事。按 frame 裁到的是纯背景，抠像后一个像素不剩，旧实现把这张**全透明图**当成「截到了」交给按钮 → P42 实测 16 格空白（正好是非收纳的 16 项，有图的 9 格全是走兜底的收纳项） | capture.py `image_for_item` 无墨（`MIN_GLYPH_PIXELS=20`）返回 None → 兜底链顶上；新增 `strip_has_content()` + `last_stats`；设置页加「菜单栏当前没画出图标」提示行（P64 构造纯黑条带取证） |
| T77 | **AX children 自然顺序 == 几何阅读序 == 模型顺序**（diag 实测设置窗 25 格逐项一致）→ 取证序列直接按自然序读，别拿坐标排：窗口改高度的动画里同一行格子 y 会飘 2–3px（Wi‑Fi 368 vs 同行 366），按 `(round(y),x)` 排会把一行拆成两行、序列「花掉」假 FAIL | t_p4.py `win_tiles`/`ids_seq` 用自然序；旧的 row_sorted/sec_seq/panel_seq 废弃 |
| T78 | **图标名是活文本，不能当身份**：TG Pro 的名字 "Performance Core 8 (Highest): 59°C" ↔ "Core 7 … 57°C" 在两次读取之间自己变脸，拿名字比的序列前后对不上。产品侧给格子 `setAccessibilityIdentifier_(配置键)`（设置与面板同一套）；配置键由 key_part 生成（T55）与活文本无关 | settings.py `_make_tile` / panel.py `_make_cell`；单测新增 2 条身份钉桩（活文本改名不改身份、格子无标题） |
| T79 | **主线程忙时合成按键会被吞**（刚开窗口正在盘点/取图那阵）：睡固定时长等按键生效赌输过（P81/P83 假 FAIL），必须「发键 + 等预期效果」（轮询配置变化/「已选：」文本变化/该不变的不变）。另：本机 PyObjC 没有 `NSWorkspace.runningApplicationWithProcessIdentifier_`/`…WithPID_`，`runningApplications()` 被绑成实例方法（类上调报 Missing argument: self）→ 拉前台走 AX：AXMain+AXRaise，拿 AXFocused 当硬判据，拿不到焦点记 SKIP 不假 FAIL | t_p4.py `press_edit/press_focus/press_nochange/bring_front/focus_first`（点选定焦比裸键走路稳）；P53 判据同 T61 改按「生效+反应=有」（err 码在目标忙时不可信） |
| T80 | **真机侦查 Thaw 3.0.0-beta.7 设置界面**（用户装了 beta，dump 全部 11 页于 `tmp/thaw_ref/`：截图+AX 树）：NavigationSplitView 侧栏 11 页、窗口 1018×720、每页带副标题、顶部工具栏含搜索；通用页=SMAppService 登录时启动/语言/主题/精简模式；布局页=条形分区 + 每区「按名称排序」MenuButton + 拖拽 + ⌥-arrows + Reset Layout；关于页=版本 + 复制版本信息 + 源码链接；疑难解答页=权限状态 + 诊断导出 | 对标取舍（定位「选项精简、中文优先」，不抄模块生态）：做五页侧栏（布局/通用/快捷键/疑难解答/关于，760 宽），结构、开机自启、排序/重置、疑难解答、关于一条不能输（Phase 4e-1） |
| T81 | **PyObjC 会把单下划线开头的带参方法导出成选择子**：`_label(self,view,x,y,…)` 建类即报 BadPrototypeError「expects 0 arguments」，启动即死（T41 同族扩展）；内部 helper 必须 ≥2 下划线命名。另：sed 批量改名时 `self\_mk_label` 的转义把点吃掉，产出 `self_mk_label(` 二次坑 | settings.py helper 定名 `_mk_label/_mk_row/_mk_btn` |
| T82 | **T63 第二战**：侧栏页签最初 `setButtonType_(1)`（PushOnPushOff）→ AX 报成 AXCheckBox，取证 `find_button`（按 AXButton 找）全部漏切页。修复：页签不设 buttonType，保持 AXButton，选中态用加粗字体 + layer 白垫底表达（也不与格子判据碰撞） | settings.py `_build_sidebar`（带注释钉住此坑） |
| T83 | **PyObjC 桥成属性的方法不能用尾下划线调**：`NSProcessInfo.operatingSystemVersionString` 是属性，`operatingSystemVersionString_()` 抛 AttributeError；且 **action 回调里的异常被 AppKit 吞进系统日志**（我们的日志文件里连 traceback 都没有），表象是「按钮按了没反应」（P98 假 FAIL 真因）。另两条同晚取证：本机 PyObjC 无 `NSButtonSwitchType`（`NSButtonTypeSwitch` 画出来是方框），拨动开关用 **NSSwitch**；AX 属性 `AXEditable` 本机探针拿不到，找输入框只按 role=AXTextField | settings.py `onCopyVersion_`（属性直调）/`_page_general`（NSSwitch + 独立标题文本 + AXIdentifier） |
| T84 | **SMAppService**：`mainAppService().status()` 枚举 NotRegistered=0/Enabled=1/RequiresApproval=2/NotFound=3；`registerAndReturnError_(None)` 返回 (ok, error) 元组；**adhoc 签名的 py2app -A 开发包报 NotFound**——开机自启的开关状态必须以系统回读为准（写后重读 status，失败拨回并把错误上屏），正式包的取证要等 Phase 4b 打包后（P95 开发包合法 SKIP） | settings.py `_LOGIN_STATUS` 映射 + `onLaunchToggle_` |
| T85 | **菜单栏管理器互斥**：Thaw beta 运行中会把 PeaseBar 的控制图标**原生收纳**（盘点里没有 owner=com.pease.peasebar、菜单栏截图无图标，而 App 日志照常报「控制图标就绪」）——t_p2b 首轮 P42/P44/P45/P54/P56 连环 FAIL 全因此环。退出 Thaw 后盘点 14→26 项、图标回来 | 取证前 `osascript -e 'quit app "Thaw"'` 并核对盘点项数正常（写入 §11 规范） |

## 6. 隐藏与顺序的实现策略（按可行性递减，实验后定型）

| 策略 | 机制 | 状态 |
|------|------|------|
| A 原生收纳引导 | 把图标 ⌘拖进刘海区触发系统收纳（E2 已验证成立）；原生按钮可 AXPress 展开/收起（E1 已验证） | **v1.x 正式路线** |
| B per-app 开关写入 | 27 上存储不可达（E3），放弃 | ✗ 已否决 |
| C 面板代持（兜底） | 图标不动，“隐藏”只是面板分区过滤 + 救援触发；顺序编辑只读 | **v1 保底，一定可用** |

> 补充：原生收纳按钮的当前状态可从按钮描述读取——「显示隐藏菜单栏项目」=收起态、「隐藏菜单栏项目」=展开态；
> 被收纳的图标不展开时**不在 AX 中**（无法静默读取清单，T13），面板要列收纳清单需“展开→枚举→diff→收起”舞步，
> v1 先不做，面板提供“一键展开/收起”按钮（F12）。
>
> E5 补充：菜单栏图标溢出时系统会**自动收纳**新图标（无需拖入刘海）；PeaseBar 自己的图标也会被收纳——
> 这正是产品要解决的核心场景，F3 面板必须能呈现“被收纳的图标”（含 PeaseBar 自身，注意自举）。

## 7. 架构与模块

```
PeaseBar/
├── peasebar/
│   ├── __main__.py      # 入口：单实例检查 → 权限检查 → 启动
│   ├── app.py           # NSApplication 生命周期、Accessory 策略、模块装配
│   ├── axutil.py        # AX 基础封装：copy/children/point/size/actions/press + CG↔AppKit
│   ├── inventory.py     # F1 盘点引擎：托管通道主用（MenuBarAgent 窗口 + GetPid）
│   │                    #   + 自有通道兜底；标 notched/stashed/key_part（T46/T47/T55）
│   ├── capture.py       # F3 图标位图：截条带→按 AX frame 裁剪→抠像→单色判定；
│   │                    #   无屏幕录制权限时的图标兜底链（永远给图，不给名字）
│   ├── trigger.py       # F3 触发执行端：阶梯试 AXPress→AXShowMenu→合成右键（可见项）→无元素直接点击（T61/T65/T66）；
│   │                    #   open_item_async 把整条阶梯放后台（阶梯全是跨进程等待，主线程会冻面板/热键）
│   ├── control_item.py  # F2 控制图标：NSStatusItem、左右键分发（无 currentEvent 的 action 当主点击，T54）
│   ├── panel.py         # F3 救援面板：三区网格（只显图标）、调 trigger 触发图标、
│   │                    #   收纳区展开/收起按钮、全局监听失焦收回（T19）、超时收回（F5）
│   ├── sections.py      # F4 三区模型：纯逻辑分桶 + config.json 原子读写（含 panel_timeout）
│   ├── settings.py      # F14 设置窗口：分区编辑的唯一入口（单击选中+按钮/右键移区，T41）
│   ├── mover.py         # F11 ⌘拖拽合成写入（Phase 3，实验通过后启用）
│   └── hotkeys.py       # F6 全局快捷键 ⌥⌘B/⌥⌘S（CGEventTap listen-only，T23；Carbon 在 PyObjC 不可用）
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
- [x] P0.2 **E1**：原生收纳按钮 AXPress 可切换；展开后收纳图标出现在刘海**左侧**（证据 `tmp/bar_before/after/restored.png`）；按钮描述在「显示/隐藏菜单栏项目」间切换，可读状态
- [x] P0.3 **E2**：合成 ⌘拖拽**有效**——移动图标成功（证据 `tmp/drag_*.png`）；拖到刘海边缘会触发**系统自动收纳**（策略 A 成立）；拖回复原精确（x=1270 复原成功，证据 `tmp/restore_*.png`）
- [x] P0.4 **E3**：收纳持久化存储不可达（MenuBarAgent 无容器偏好；候选 defaults 域无变化，证据 `tmp/probe_stash_store.py` 输出）→ 策略 B 判定为受限不可用，不进入 v1.x；顺序写入只走 ⌘拖拽
- [x] P0.5 **E4**：`screencapture -x -R` 条带截图可用（终端已有屏幕录制权限），取证链路成立
- [x] P0.6 骨架：`__main__/app.py` AppKit 生命周期 + Accessory + 单实例 + 右键菜单可退出；启动顺序修复（状态项先建、权限引导非阻塞）；**E5** 准入机制对照实验：状态项自动入准入门、图标现身收纳展开区（证据 `tmp/bar_peasebar_icon.png`、`tmp/bar_expanded_zoom.png`、`tmp/allow_list_1.png`）→ **节点提交**

### Phase 1 v1 核心（F1–F3, F8）
- [x] P1.1 `axutil.py` + `inventory.py`（含遮挡判定、两级结构兼容、轮询刷新）：终端取证通过——系统 4 项（Wi‑Fi/控制中心/时钟/收纳按钮，名称坐标全对）+ 第三方 12 项与菜单栏实际一致；修复 `__NSArrayM` 判断怪癖与 MenuBarAgent 懒加载空树（T6/T14 取证写入 §5）；并行枚举提速 19.8s→2.1s（T22）
- [x] P1.2 `control_item.py`（左键/右键分发 + 中文菜单 setTarget_ 修复 T21 + 权限项反馈）
- [x] P1.3 `panel.py` 救援面板（网格、刘海徽标、合成右键触发 T17、objc.super 修复、setFrame_display_ 复用修复 T20、hidesOnDeactivate 修复 T18、全局监听失焦收回 T19）
- [x] P1.4 `tmp/test-plan.md` 逐条真机执行 + 截图取证：T1–T15 全部 PASS（执行记录见 tmp/test-plan.md）；修复链见 §10 晚间快照 → **节点提交**

### Phase 2 分区与维持（F4–F7, F9–F10）
- [x] P2.1 `sections.py`（三区纯逻辑 + JSON 原子持久化）+ 面板按区分组 + 格子右键移区（T27）：真机 P21–P25 全 PASS（修菜单文案反转、T24 label「更多」→「PeaseBar」）
- [x] P2.2 超时自动收回（默认 8s，config `panel_timeout`，交互续期；P27 3.0s 精确取证）+ `hotkeys.py` ⌥⌘B（T23 CGEventTap；P26 PASS；含 NSRunLoopCommonModes 未导入 NameError 修复）
- [x] P2.3 单实例唤醒接线（哨兵 0.5s 轮询 accept → show；P28 `open -n` PASS，T26 事实同记）；权限引导已有（菜单项 alert，T14），引导窗升级留 Phase 4
- [x] P2.4 tests/ 纯逻辑单测 29 项全 PASS（分区规划 + 遮挡判定；拓出并修复 rect_intersects 零宽误报）；Phase 1 回归 T7–T12 全绿 → **节点提交**
- [x] P2b 按用户两项定调重做 UI 分工（**编辑只在设置窗口、面板不编辑**；**只显图标不显名字**，名字进 tooltip）：
      `capture.py` 条带抓取 + 色键去背 + 兜底链（T28/T44–T46/T71）、`settings.py` 设置窗口、`trigger.py` 四档阶梯
      并搬后台（T61/T65–T68）；胶囊底色、图标居中、宽图标溢出三个真缺陷均 P42 当场拓出并修复（T69–T75）；
      真机 P41–P56 共 15 条全 PASS，单测 54 项 → **节点提交**

### Phase 3 顺序写入（F11–F12，视 E2/T66 结论）
- [ ] P3.1 `mover.py` ⌘拖拽写入 + 编辑器上移/下移/拖拽
      ⚠ **开工前先做一次性探针**（T66）：合成点击按 App 家族分裂、被收纳项坐标不可信，
      E2 当年验的 ⌘拖拽成立是因为它由 MenuBarAgent 的托管窗口接单——拖拽仍可行，
      但目标槽位必须按**画出来的位置**瞄准（Thaw DrawnItemFrame 的做法）
- [ ] P3.2 原生收纳联动（面板按钮调原生 AXPress）
- [ ] P3.3 真机顺序编辑回归（移 3 个图标并复原）→ **节点提交**

### Phase 4 完整化（F13–F14）
- [x] P4.1 设置窗口（中文、简单模式默认）；照 Thaw 加「挤不下/够不着」提示行（T72：
      `OutOfRoomWarning`/`.outOfReach` 那类信息放设置页，不在格子上打角标）；
      计数与盘点同源不二次枚举，提示只给计数与指引绝不列名字（P61–P63 真机 PASS）；
      另加「菜单栏当前没画出图标」一条（T76，P64 构造纯黑条带取证）→ **节点提交**
- [x] P4.1b 设置页编辑本体（照 Thaw LayoutBarsSection 的键盘契约：区内顺序持久化 + ⌥←/→ 改序
      + ⌥↑/↓ 换区落末尾 + ⌘1/2/3 移区 + ⌘Z 撤销 + 底部前移/后移/撤销按钮；
      编辑只在设置窗口，救援面板不编辑）：真机 P81–P86 全 PASS、单测 95 项（T77–T79）→ **节点提交**
- [x] P4.1c 设置窗口侧栏多页化（对标 thaw@beta 3.0.0-beta.7，T80）：布局/通用/快捷键/疑难解答/关于
      五页（窗口 760 宽，标题「PeaseBar 设置 · 页名」，重开归位布局页）；布局页补每区「按名称排序」
      与「重置布局」（NSAlert 确认 + ⌘Z 可回）；通用页 NSSwitch 开机自启（SMAppService 写后回读，T84）
      + 超时输入框；疑难解答页权限对照/重新抓取/打开日志/盘点摘要；关于页版本+复制+源码链。
      真机 P91–P99：8 PASS + P95 SKIP（开发包 NotFound，待正式包复测）；P100 回归全绿（含 P53/P63/P64
      判据按环境漂移修正后复验，T85；单测 99 项）→ **节点提交**
- [ ] P4.2 py2app 打包 + AppIcon 资产 + SMAppService 开机自启
- [ ] P4.3 全量回归 + README 使用说明 → **v1.0 发布节点**

## 9. 续作指引（重启后从这里开始）

1. `cd /Users/daydream/Project/PeaseBar`
2. 读本文档 §8 找到第一个未勾选项；进度快照见 §10
3. 环境自检：`python3 -c "import ApplicationServices as AS; print(AS.AXIsProcessTrusted())"` 应为 True；
   依赖缺失则 `python3 -m pip install --user pyobjc-framework-Cocoa pyobjc-framework-Quartz pyobjc-framework-ApplicationServices`
4. 临时/测试产物一律放 `tmp/`（已 gitignore）；提交节奏 = 每个 Phase 节点 commit+push（remote: `PeaseAPI/PeaseBar`）
5. 代码注释一律中文（Pease 产品线规范）；UI 文案中文优先
6. 启动/重启 PeaseBar 一律 `open /Applications/PeaseBar.app`（开发态构建：`python3 setup.py py2app -A && ditto dist/PeaseBar.app /Applications/PeaseBar.app`）；**切勿**终端直启二进制（T12：StatusBarServer 拒绝记账，图标不显示）
7. 排障先看 `~/Library/Logs/PeaseBar.log`（app.py 落盘，UTF-8，见 T15）；open 启动的进程 stdout/stderr 不可见
8. 新 bundle 首次跑需授权辅助功能（T16）：系统设置「设备控制和数据访问」页打开 PeaseBar 开关（需 Touch ID 认证）
9. 测试脚本轮询等待面板窗口出现（盘点 ~2s，固定 sleep 会竞态）；参考 `tmp/t34_expand_click.py`/`tmp/t8_t12.py` 的 wait_panel 模式；进程存活/交接验证用 `pgrep`（T25）；双开唤醒测试用 `open -n`（T26）
10. 纯逻辑单测：项目根目录 `python3 -m unittest discover -s tests -t .`（99 项，不需 GUI/AX 权限）

## 10. 进度快照

- **2026-11-22（上午）**：完成 §5 全部探测（T1–T9 已取证，`tmp/probe_ax.py`/`tmp/probe_result.json`）；
  E1 首跑被机器重启打断。
- **2026-11-22（下午）**：E1/E2/E3/E4 全部完成（见 Phase 0 勾选项与 §6 结论），架构定型：
  v1 = 面板代持（C）+ 原生收纳联动（A）；⌘拖拽合成有效（mover.py 可开工）。
  **下一步：P0.6 骨架 → Phase 1。**
- **2026-11-22（午后）**：P0.6 骨架完成并冒烟验证（图标已现身，当前被系统自动收纳，见 T13）。
  排障「图标不显示」定案三层根因（权限弹窗阻塞启动 / 终端直启链被拒 / 自动收纳属正常业务），
  全部取证并修复：T11–T13、E5 写入 §5/§6，app.py 启动顺序改为「状态项先建、权限非阻塞」。
  **下一步：Phase 1（P1.1 盘点引擎 axutil+inventory）→ P1.3 面板。**
- **2026-11-22（傍晚）**：P1.1 盘点引擎完成并终端取证（系统 4 项 + 第三方 12 项与实际一致）。
  过程中挖出两个基础事实：PyObjC AX 数组是 `__NSArrayM`（isinstance 判不出）与 MenuBarAgent
  懒加载空树（轮询唤醒），连同 T14（全屏隐藏菜单栏时第三方 AX 全线 -25212）写入 §5。
  **下一步：P1.3 救援面板（panel.py）→ test-plan 真机取证 → 节点提交。**
- **2026-11-22（晚）**：P1.2/P1.3/P1.4 全部完成（Phase 1 收官）。面板从「构造即崩」走到「15 条用例全 PASS」：
  ① PyObjC 13.0 super 修复（objc.super）；② open 启动中文日志崩溃（T15，encoding 修复）；
  ③ bundle 独立 AX 授权（T16，Touch ID 人机协作）；④ 盘点并行化 19.8s→2.1s（T22）；
  ⑤ T7 救援触发五连败后确立**右键定律**（T17）；⑥ toggle 复用路径 setFrame_ 崩（T20）；
  ⑦ 面板被系统偷藏（T18 hidesOnDeactivate）；⑧ 失焦收回改全局监听（T19，含图标点击双火修复）；
  ⑨ 右键菜单 action 落空（T21 setTarget_）。修复后 T1–T15 全 PASS
  （toggle 往返/失焦收回/收纳区按钮往返/刷新/右键菜单/权限 alert/坐标校验）。
  注意：最终回归时用户切换了显示状态（远程会话全屏），T14 事实复现（盘点塌缩到 4 系统项）——
  属环境干扰非缺陷，全部核心修复均有单点 PASS 证据。
  **下一步：Phase 2（sections 三区 + 持久化 + 快捷键 + 超时收回）。**
- **2026-11-22（夜）**：Phase 2 收官（P2.1–P2.4）。新事实 T23–T27 写入 §5：
  ① Carbon 不可用 → ⌥⌘B 改 CGEventTap（P26 PASS）；② SF Symbol 默认描述污染状态项 label（T24 修复）；
  ③ NSRunLoopCommonModes 未导入 NameError 被 show() 大 try/except 吞——面板照常显示但超时静默失效
  （教训：交付前 grep 日志 traceback）；④ 分区闭环 P21–P25 PASS（右键移区+重启持久化+回区删键）；
  ⑤ 单实例唤醒接线 P28 PASS（`open -n`；普通 open 被 LaunchServices 合并，T26）；
  ⑥ 超时收回 P27 3.0s 精确 PASS；⑦ tests/ 29 项纯逻辑单测全绿（拓出 rect_intersects 零宽误报并修复）。
  Phase 1 回归 T7–T12 全绿（分区改造未破坏左键/toggle/收纳区链路）。
  **下一步：Phase 3（mover.py ⌘拖拽顺序写入 + 编辑器；原生收纳联动 F12）。**
- **2026-11-22（深夜）**：按用户定调两项：① **分区/顺序编辑全部搬进设置窗口**（面板只找回+触发，照 Thaw 分工）；
  ② **UI 永远只显图标、不显名字**（名字进 tooltip；无屏幕录制权限时用兜底链：22 项 App 图标 + 3 项系统符号 + 0 项占位）。
  为验收这两项撞上「菜单栏图标全部枚举不到」的环境级退化，深读 Thaw 后按 `MenuBarAgentWindow` 重写盘点引擎：
  托管通道主用（**4 项 → 25 项，耗时 2s → 0.05s**，收起/展开两态一致），新事实 T28/T41/T44–T63 写入 §5。
  其中两条推翻了旧结论：**-25212 不是「被收纳」**（T46）、**合成右键已全线失效，触发靠 AXPress 阶梯**（T59/T60/T61，新建 trigger.py；该条本身概括过度，见下一条目更正）。
  真机取证：P41/P44/P45/P46/P47/P48/P49/P52/P53/P54 全 PASS（新增 P53 收纳项 AX 触发、P54 AXPress 并关面板）。
  **待办：屏幕录制权限未授予 bundle（像素图标路径未取证）；真实鼠标左键点控制图标需人工复核（T41）。**
- **2026-11-22（凌晨·复核）**：不放过「合成点击失效」与「Thaw 有 revealAndClick」这组矛盾，读完
  Thaw 的事件工厂与投递链路（`MenuBarItemEventSupport` / `+Clicking` / `+EventHelpers`）后写 t65/t66 复测：
  **合成点击没死，是按 App 家族分裂**（AXPress 17/25、合成右键 8/25，LaunchOS/Little Snitch 只答点击，
  被收纳 9 项坐标点击 0/9）——T59/T60 是从 4 个恰好不吃合成点击的样本上下的全称结论，已改写 §5（新增 T65/T66）。
  同时拿到三条字段工法与两条反例（假 windowID 字段与 PostToPid 都会把点击毁掉）。
  trigger.py 因此补上第三档；新增 P55 取证（LaunchOS 靠补档弹窗），P41/P44/P45/P46/P47/P48/P49/P52/P53/P54/P55 全 PASS，
  单测 51 项全绿。**Phase 3 的 ⌘拖拽风险已记到 §8（瞄准要用画出来的位置）。**
  同日再修两处：① 阶梯整体搬后台（`open_item_async`）——最坏 ~3s 全是对端等待，卡在主线程会把面板和
  热键一起冻住，新增 P56 用 AXPress 往返当探针取证（触发中 0.106s vs 空载 0.118s）；
  ② **P44 旧版是假 PASS**（只问「有没有任何外来小窗」，而选中的 OneDrive 左键只刷同步从不开窗），
  收紧为「目标 pid/layer 101 的窗口差 + 靠 T66 名单选样本」后重跑 PASS。
  至此 12 条真机用例（P41/P44/P45/P46/P47/P48/P49/P52/P53/P54/P55/P56）全 PASS。
- **2026-11-22（清晨）**：bundle 授权到手，像素图标路径补齐取证：P42/P43/P51 从「仍未取证」转 PASS。
  P42 当场抓到真缺陷——**格子里有 NSButton rounded 胶囊灰底**，直接违背「只显示图标」；顺带挖出两个
  枚举陷阱（图标被顶到上沿、小图被撑满整格）与宽图标溢出，三处一起修（panel/settings/capture.fit_box），
  并把 P42 的判据换成在**真 bug 构建上标定**过的背景占比（0.35–0.53 vs 0.87–0.96，断点 0.70）。
  新事实 T69–T75 写入 §5；本机刘海是死区（真实遮挡以 stashed 呈现），Thaw 把「挤不下/够不着」放设置页
  提示而非格子角标——Phase 4 照此办理。
  同时修掉取证脚本自身的三处假 FAIL：P56 的 1.5s 其实是 messaging 超时的固定价（带 err 才能分开
  「我们卡住」与「探针没落到元素上」，T75；对照组与灵敏度分别由 t76/t77 取证）、P49/P52 依赖上一条
  用例留下的设置窗口（P48 会关掉它）→ 改为 `ensure_settings()` 自给自足、P42 截图前先挪开指针（悬停
  tooltip 会盖住格子）。
  全量 15 条（P41/P42/P43/P44/P45/P46/P47/P48/P49/P51/P52/P53/P54/P55/P56）复跑 PASS，单测 54 项全绿。
  **下一步：Phase 4（设置窗口完整化 + 打包 + 开机自启）。**
- **2026-11-22（傍晚·Phase 4a + P42 回归）**：设置页加「挤不下 / 够不着」提示行（照 Thaw 放设置页、
  只给计数与指引、绝不列名字），P61/P62/P63 真机 PASS；顺带把取证脚本里两个只自娱的判据拆掉：
  P63 的「拿盘点名字子串查漏」会被固定文案「被系统收纳」撞上归属名叫「系统」而假阳性（改模板正则 +
  bundle id 查漏），P42 的「真实像素 16/16」只比字节不比墨量。
  回归时 P42 稳定 FAIL「空白格子 16 个」：先怀疑权限（日志报「权限=有」但裁图无墨），再用对照通道排除——
  进程内截条带全黑、`screencapture -R` 菜单栏也全黑、而全屏截图正常 → **真因是这台 Mac 当时全屏跑着
  远程 Windows 会话，菜单栏被自动隐藏**（新事实 T76）。产品缺陷是真的：那种场景下裁到的是纯背景，
  抠像后一个像素不剩，旧实现把全透明图当「截到了」交给按钮。修：`image_for_item` 无墨直接返回 None
  走兜底链（格子绝不空白），新增 `strip_has_content()`/`last_stats`，设置页多一行「菜单栏当前没画出图标」
  提示；P42 判据拆成 A（格子永远有墨，环境无关）+ B（条带有内容时非收纳项至少 2/3 裁到真像素，
  条带全黑记「环境受限」不算失败）。P64 用纯黑条带构造取证：25 格全部拿到兜底图标、提示行出现且高度涨一行。
  菜单栏恢复可见后复验：P42 PASS（裁到墨 16/16、空白 0）、P61–P64 全 PASS、全量 15 条全 PASS、单测 67 项全绿。
  **下一步：Phase 4b（SMAppService 开机自启 + py2app 正式打包 + AppIcon）。**
- **2026-11-22（晚·Phase 4d 设置页编辑本体）**：把「设置页才是编辑器」做实：区内顺序持久化
  （`config.order`）+ ⌥←/→ 改序 + ⌥↑/↓ 换区落末尾 + ⌘1/2/3 移区 + ⌘Z 撤销（栈深 50、原地不动不写盘
  不入栈）+ 底部前移/后移/撤销按钮；救援面板零改动（只跟着 plan_sections 同序）。真机
  P81–P86 全 PASS + P87 回归（t_p2b 16 条全绿、P61–P64 全绿、单测 95 项）；取证底座三条硬教训
  写入 §5（T77 自然序代替坐标排序、T78 AXIdentifier=配置键代替活文本身份、T79 主线程吞按键
  必须等效果 + PyObjC NSWorkspace 坑）；产品侧同步给格子加 `setAccessibilityIdentifier_`；
  P53 判据按 T61 修正（err 码不可信时看新窗口）；取证会话级配置保护上线（起点归位+结尾写回校验，
  用户 config.json 零残留）。**下一步：Phase 4b（SMAppService 开机自启 + py2app 打包 + AppIcon）。**
- **2026-11-22（夜·Phase 4e 设置窗口侧栏多页化）**：用户装了 thaw@beta 要求对照补齐——真机 dump
  Thaw 3.0.0-beta.7 全部 11 个设置页（T80），取舍后做五页侧栏（布局/通用/快捷键/疑难解答/关于，760 宽，
  重开归位布局页保探针判据）；布局页补每区「按名称排序」（纯函数 casefold，已有序不写盘不留撤销痕迹）
  与「重置布局」（NSAlert 确认 + 先推撤销栈再写盘，一步 ⌘Z 可回）；通用页 NSSwitch 开机自启（SMAppService
  写后回读为准，开发包 NotFound 如实 SKIP，T84）+ 超时输入框搬入；疑难解答页权限行↔App 日志对照 +
  打开日志 + 盘点摘要；关于页版本/复制/源码链。新事实 T81–T85（单下划线选择子导出、PushOnPushOff 二战、
  属性无尾下划线且 action 异常被 AppKit 吞、SMAppService 枚举、**Thaw 运行时把我们控制图标原生收纳**）。
  真机 P91–P99：8 PASS + P95 SKIP；P100 回归：t_p4 全绿（P63 因收纳 0 改判 SKIP 分支、后在收纳 9 环境
  复验 PASS；P64 阈值 15→10），t_p2b 首轮 5 连 FAIL 查出是 Thaw 互斥环境根因（T85），退 Thaw 后 15 PASS；
  P53 押单目标失效（Snapzy 当晚静默吞 AXPress，同一收纳路径在欧路词典/Qoder 上反应=有）→ 判据改「逐个
  试收纳格，任一命中即 PASS 并注明目标」后 PASS。单测 95→99 项全绿。定调复核（P99）：格子仍只显图标、
  编辑仍只在设置窗口、提示行仍在布局页。**下一步：Phase 4b（py2app 正式打包 + AppIcon，打包后回测 P95）。**
- 已知风险：
  - 打包成 .app 后辅助功能权限需对新 bundle 重新授权（T1 边界）；
  - macOS 27 小版本可能改动 MenuBarAgent AX 树（每次系统升级后重跑 `tmp/probe_ax.py`）；
  - 图标识别键 = bundleId + `key_part`（稳定 AXIdentifier/应名，同 App 双图标加 `#rank`）——换位会改序号，分区设置需能容忍（T55）；
  - AXPress 是「主点击」不是「右键」，只答右键的 App 靠阶梯第三档补一次合成右键（T66/P55）；
    将来可按 Thaw `OpenMethodIdentity`（图标身份 + App 版本）逐家记住哪种方法有效，免每次都试探。
  - PeaseBar 自身图标也会被自动收纳——F1 盘点与 F3 面板需处理「自举」（自己也在列表里，T13）。
  - 全屏 App 遮住菜单栏时根本没有图标像素可裁（T76）：现在退成兜底图标 + 设置页提示，
    但「真实像素」那一半取证在那种环境下无法验证，复跑前先确认菜单栏可见。

## 11. 测试与取证规范

- 交付 UI/交互功能前先写 `tmp/test-plan.md`（逐条用例 + 预期），真机逐条执行并截图到 `tmp/`；
- **反应类断言必须锁定「目标那一家」**：判据用点击前后的窗口差，且新窗口归属目标 pid
  或坐在菜单层（layer 101）；只问「有没有任何外来小窗」会被邻居 App 的窗口造成假 PASS
  （P44 旧版就因此假 PASS：OneDrive 左键只刷同步、从不开窗）；
- 选样本要靠图谱不靠直觉：哪些图标会开窗见 T61/T66，拿不到可开窗样本时直接断言失败（宁可 FAIL 不可假 PASS）；
- 任何「某通道整体失效」的结论必须全量跑一遍再下：T59/T60 就是 4 个样本上下的全称结论，被 T66 推翻；
- **测「主线程忙闲」要选会抵达对端执行的动作**（对自家状态项 AXPress 的往返时长）：
  读属性（AXWindows/AXChildren）在 App 被冻住时也会 0.000s 秒回，量不到延迟（T67/T68）；
  灵敏度还要先用 SIGSTOP 对照验证，否则「全部很快」什么都不能证明（假 PASS）；
  多轮采样取最好值的判据，同样要跑一遍 SIGSTOP 对照确认它会被判 FAIL（T75/t77）；
- **计时探针必须同时记录错误码**：超时与失败往往有固定价（本例 1.501s），只看时长会把
  「没落到能答话的元素上」当成「被占住」；必要时拉一个**对照组**（同一时刻另一家图标）分清是谁慢（T75）；
- 涉及图标移动的实验必须可复原：记录前/后坐标，测试后把图标拖回原位；
- **像素度量必须在真 bug 构建上标定**，不接受「人工涂色」当灵敏度对照：涂色的位置与对比度跟真缺陷
  对不上，会造出永远报 0.00 的瞎判据（本轮就连输两次）。做法：把源码改回缺陷版跑一次真机、再改回来，
  取两侧分布的空隙当阈值（T74）；
- **判据必须证明它声称的事实本身**：P42 旧版的「真实像素 16/16」只比字节是否等于兜底图，
  全透明图同样不等于兜底 → 它证明不了有墨，因此 16 格空白跑了整整一个 Phase 都没拦住（T76）。
  写判据前先问一句：这个指标在缺陷场景下会怎么变？答不上来就别拿它当证据；
- **环境级现象先用对照通道排除，再怀疑自家代码**：同一条像素链路，进程内截图全黑而 `screencapture`
  全屏截图正常 → 不是权限也不是回归，是菜单栏此刻被全屏 App 遮住（T76）。一次重启/重建就能
  让一个长期 PASS 的用例稳定 FAIL 时，先取环境现场（条带落盘、CLI 对照、菜单栏画没画）再改代码；
- **探针进程里构造的窗口不会上屏**（无事件循环），拿它 `orderFront_` 后截图只会拍到桌面/编辑器，
  属于无效证据；这类用例只比视图树里的对象状态（P43/P64 同法），不要附截图；
- **截图前先挪开指针**：悬停 tooltip 会盖在格子上，能把底色差从 0 顶到 188；
- **度量不要依赖两次盘点之间的格子↔item 对位**：菜单栏一变就整串错位（实测 26 vs 25），
  只拿格子自身与周边背景作比较；
- **用例不许依赖上一条留下的窗口状态**：需要设置窗口就自己开（`ensure_settings()`），否则批量顺序一变
  就报「设置窗口里没有格子」这种假 FAIL；同理，拿 AX 元素做计时探针必须每轮重取（T73）；
- **反应类判据不许押在单个第三方 App 的即时状态上**（P53 教训）：同一收纳触发路径，Snapzy 当晚
  err=0 静默吐掉（窗口/前置/像素三路全无反应），而欧路词典/Qoder 照常开窗——目标 App 哑了不等于
  路径坏了。做法：按图谱逐个试同类样本，任一命中真实反应即 PASS 并注明取证目标，全部静默才 FAIL；
- **取证前先检查环境有没有别家同类占用者**：菜单栏管理器（Thaw/Bartender/Ice）运行中会把 PeaseBar
  控制图标原生收纳，造成连环假 FAIL（T85）——开工先 `pgrep` 确认并退出对照 App，再核对盘点项数正常；
- 不在未授权的机器上静默降级——权限缺失时给出中文指引。
