// swift-tools-version:5.9
import PackageDescription

// PeaseBar 自有重写：完全我们自己的 Swift 代码，用公开 AX API 读菜单栏、
// 用 macOS 原生「菜单栏布局/溢出」机制做逐图标隐藏。不依赖任何私有框架，
// 也绝不引用 Thaw 的任何包/源码——只照它的好看界面自己写一套 SwiftUI。
let package = Package(
    name: "PeaseBar",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "PeaseBarCore"),
        .executableTarget(name: "pbprobe", dependencies: ["PeaseBarCore"]),
        .executableTarget(name: "PeaseBarApp", dependencies: ["PeaseBarCore"]),
    ]
)
