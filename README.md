# PeaseBar

macOS 菜单栏图标管理器：图标被刘海遮挡、被系统收纳、或被刻意隐藏时，
都能从菜单栏按钮弹出的**救援面板**一键找回并触发。业务逻辑参照
[Thaw](https://github.com/thaw-app/Thaw)，以 Python + PyObjC 全新实现，中文优先。

## 它能做什么

- **找回图标**：点菜单栏的 PeaseBar 图标（或按 `⌥⌘B`）弹出救援面板，
  这里只列「看不见」的图标：被你设为弹窗显示的 + 被系统收进溢出区、被刘海挡住的
  （照 Thaw：此刻画在菜单栏上的不重复出现；永久隐藏的不展示）。
  面板就是一张居中的纯图标网格，秒开；需要展开系统收纳区时在控制图标右键菜单里操作。
- **一键触发**：点面板里的图标 = 点真图标（弹它的原生菜单或窗口），
  不需要把图标拖回来。
- **三区管理**：菜单栏显示 / 弹窗显示 / 永久隐藏——前两种都可编辑先后顺序，
  把不常用的图标挪出画面，常用图标腾出位置。
- **同步真实菜单栏**（布局页选项，默认开）：把图标移进「弹窗显示/永久隐藏」会真的把它从
  系统菜单栏收起、移回「菜单栏显示」会真的放出来；「菜单栏显示」区内改序也会同步回真实菜单栏。
  实现走 macOS 原生的按住 ⌘ 拖拽状态项；仅对第三方图标生效，苹果系统图标（时间/电池/Control
  Center 等）受系统限制无法程序拖动，会自动跳过（可关掉此开关回到纯逻辑编辑）。
- **顺序编辑**：在设置窗口的布局页调整顺序与分区——**按住图标直接拖**（条内拖动
  改顺序，拖到另一个区就换区），或用键盘（`⌥←/→` 移序、`⌥↑/↓` 换区、`⌘1/2/3`
  快速移区、`⌘Z` 撤销），也可「按名称排序」「重置布局」。
- **开机自启**：设置 → 通用 → 「登录时启动」（走系统 SMAppService，状态以系统回读为准）。
- **触发图标可定义**：菜单栏上的 PeaseBar 图标（默认圆圈三点 ⋯）可在
  设置 → 通用 → 「菜单栏控制图标」换预设，点击后图标列表向下展开。

界面只显示纯图标：不显示名字（鼠标悬停可看），也不带消息数字、流量数值——
PeaseBar 只负责编排图标，不替你重画它们。把条目移回菜单栏后，它保持原本样子
（流量、温度这些数值在菜单栏上照常显示）。

布局页的格子用菜单栏真实像素，**显示一半的图标（网速、温度这类两行文字）会
按同样比例完整缩着显示**，不再裁掉下半行；菜单栏高度按屏幕实测（刘海屏 39pt
与老屏 24pt 都算得对）。

## 设置窗口（`⌥⌘S` 或右键 PeaseBar 图标 → 设置…）

1:1 对标 Thaw 的 12 页设置窗（侧栏分三组：主页签 / MODULES / MANAGE）：

| 页 | 内容 |
|----|------|
| 通用 | 登录时启动、精简模式、Dock 图标、语言、主题（System/Light/Dark/Black）、显示设置描述、菜单栏控制图标、收起 App 菜单、右键菜单栏 |
| 布局 | 三区横向图标条（真实图标像素、宽度随图伸缩）、拖拽/选中/移动/撤销、排序与重置、选项开关（真实像素优先、图标条换行、同步真实菜单栏）、收纳与遮挡提示 |
| Visibility | 显示隐藏项方式（点击/悬停/滚动）、再次隐藏策略、保持打开秒数、Zen Mode、交换、搜索、On hover |
| 外观 | 形状（无/全幅/分隔/刘海）、菜单栏样式、圆角、Screen corners、浅色/深色分别设置 |
| PeaseBar 工具栏 | 预览 + 子页签（显示/Look/All Displays）、应用到哪台显示器、行为开关 |
| 显示器 | 显示器卡片与识别、子页签（Spacing/Template/Spaces/Wide Displays）、菜单栏项目间距、按显示器间距、重置间距 |
| Shortcuts | 子页签（Visibility/菜单栏项目/布局/工具栏）+ 各项快捷键一览与录制 |
| 配置管理 | 已保存布局列表、新建名称、保存/应用/删除/导入当前配置 |
| Modules | 可选模块开关（配置管理 / Scripts / Triggers / Widgets） |
| Privacy | 权限状态（辅助功能 / Menu Bar Layout Access / 屏幕录制 / Notifications）、允许 App 改设置、可看到项、网络访问 |
| 疑难解答 | 子页签（诊断/Repair/重置）、详细日志、导出日志、重新抓取图标 |
| 关于 | 版本信息（一键复制）、更新频道、自动更新、检查更新、What's New、源码链接、版权 |

> 说明：暂无真实后端的 Thaw 功能（Zen Mode 生效、收纳条、间距重启应用、录制全局快捷键、网络自动更新）
> 以「持久化偏好 + 诚实占位」呈现，不会假装成功；有后端的项即时生效。

## 权限

macOS 会按 App 记账，首次运行需要授予：

- **辅助功能**（必需）：读取与触发菜单栏图标。设置 → 隐私与安全性 →
  「设备控制和数据访问」中放行 PeaseBar；未放行时应用内会有指引。
- **录屏与系统录音**（可选）：抓取图标的真实像素。没有此权限不丢核心功能——
  格子会退用 App 图标/系统符号，绝不会空白。设置 → 疑难解答 → 「请求屏幕录制权限」。

权限授予/重装 App 后建议重启 PeaseBar 一次。

## 安装与运行

正式包（macOS 26/27，Apple Silicon）：

```bash
python3 setup.py py2app          # 产物 dist/PeaseBar.app
rm dist/PeaseBar.app/Contents/Resources/lib/python3.*/config   # 删构建尾产物里的悬空软链（否则验签不过）
codesign --force --deep -s - dist/PeaseBar.app                 # 手动 ad-hoc 签名（签名定稿后不要再重签）
ditto dist/PeaseBar.app /Applications/PeaseBar.app
open /Applications/PeaseBar.app
```

开发态（改动即时生效）：

```bash
python3 -m pip install --user pyobjc-framework-Cocoa pyobjc-framework-Quartz pyobjc-framework-ApplicationServices
python3 setup.py py2app -A && ditto dist/PeaseBar.app /Applications/PeaseBar.app
open /Applications/PeaseBar.app   # 请勿终端直启二进制（系统不给上菜单栏）
```

## 已知边界

- 全屏应用遮住菜单栏期间，格子会暂时退用兜底图标，退出全屏后在设置 → 疑难解答
  点「重新抓取图标」（或重启）恢复真实像素；
- 个别 App 的图标对程序化触发不响应（第三方自身行为），面板会逐级尝试常见方式；
- 图标顺序/隐藏的「写回真实菜单栏」只对**第三方图标**生效（按住 ⌘ 原生拖拽）；苹果系统图标受 macOS
  限制无法程序拖动，对它们 PeaseBar 管理的仍是面板/设置里的逻辑序（布局页可关闭「同步真实菜单栏」）。

## 更多

- 功能说明 / 技术事实 / 路线图 / 进度：见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
- 纯逻辑单测：`python3 -m unittest discover -s tests -t .`
- 日志：`~/Library/Logs/PeaseBar.log`
