from __future__ import annotations

import json
import threading
import urllib.request
import webbrowser

from daily_review_app import serve
from src.paths import get_paths


URL = "http://127.0.0.1:8765/"


def service_is_running() -> bool:
    try:
        with urllib.request.urlopen(URL + "api/health", timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and payload.get("ok") is True
    except Exception:
        return False


def main() -> None:
    if service_is_running():
        print("审核服务已经运行，正在打开浏览器。")
        webbrowser.open(URL)
        return
    print("正在启动每日图片与文字审核服务……")
    print("请保持此窗口开启；关闭窗口会停止本地服务。")
    threading.Timer(0.8, lambda: webbrowser.open(URL)).start()
    serve(get_paths(), "127.0.0.1", 8765)


if __name__ == "__main__":
    main()

