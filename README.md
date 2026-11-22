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
- **顺序编辑**：在设置窗口的布局页调整顺序与分区（`⌥←/→` 移序、`⌥↑/↓` 换区、
  `⌘1/2/3` 快速移区、`⌘Z` 撤销），也可「按名称排序」「重置布局」。
- **开机自启**：设置 → 通用 → 「登录时启动」（走系统 SMAppService，状态以系统回读为准）。
- **触发图标可定义**：菜单栏上的 PeaseBar 图标（默认圆圈三点 ⋯）可在
  设置 → 通用 → 「菜单栏控制图标」换预设，点击后图标列表向下展开。

界面只显示纯图标：不显示名字（鼠标悬停可看），也不带消息数字、流量数值——
PeaseBar 只负责编排图标，不替你重画它们。把条目移回菜单栏后，它保持原本样子
（流量、温度这些数值在菜单栏上照常显示）。

## 设置窗口（`⌥⌘S` 或右键 PeaseBar 图标 → 设置…）

| 页 | 内容 |
|----|------|
| 布局 | 三区网格、选中/移动/撤销、排序与重置、收纳与遮挡提示 |
| 通用 | 登录时启动、面板自动收回秒数、菜单栏控制图标预设 |
| 快捷键 | 当前生效的全局快捷键一览 |
| 疑难解答 | 权限状态对照、重新抓取图标、打开日志 |
| 关于 | 版本信息（一键复制）、源码链接 |

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
- 图标顺序的「写回系统菜单栏」受 macOS 限制，PeaseBar 管理的是面板/设置里的逻辑序。

## 更多

- 功能说明 / 技术事实 / 路线图 / 进度：见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
- 纯逻辑单测：`python3 -m unittest discover -s tests -t .`
- 日志：`~/Library/Logs/PeaseBar.log`
