"""
VoiceSync 本体アプリのバックエンド（フェーズ2: 基盤実装）

構成:
  マイク入力 -> Vosk（recognizer.py） -> キュー -> WebSocketで全クライアントへ配信
  クライアントは2種類:
    - app/main.html   : 運用者が操作するメイン画面
    - app/display.html: HDMI外部モニタに映す表示専用画面

起動:
  uvicorn server:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import json
import queue
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from audio_source import MicSource, WavFileSource, list_input_devices
from recognizer import VoskEngine

APP_DIR = Path(__file__).parent.parent / "app"
MODEL_DIR = Path(__file__).parent.parent / "poc" / "vosk-check" / "vosk-model-small-ja-0.22"

app = FastAPI()

engine = VoskEngine(MODEL_DIR)
event_queue: "queue.Queue[dict]" = queue.Queue()

_state = {
    "recording": False,
    "source": None,       # MicSource | WavFileSource
    "thread": None,        # threading.Thread
}

_clients: set[WebSocket] = set()


def _run_recognition(source) -> None:
    def on_partial(text: str) -> None:
        event_queue.put({"type": "partial", "text": text})

    def on_final(text: str) -> None:
        event_queue.put({"type": "final", "text": text})

    try:
        engine.run(source, on_partial, on_final)
    finally:
        # WAVファイルの再生終了時など、/api/stopを経由せず認識が終わった場合も
        # recording状態をリセットしておく（次の/api/startを受け付けられるように）
        _state["recording"] = False
        event_queue.put({"type": "stopped"})


@app.on_event("startup")
async def broadcast_loop() -> None:
    async def _loop():
        loop = asyncio.get_event_loop()
        while True:
            event = await loop.run_in_executor(None, event_queue.get)
            dead = []
            for ws in list(_clients):
                try:
                    await ws.send_json(event)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                _clients.discard(ws)

    asyncio.create_task(_loop())


@app.get("/api/devices")
def get_devices():
    try:
        return {"devices": list_input_devices()}
    except Exception as e:
        return {"devices": [], "error": str(e)}


@app.post("/api/names")
def set_names(payload: dict):
    """表示許可リストを更新する（画面側の名前登録UIから呼ばれる想定）"""
    terms = payload.get("terms", [])
    engine.set_registered_terms(terms)
    return {"ok": True, "count": len(terms)}


@app.post("/api/start")
def start_recording(payload: Optional[dict] = None):
    if _state["recording"]:
        return {"ok": False, "error": "already recording"}

    payload = payload or {}
    wav_path = payload.get("wav_path")  # テスト用: マイクの代わりにWAVを流す
    device_index = payload.get("device_index")

    source = WavFileSource(wav_path) if wav_path else MicSource(device_index=device_index)
    if hasattr(source, "start"):
        source.start()

    _state["source"] = source
    _state["recording"] = True
    thread = threading.Thread(target=_run_recognition, args=(source,), daemon=True)
    _state["thread"] = thread
    thread.start()
    return {"ok": True}


@app.post("/api/stop")
def stop_recording():
    if not _state["recording"]:
        return {"ok": False, "error": "not recording"}
    source = _state["source"]
    if hasattr(source, "stop"):
        source.stop()
    _state["recording"] = False
    return {"ok": True}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    _clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()  # クライアントからは何も送らない想定。切断検知用
    except WebSocketDisconnect:
        _clients.discard(websocket)


@app.get("/")
def index():
    return FileResponse(APP_DIR / "main.html")


@app.get("/display")
def display():
    return FileResponse(APP_DIR / "display.html")


app.mount("/app", StaticFiles(directory=APP_DIR), name="app")
