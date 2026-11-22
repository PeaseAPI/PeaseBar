import SwiftUI
import AppKit
import PeaseBarCore

/// PeaseBar 自有 App 入口。这是完全我们自己写的 SwiftUI，界面仿 Thaw 的样子，
/// 但没有引用它的任何一行代码。
@main
struct PeaseBarApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var store = PeaseBarStore()

    var body: some Scene {
        // 主设置窗：仿 Thaw 的「侧边栏 + 详情」结构。
        Window("PeaseBar", id: "settings") {
            RootView()
                .environmentObject(store)
                .frame(minWidth: 820, minHeight: 560)
                .onAppear { store.refresh() }
        }
        .windowResizability(.contentMinSize)
        .defaultSize(width: 980, height: 680)
        // 菜单栏常驻图标：点开是收纳起来的图标面板。
        MenuBarExtra("PeaseBar", systemImage: "menubar.rectangle") {
            MenuContent(store: store)
        }
    }
}

/// 把 App 设为「菜单栏应用」（不占 Dock），和 Thaw 一样只在菜单栏出现。
/// 首启用 .regular 好让主窗口自动弹出，方便核对界面；稳定后再改回 .accessory。
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
    }
}

private struct MenuContent: View {
    @ObservedObject var store: PeaseBarStore
    var body: some View {
        Button("刷新菜单栏") { store.refresh() }
        Divider()
        let hidden = store.items.filter { $0.section == .hidden }
        if hidden.isEmpty {
            Text("没有收纳的图标").foregroundStyle(.secondary)
        } else {
            ForEach(hidden) { item in
                Button("↩︎ 显示 \(item.ownerName)") { store.setSection(.shown, for: item.id) }
            }
        }
        Divider()
        Button("打开设置…") {
            NSApp.setActivationPolicy(.regular)
            NSApp.activate(ignoringOtherApps: true)
            if let w = NSApp.windows.first(where: { $0.title == "PeaseBar" }) { w.makeKeyAndOrderFront(nil) }
        }
    }
}
