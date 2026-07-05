"""
音声入力ソース。

- MicSource: 実機のマイクからリアルタイムにキャプチャする本番用（sounddevice使用）
- WavFileSource: マイクの代わりにWAVファイルを読み込むテスト用
  （このリポジトリの開発環境にはマイクが無いため、動作確認は
  poc/vosk-check で使った sample.wav 等を使って行う）
"""
from __future__ import annotations

import queue
import wave
from pathlib import Path
from typing import Iterator

from recognizer import SAMPLE_RATE

CHUNK_FRAMES = 4000  # 0.25秒相当 (16kHz)


def list_input_devices() -> list[dict]:
    """接続されているマイクデバイスの一覧を返す（メイン画面のデバイス選択用）"""
    import sounddevice as sd

    devices = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev.get("max_input_channels", 0) > 0:
            devices.append({"index": idx, "name": dev["name"]})
    return devices


class MicSource:
    """実機マイクからのストリーミング入力（本番用）"""

    def __init__(self, device_index: int | None = None, sample_rate: int = SAMPLE_RATE):
        import sounddevice as sd

        self._sd = sd
        self.device_index = device_index
        self.sample_rate = sample_rate
        self._queue: queue.Queue[bytes] = queue.Queue()
        self._stream = None
        self._stopped = False

    def _callback(self, indata, frames, time_info, status):
        self._queue.put(bytes(indata))

    def start(self) -> None:
        self._stream = self._sd.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=CHUNK_FRAMES,
            device=self.device_index,
            dtype="int16",
            channels=1,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        self._stopped = True
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
        self._queue.put(b"")  # イテレータを止めるための番兵

    def __iter__(self) -> Iterator[bytes]:
        while True:
            chunk = self._queue.get()
            if self._stopped and chunk == b"":
                return
            yield chunk


class WavFileSource:
    """WAVファイルをマイク入力の代わりに流し込むテスト用ソース。

    実機マイクが無い開発環境で、認識〜WebSocket配信までの
    パイプライン全体を検証するために使う。
    """

    def __init__(self, wav_path: str | Path):
        self.wav_path = str(wav_path)

    def __iter__(self) -> Iterator[bytes]:
        wf = wave.open(self.wav_path, "rb")
        assert wf.getframerate() == SAMPLE_RATE, "WAVは16kHzである必要があります"
        assert wf.getnchannels() == 1 and wf.getsampwidth() == 2, "WAVはmono/16bitである必要があります"
        while True:
            data = wf.readframes(CHUNK_FRAMES)
            if len(data) == 0:
                break
            yield data
