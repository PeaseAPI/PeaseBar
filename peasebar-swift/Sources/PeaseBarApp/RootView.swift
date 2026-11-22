import SwiftUI
import AppKit

/// 侧边栏可进入的面板（先做核心的一块「菜单栏布局」，其余占位，逐步补）。
enum Pane: String, CaseIterable, Identifiable {
    case layout = "菜单栏布局"
    case general = "通用"
    case about = "关于"
    var id: String { rawValue }
    var icon: String {
        switch self {
        case .layout: return "menubar.dock.rectangle"
        case .general: return "gearshape"
        case .about: return "info.circle"
        }
    }
}

/// 仿 Thaw：左侧来源列表侧边栏 + 右侧详情。
struct RootView: View {
    @EnvironmentObject var store: PeaseBarStore
    @State private var selection: Pane? = .layout

    var body: some View {
        NavigationSplitView {
            List(Pane.allCases, selection: $selection) { pane in
                NavigationLink(value: pane) {
                    Label(pane.rawValue, systemImage: pane.icon)
                }
            }
            .navigationSplitViewColumnWidth(min: 190, ideal: 220, max: 250)
        } detail: {
            Group {
                switch selection ?? .layout {
                case .layout: LayoutPane()
                case .general: PlaceholderPane(title: "通用")
                case .about: PlaceholderPane(title: "关于")
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        store.refresh()
                    } label: {
                        Label("刷新", systemImage: "arrow.clockwise")
                    }
                }
            }
            .navigationTitle(selection?.rawValue ?? "PeaseBar")
        }
    }
}

private struct PlaceholderPane: View {
    let title: String
    var body: some View {
        ContentUnavailableView(title, systemImage: "hammer", description: Text("这块会逐步补上"))
            .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
