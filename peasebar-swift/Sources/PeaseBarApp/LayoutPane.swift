import SwiftUI
import AppKit

/// 「菜单栏布局」主面板：仿 Thaw 的分区卡片——每区一个圆角分组，里面是图标格子。
/// 两区：显示在菜单栏 / 收纳到弹窗。点图标上的菜单可在两区间移动。
struct LayoutPane: View {
    @EnvironmentObject var store: PeaseBarStore

    private var shown: [PeaseItem] { store.items.filter { $0.section == .shown } }
    private var hidden: [PeaseItem] { store.items.filter { $0.section == .hidden } }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                if !store.authorizationGranted {
                    AccessBanner()
                }
                SectionCard(title: "显示在菜单栏",
                            subtitle: "这些图标留在顶部菜单栏",
                            systemImage: "menubar.rectangle",
                            items: shown, targetSection: .shown)
                SectionCard(title: "收纳到弹窗",
                            subtitle: "这些图标从菜单栏隐藏，点菜单栏图标才出现",
                            systemImage: "square.stack.3d.up",
                            items: hidden, targetSection: .hidden)
            }
            .padding(24)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

private struct SectionCard: View {
    let title: String
    let subtitle: String
    let systemImage: String
    let items: [PeaseItem]
    let targetSection: ItemSection
    @EnvironmentObject var store: PeaseBarStore

    private var other: ItemSection { targetSection == .shown ? .hidden : .shown }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Image(systemName: systemImage).foregroundStyle(.tint)
                Text(title).font(.headline)
                Spacer()
                Text("\(items.count)").font(.callout).foregroundStyle(.secondary)
            }
            Text(subtitle).font(.subheadline).foregroundStyle(.secondary)

            if items.isEmpty {
                Text("（空）").foregroundStyle(.tertiary).frame(maxWidth: .infinity, alignment: .center).padding(.vertical, 16)
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 96), spacing: 12)], spacing: 12) {
                    ForEach(items) { item in
                        ItemTile(item: item) {
                            store.setSection(other, for: item.id)
                        }
                        .contextMenu {
                            Button(other == .hidden ? "收纳到弹窗" : "显示在菜单栏") {
                                store.setSection(other, for: item.id)
                            }
                        }
                    }
                }
            }
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(Color(nsColor: .controlBackgroundColor))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(Color(nsColor: .separatorColor), lineWidth: 1)
        )
    }
}

private struct ItemTile: View {
    let item: PeaseItem
    let onMove: () -> Void
    @State private var hovering = false

    var body: some View {
        VStack(spacing: 6) {
            AppIconView(bundleID: item.info.ownerBundleID)
                .frame(width: 40, height: 40)
            Text(item.ownerName)
                .font(.caption)
                .lineLimit(1)
                .foregroundStyle(.primary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 10)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(hovering ? Color.accentColor.opacity(0.15) : Color.clear)
        )
        .overlay(alignment: .topTrailing) {
            Button(action: onMove) {
                Image(systemName: "arrow.left.arrow.right.circle.fill")
                    .foregroundStyle(.tint)
            }
            .buttonStyle(.plain)
            .padding(4)
            .opacity(hovering ? 1 : 0)
        }
        .onHover { hovering = $0 }
        .help("\(item.ownerName) · \(item.title)")
    }
}

/// 按 bundle id 取应用图标；取不到就用通用占位。
private struct AppIconView: View {
    let bundleID: String
    var body: some View {
        Group {
            if let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleID) {
                Image(nsImage: NSWorkspace.shared.icon(forFile: url.path))
                    .resizable()
            } else {
                Image(systemName: "app.dashed")
                    .resizable()
                    .foregroundStyle(.secondary)
            }
        }
        .aspectRatio(contentMode: .fit)
    }
}

private struct AccessBanner: View {
    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "lock.trianglebadge.exclamationmark").foregroundStyle(.orange)
            VStack(alignment: .leading, spacing: 2) {
                Text("还没有辅助功能权限").font(.headline)
                Text("到「系统设置 → 隐私与安全性 → 辅助功能」里允许 PeaseBar，才能读取菜单栏。")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Button("打开辅助功能设置") {
                if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
                    NSWorkspace.shared.open(url)
                }
            }
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color.orange.opacity(0.12)))
    }
}
