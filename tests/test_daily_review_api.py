from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from daily_review_app import make_handler


def _request(base: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None
    headers = {}
    method = "GET"
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_daily_review_http_draft_and_approval_flow(project_paths) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(project_paths))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    date = "2026-07-06"
    try:
        status, saved = _request(
            base,
            "/api/save-day",
            {
                "date": date,
                "topic": "设备检测流程",
                "notes": "观察了检测流程。认识到规范记录有助于质量追溯。",
                "status": "reviewed",
                "images": [],
            },
        )
        assert status == 200
        assert saved["review"]["date"] == date

        status, generated = _request(base, "/api/generate-draft", {"date": date})
        assert status == 200
        draft = generated["draft"]
        assert draft["facts"]["confirmed_facts"]
        assert any(section["requires_confirmation"] for section in draft["sections"])

        status, blocked = _request(base, "/api/approve-draft", {"date": date})
        assert status == 400
        assert "Formal approval blocked" in blocked["error"]

        draft["facts"]["pending_confirmation"] = []
        for section in draft["sections"]:
            if section["requires_confirmation"]:
                section["requires_confirmation"] = False
                section["text"] = "已根据当天记录补充并确认本段内容。"
        status, saved_draft = _request(base, "/api/save-draft", {"draft": draft})
        assert status == 200
        assert saved_draft["draft"]["status"] == "draft"

        status, approved = _request(base, "/api/approve-draft", {"date": date})
        assert status == 200
        assert approved["draft"]["status"] == "approved"

        status, loaded = _request(base, f"/api/draft?date={date}")
        assert status == 200
        assert loaded["draft"]["approved_at"]

        loaded["draft"]["status"] = "draft"
        status, rejected = _request(base, "/api/save-draft", {"draft": loaded["draft"]})
        assert status == 400
        assert "approved locked draft" in rejected["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
