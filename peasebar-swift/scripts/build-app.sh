#!/bin/bash
# 把 peasebar-swift 编译产物打包成一个能直接运行的 PeaseBar.app（纯我们自己的代码）。
# 产物与之前的「改名版 Thaw」用不同 bundle id（com.pease.peasebar.own），互不干扰。
set -euo pipefail

cd "$(dirname "$0")/.."

BUNDLE_ID="com.pease.peasebar.own"
APP="build/PeaseBar.app"

echo "==> 编译 PeaseBarApp"
swift build --product PeaseBarApp

BIN="$(swift build --show-bin-path)/PeaseBarApp"

echo "==> 组装 $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp "$BIN" "$APP/Contents/MacOS/PeaseBar"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>PeaseBar</string>
    <key>CFBundleDisplayName</key><string>PeaseBar</string>
    <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
    <key>CFBundleExecutable</key><string>PeaseBar</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>0.1</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>LSMinimumSystemVersion</key><string>14.0</string>
    <key>LSUIElement</key><false/>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

echo "==> ad-hoc 签名"
codesign --force --deep --sign - "$APP" 2>/dev/null || echo "  (签名跳过)"

echo "==> 安装到 /Applications/PeaseBar-own.app"
rm -rf "/Applications/PeaseBar-own.app"
cp -R "$APP" "/Applications/PeaseBar-own.app"

echo "完成。运行：open /Applications/PeaseBar-own.app"
