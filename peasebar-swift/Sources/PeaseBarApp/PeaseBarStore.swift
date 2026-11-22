import Foundation
import SwiftUI
import AppKit
import PeaseBarCore

/// 一枚图标归属哪个区：显示在菜单栏，还是收纳进弹窗（隐藏）。
enum ItemSection: String, Codable {
    case shown    // 显示在菜单栏
    case hidden   // 收纳到弹窗
}

/// 我们自己的图标模型：不依赖 Thaw 的任何类型，只包一层 MenuBarReader 读到的信息，
/// 再挂上「我们想让它显示还是隐藏」的意图。
struct PeaseItem: Identifiable, Hashable {
    let id: String          // 稳定标识：bundleID + 标题
    let info: MenuBarItemInfo
    var section: ItemSection

    var ownerName: String { info.ownerApp }
    var title: String { info.title }
    static func == (lhs: PeaseItem, rhs: PeaseItem) -> Bool { lhs.id == rhs.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

/// 中心状态：读取当前菜单栏、维护每枚图标的显示/隐藏意图，并持久化到 UserDefaults。
@MainActor
final class PeaseBarStore: ObservableObject {
    @Published private(set) var items: [PeaseItem] = []
    @Published var authorizationGranted: Bool = false

    /// 意图持久化：key 是图标稳定标识，value 是分区（缺省 shown）。
    private var intents: [String: ItemSection] {
        get {
            guard let raw = UserDefaults.standard.dictionary(forKey: Self.intentKey) as? [String: String] else { return [:] }
            return raw.compactMapValues { ItemSection(rawValue: $0) }
        }
        set {
            let encoded = newValue.mapValues { $0.rawValue }
            UserDefaults.standard.set(encoded, forKey: Self.intentKey)
        }
    }

    private static let intentKey = "com.pease.peasebar.itemIntents"

    /// 重新扫描菜单栏，把读到的实时图标和已存的意图合并。
    func refresh() {
        authorizationGranted = MenuBarReader.isTrusted()
        let current = intents
        var stored = current
        var next: [PeaseItem] = []
        for info in MenuBarReader.read() {
            let id = "\(info.ownerBundleID)|\(info.title)"
            let section = stored[id] ?? .shown
            next.append(PeaseItem(id: id, info: info, section: section))
            if stored[id] == nil { stored[id] = section }   // 记住新出现的图标
        }
        intents = stored
        items = next.sorted {
            if $0.section != $1.section { return $0.section == .hidden }
            return $0.ownerName < $1.ownerName
        }
    }

    /// 把某枚图标设为目标分区。真正作用到系统菜单栏的隐藏动作由 ItemHider 负责。
    func setSection(_ section: ItemSection, for id: String) {
        var stored = intents
        stored[id] = section
        intents = stored
        if let idx = items.firstIndex(where: { $0.id == id }) {
            items[idx].section = section
        }
        ItemHider.apply(section: section, to: items.first(where: { $0.id == id }))
    }
}
