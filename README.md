# PeaseBar

macOS 菜单栏图标管理器：图标被刘海遮挡、被系统收纳、或被刻意隐藏时，
都能从菜单栏按钮弹出的**救援面板**一键找回并触发。业务逻辑参照
[Thaw](https://github.com/thaw-app/Thaw)，以 Python + PyObjC 全新实现，中文优先。

- 功能说明 / 技术事实 / 路线图 / 进度：见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
- 运行（开发态）：`python3 -m peasebar`
- 依赖：`python3 -m pip install --user pyobjc-framework-Cocoa pyobjc-framework-Quartz pyobjc-framework-ApplicationServices`
