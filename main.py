# 打包入口：py2app 以本文件为 PeaseBar.app 的启动脚本（开发态 `python3 -m peasebar` 也走同一逻辑）
from peasebar.app import main

if __name__ == "__main__":
    main()
