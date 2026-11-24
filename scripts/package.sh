#!/bin/zsh
# PeaseBar 正式打包 + 稳定证书签名 + 安装到 /Applications，一条命令。
#
# 为什么打完包还要重签：py2app 出包是 ad-hoc 签名，每次重建 cdhash 都变，
# 系统把辅助功能授权绑在 cdhash 上——重装一次授权掉一次（盘点恒 0 项）。
# 用本机 Apple Development 证书（身份稳定）重签后，cdhash 随证书身份走，
# 重装不再掉授权。换证书时改 SIGN_ID。
set -e
cd "$(dirname "$0")/.."
PY=/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14
SIGN_ID="26A93F35CC735BAC8B1B108803A47A972F988B5E"

# 1) py2app 正式包（非 -A；tkinter 已在 setup.py excludes 排除，否则签名必炸）
"$PY" setup.py py2app

# 2) 稳定证书重签 + 验证
codesign --force --deep --sign "$SIGN_ID" dist/PeaseBar.app
codesign --verify --deep --strict dist/PeaseBar.app
echo "签名验证 OK（TeamIdentifier=$(codesign -dv dist/PeaseBar.app 2>&1 | awk -F= '/^TeamIdentifier/{print $2}')）"

# 3) 安装：先停旧实例，避免新旧两份同时占菜单栏
pkill -9 -f "MacOS/PeaseBar" 2>/dev/null || true
sleep 1
rm -rf /Applications/PeaseBar.app
cp -R dist/PeaseBar.app /Applications/
open /Applications/PeaseBar.app
echo "已安装并启动 /Applications/PeaseBar.app；首次运行请在系统弹框里点「允许」。"
