# py2app 打包配置：`python3 setup.py py2app -A`（-A 为 alias 开发模式，产物 dist/PeaseBar.app）
from setuptools import setup

setup(
    app=["main.py"],
    data_files=[],
    options={
        "py2app": {
            "argv_emulation": False,
            "includes": ["peasebar"],
            "plist": {
                "CFBundleName": "PeaseBar",
                "CFBundleDisplayName": "PeaseBar",
                "CFBundleIdentifier": "com.pease.peasebar",
                "CFBundleShortVersionString": "0.1.0",
                "CFBundleVersion": "0.1.0",
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
