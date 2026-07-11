"""
配布用アプリのエントリーポイント。

PyInstallerでパッケージ化した際、この関数が実行され、
ローカルサーバーを起動したうえで既定のブラウザでメイン画面を開く。
"""
from __future__ import annotations

import threading
import time
import webbrowser

import uvicorn

HOST = "127.0.0.1"
PORT = 8000


def _open_browser_when_ready() -> None:
    time.sleep(1.5)
    webbrowser.open(f"http://{HOST}:{PORT}/")


def main() -> None:
    import server  # noqa: F401  (資源パス解決を含め、この時点で読み込む)

    threading.Thread(target=_open_browser_when_ready, daemon=True).start()
    uvicorn.run(server.app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
