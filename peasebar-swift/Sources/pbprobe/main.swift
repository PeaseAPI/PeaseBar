import Foundation
import PeaseBarCore

// 里程碑 1 验证：我们自己的代码能不能读到顶部菜单栏。
print("辅助功能已授权：\(MenuBarReader.isTrusted())")
let items = MenuBarReader.read()
print("读到菜单栏项：\(items.count) 个")
for it in items {
    print("  \(it)")
}
