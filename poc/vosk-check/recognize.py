"""
Vosk 素の精度検証スクリプト（辞書登録なし・ベースライン計測用）

使い方:
  python3 recognize.py <wavファイル> <正解テキストファイル>

WAVは 16kHz / mono / 16bit PCM を前提とする。
認識結果と正解テキストを文字誤り率（CER）で比較する。
"""
import sys
import json
import wave
from pathlib import Path

from vosk import Model, KaldiRecognizer

MODEL_DIR = Path(__file__).parent / "vosk-model-small-ja-0.22"


def recognize(wav_path: str) -> str:
    wf = wave.open(wav_path, "rb")
    if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
        raise ValueError("WAVは mono / 16bit PCM である必要があります")

    model = Model(str(MODEL_DIR))
    rec = KaldiRecognizer(model, wf.getframerate())
    rec.SetWords(True)

    pieces = []
    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            result = json.loads(rec.Result())
            if result.get("text"):
                pieces.append(result["text"])
    final = json.loads(rec.FinalResult())
    if final.get("text"):
        pieces.append(final["text"])

    return "".join(pieces)


def normalize(text: str) -> str:
    # Vosk日本語モデルは分かち書き（単語間スペース）で出力するため、
    # 文字単位比較のためにスペースを除去して正規化する
    return text.replace(" ", "").replace("　", "").strip()


def char_error_rate(ref: str, hyp: str) -> float:
    """レーベンシュタイン距離ベースの文字誤り率（CER）を計算する"""
    ref, hyp = list(ref), list(hyp)
    n, m = len(ref), len(hyp)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            dp[i][j] = min(
                dp[i - 1][j] + 1,      # 削除
                dp[i][j - 1] + 1,      # 挿入
                dp[i - 1][j - 1] + cost,  # 置換 or 一致
            )
    return dp[n][m] / max(n, 1)


def main():
    if len(sys.argv) != 3:
        print("usage: python3 recognize.py <wav> <ground_truth.txt>")
        sys.exit(1)

    wav_path, gt_path = sys.argv[1], sys.argv[2]
    ground_truth = normalize(Path(gt_path).read_text(encoding="utf-8"))

    print("=== 認識中... ===")
    recognized_raw = recognize(wav_path)
    recognized = normalize(recognized_raw)

    cer = char_error_rate(ground_truth, recognized)

    print("\n--- 正解テキスト ---")
    print(ground_truth)
    print("\n--- 認識結果（分かち書きのまま） ---")
    print(recognized_raw)
    print("\n--- 認識結果（比較用に正規化） ---")
    print(recognized)
    print(f"\n=== 文字誤り率（CER）: {cer * 100:.1f}% ===")


if __name__ == "__main__":
    main()
