# py2app 打包配置：`python3 setup.py py2app -A`（-A 为 alias 开发模式，产物 dist/PeaseBar.app）
import re

from setuptools import setup

# 版本号唯一源：peasebar/__init__.py 的 __version__，这里只读不再写第二份
_VERSION = re.search(r'__version__ = "([^"]+)"',
                     open("peasebar/__init__.py", encoding="utf-8").read()).group(1)

setup(
    app=["main.py"],
    data_files=[],
    options={
        "py2app": {
            "argv_emulation": False,
            # 正式包（不带 -A）要真捆依赖：numpy 是动态导入，显式 include 防漏
            "includes": ["peasebar", "numpy"],
            # 排除 tkinter：py2app 默认会把它连同 Tcl/Tk.framework 捆进来，
            # 而框架里的 libtclstub.a/libtkstub.a 无代码签名，会让 ad-hoc 签名
            # 报「code object is not signed at all」而整体失败。PeaseBar 只用 AppKit，
            # 用不到 tkinter，直接排掉最干净。
            "excludes": ["tkinter", "_tkinter", "unittest", "pydoc_data"],
            "iconfile": "assets/AppIcon.icns",
            "plist": {
                "CFBundleName": "PeaseBar",
                "CFBundleDisplayName": "PeaseBar",
                "CFBundleIdentifier": "com.pease.peasebar",
                "CFBundleShortVersionString": _VERSION,
                "CFBundleVersion": _VERSION,
                # Finder/登录项列表里的 App 图标（LSUIElement 不上 Dock，但系统列表要用）
                "CFBundleIconFile": "AppIcon",
                # 菜单栏应用：不出现 Dock 图标
                "LSUIElement": True,
                "NSHighResolutionCapable": True,
                "CFBundleDevelopmentRegion": "zh_CN",
                "LSMinimumSystemVersion": "26.0",
                "NSHumanReadableCopyright": "© 2026 Pease",
            },
        }
    },
    setup_requires=["py2app"],
)
