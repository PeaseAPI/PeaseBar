import Foundation
import AppKit
import ApplicationServices

/// 一枚菜单栏状态项的读取结果（自有数据结构，不依赖任何第三方代码）。
public struct MenuBarItemInfo: CustomStringConvertible {
    public let ownerApp: String
    public let ownerBundleID: String
    public let ownerPID: pid_t
    public let title: String
    public let frame: CGRect?

    public var description: String {
        let pos = frame.map { "(\(Int($0.origin.x)),\(Int($0.origin.y)) \(Int($0.width))x\(Int($0.height)))" } ?? "无坐标"
        return "[\(ownerApp)/\(ownerBundleID)] \(title)  \(pos)"
    }
}

/// 用公开 AX API 读取整个菜单栏：逐个进程取其 "AXExtrasMenuBar" 的子项。
/// 第三方状态项归属各自 App 进程，系统模块归属 com.apple.MenuBarAgent，
/// 所以要对每个运行中的 App 都取一次，再汇总。全程只用 ApplicationServices 公开接口。
public enum MenuBarReader {

    public static func isTrusted() -> Bool { AXIsProcessTrusted() }

    private static func attr(_ el: AXUIElement, _ name: String) -> CFTypeRef? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(el, name as CFString, &value) == .success else { return nil }
        return value
    }

    private static func children(of el: AXUIElement) -> [AXUIElement] {
        (attr(el, "AXChildren") as? [AXUIElement]) ?? []
    }

    private static func frame(of el: AXUIElement) -> CGRect? {
        guard let posV = attr(el, "AXPosition"), let sizeV = attr(el, "AXSize") else { return nil }
        var point = CGPoint.zero
        var size = CGSize.zero
        guard AXValueGetValue(posV as! AXValue, .cgPoint, &point),
              AXValueGetValue(sizeV as! AXValue, .cgSize, &size) else { return nil }
        return CGRect(origin: point, size: size)
    }

    private static func title(of el: AXUIElement) -> String {
        (attr(el, "AXTitle") as? String).flatMap { $0.isEmpty ? nil : $0 }
            ?? (attr(el, "AXDescription") as? String) ?? "?"
    }

    /// 汇总所有 App 的菜单栏项。
    public static func read() -> [MenuBarItemInfo] {
        var result: [MenuBarItemInfo] = []
        let apps = NSWorkspace.shared.runningApplications.filter { $0.isActive || true }
        for app in apps {
            let pid = app.processIdentifier
            let axApp = AXUIElementCreateApplication(pid)
            guard let extras = attr(axApp, "AXExtrasMenuBar") else { continue }
            let bar = extras as! AXUIElement
            for item in children(of: bar) {
                result.append(MenuBarItemInfo(
                    ownerApp: app.localizedName ?? "?",
                    ownerBundleID: app.bundleIdentifier ?? "?",
                    ownerPID: pid,
                    title: title(of: item),
                    frame: frame(of: item)
                ))
            }
        }
        return result
    }
}
