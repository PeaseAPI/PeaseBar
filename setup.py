# py2app 打包配置：`python3 setup.py py2app -A`（-A 为 alias 开发模式，产物 dist/PeaseBar.app）
from setuptools import setup

setup(
    app=["main.py"],
    data_files=[],
    options={
        "py2app": {
            "argv_emulation": False,
            # 正式包（不带 -A）要真捆依赖：numpy 是动态导入，显式 include 防漏
            "includes": ["peasebar", "numpy"],
            "iconfile": "assets/AppIcon.icns",
            "plist": {
                "CFBundleName": "PeaseBar",
                "CFBundleDisplayName": "PeaseBar",
                "CFBundleIdentifier": "com.pease.peasebar",
                "CFBundleShortVersionString": "0.1.0",
                "CFBundleVersion": "0.1.0",
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
