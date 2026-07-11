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
import tempfile
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from audio_source import MicSource, WavFileSource, list_input_devices
from doc_extract import extract_name_candidates
from recognizer import VoskEngine, ensure_period

APP_DIR = Path(__file__).parent.parent / "app"
MODEL_DIR = Path(__file__).parent.parent / "poc" / "vosk-check" / "vosk-model-small-ja-0.22"

app = FastAPI()

engine = VoskEngine(MODEL_DIR)
event_queue: "queue.Queue[dict]" = queue.Queue()

_state = {
    "recording": False,
    "source": None,       # MicSource | WavFileSource
    "thread": None,        # threading.Thread
    "final_seq": 0,        # 確定行の連番。修正メッセージがどの行を指すか特定するために使う
    "display_settings": {
        "fontSize": "3.1vw",
        "fontFamily": "'BIZ UDPGothic', 'Noto Sans JP', sans-serif",
    },
}

_clients: set[WebSocket] = set()


def _run_recognition(source) -> None:
    def on_partial(text: str) -> None:
        event_queue.put({"type": "partial", "text": text})

    def on_final(text: str) -> None:
        _state["final_seq"] += 1
        event_queue.put({"type": "final", "seq": _state["final_seq"], "text": text})

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


@app.get("/api/names")
def get_names():
    """現在の表示許可リストを返す"""
    return {"terms": engine.registered_terms}


@app.post("/api/names")
def set_names(payload: dict):
    """表示許可リストを更新する。
    payload.terms は [{"name": "...", "reading": "..."}, ...] の形式。
    mode="add"（既定）なら既存リストに追加（同名は上書き）、
    mode="replace" なら全体を置き換える。
    """
    terms = payload.get("terms", [])
    mode = payload.get("mode", "add")

    if mode == "replace":
        merged = {t["name"]: t for t in terms}
    else:
        merged = {t["name"]: t for t in engine.registered_terms}
        for t in terms:
            merged[t["name"]] = t

    engine.set_registered_terms(list(merged.values()))
    return {"ok": True, "count": len(merged)}


@app.delete("/api/names/{name}")
def delete_name(name: str):
    """表示許可リストから1件削除する"""
    remaining = [t for t in engine.registered_terms if t["name"] != name]
    engine.set_registered_terms(remaining)
    return {"ok": True, "count": len(remaining)}


@app.put("/api/names/{name}")
def update_name(name: str, payload: dict):
    """表示許可リストの1件を修正する（氏名・読みの変更）"""
    new_name = payload.get("name", "").strip()
    new_reading = payload.get("reading", "").strip()
    if not new_name:
        return {"ok": False, "error": "氏名を入力してください"}

    remaining = [t for t in engine.registered_terms if t["name"] != name]
    remaining = [t for t in remaining if t["name"] != new_name]
    remaining.append({"name": new_name, "reading": new_reading})
    engine.set_registered_terms(remaining)
    return {"ok": True, "count": len(remaining)}


@app.post("/api/extract-names")
async def extract_names(file: UploadFile = File(...)):
    """事前学習資料（PDF/DOCX/PPTX）から氏名候補を抽出する。
    テキスト層があるページ／スライドのみ対象（OCRは対象外）。
    """
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".pdf", ".docx", ".pptx"):
        return {"ok": False, "error": f"未対応のファイル形式です: {suffix}"}

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(await file.read())
        tmp.flush()
        try:
            result = extract_name_candidates(tmp.name, file.filename)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return {"ok": True, **result}


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
    # final_seq はここでリセットしない。停止→再開しただけで文字が消えては
    # いけないため、続きの連番のまま画面の表示を維持する。
    # 画面を空にしたい場合は運用者が明示的に「クリア」ボタンを押す。
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
    # 新規接続時に、現在の表示設定（文字サイズ・フォント）を即座に送っておく。
    # display.html をあとから開き直した場合も、直前の設定が復元されるように。
    await websocket.send_json({"type": "settings", **_state["display_settings"]})
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "correction":
                # 運用者がライブ文字起こしの確定行を修正した通知。
                # 同じキューに乗せて全クライアント（本人含む）へ配信し、
                # HDMI表示画面にも即座に反映させる
                event_queue.put({
                    "type": "correction",
                    "seq": msg.get("seq"),
                    "text": msg.get("text", ""),
                })
            elif msg.get("type") == "settings":
                # 運用者がスクリーン表示の文字サイズ・フォントを変更した通知
                if "fontSize" in msg:
                    _state["display_settings"]["fontSize"] = msg["fontSize"]
                if "fontFamily" in msg:
                    _state["display_settings"]["fontFamily"] = msg["fontFamily"]
                event_queue.put({"type": "settings", **_state["display_settings"]})
            elif msg.get("type") == "manual":
                # 運用者がPCから直接入力したテキスト（休憩案内など）。
                # 音声認識の確定行と同じ扱いにして、通常の行として画面に流す
                text = msg.get("text", "").strip()
                if text:
                    _state["final_seq"] += 1
                    event_queue.put({"type": "final", "seq": _state["final_seq"], "text": ensure_period(text)})
            elif msg.get("type") == "split":
                # 文の途中で改行されてしまった行を、カーソル位置で分割した際の
                # 「カーソルより後ろ」のテキスト。分割で生まれただけなので句点は
                # 付けず、元の行のすぐ次に表示されるよう insertAfterSeq を渡す
                text = msg.get("text", "").strip()
                after_seq = msg.get("afterSeq")
                if text:
                    _state["final_seq"] += 1
                    event_queue.put({
                        "type": "final",
                        "seq": _state["final_seq"],
                        "text": text,
                        "insertAfterSeq": after_seq,
                    })
            elif msg.get("type") == "merge":
                # Shift+Enterで分割したテキストを、次の行の先頭に合流させた通知。
                # 「correction」とは違い、合流後の文章をそのまま新しい基準にするため
                # 赤字の差分表示は出さない
                event_queue.put({
                    "type": "merge",
                    "seq": msg.get("seq"),
                    "text": msg.get("text", ""),
                })
            elif msg.get("type") == "clear":
                # 休憩に入る際などに、運用者が画面表示を手動でクリアする
                _state["final_seq"] = 0
                event_queue.put({"type": "clear"})
    except WebSocketDisconnect:
        _clients.discard(websocket)


@app.get("/")
def index():
    return FileResponse(APP_DIR / "main.html")


@app.get("/display")
def display():
    return FileResponse(APP_DIR / "display.html")


app.mount("/fonts", StaticFiles(directory=APP_DIR / "fonts"), name="fonts")
app.mount("/app", StaticFiles(directory=APP_DIR), name="app")
