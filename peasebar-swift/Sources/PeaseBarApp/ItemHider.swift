import Foundation
import AppKit
import PeaseBarCore

/// 把「显示 / 收纳」的意图真正作用到系统菜单栏的隐藏引擎。
///
/// 现状说明（诚实）：macOS 对「逐枚菜单栏图标隐藏」没有稳定的公开 API，
/// 原生做法是走系统自带的「菜单栏布局 / 溢出」可见性机制。这一步是本项目
/// 最硬的一块，需要单独验证。当前版本先把意图记录并尝试用公开 AX 的
/// AXPress 触发原生收纳，真正逐枚隐藏引擎在下一步专攻。
enum ItemHider {
    static func apply(section: ItemSection, to item: PeaseItem?) {
        guard let item else { return }
        switch section {
        case .shown:
            reveal(item.info)
        case .hidden:
            conceal(item.info)
        }
    }

    /// 尝试触发该图标所属 App 的原生收纳（best-effort）。
    private static func conceal(_ info: MenuBarItemInfo) {
        pressMenuBarItem(info)
    }

    private static func reveal(_ info: MenuBarItemInfo) {
        // 显示方向：原生收纳是 toggle，再按一次即回到菜单栏。
        pressMenuBarItem(info)
    }

    private static func pressMenuBarItem(_ info: MenuBarItemInfo) {
        let axApp = AXUIElementCreateApplication(info.ownerPID)
        guard let extrasRef = copyAttr(axApp, "AXExtrasMenuBar") else { return }
        let bar = extrasRef as! AXUIElement
        guard let children = (copyAttr(bar, "AXChildren") as? [AXUIElement]) else { return }
        // 找到标题匹配的那枚，按原生方式触发其可见性切换。
        for el in children {
            let title = (copyAttr(el, "AXTitle") as? String) ?? (copyAttr(el, "AXDescription") as? String) ?? ""
            if title == info.title {
                _ = AXUIElementPerformAction(el, "AXPress" as CFString)
                break
            }
        }
    }

    private static func copyAttr(_ el: AXUIElement, _ name: String) -> CFTypeRef? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(el, name as CFString, &value) == .success else { return nil }
        return value
    }
}
