"""
後処理補正 v2: Voskの単語分割（SetWords）を単位にして、登録済み用語の読みと
n-gram照合する方式。v1（文字レベルのスライド窓）は語の境界を無視して誤爆する
バグがあったため、Voskが返す単語区切りを最小単位として扱うよう改善した。
"""
import json
import wave
from pathlib import Path

from pykakasi import kakasi
from vosk import KaldiRecognizer, Model

MODEL_DIR = Path(__file__).parent / "vosk-model-small-ja-0.22"
kks = kakasi()


def to_reading(text: str) -> str:
    return "".join(item["hira"] for item in kks.convert(text))


def edit_distance(a: str, b: str) -> int:
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    return dp[n][m]


def recognize_words(wav_path: str) -> list[str]:
    wf = wave.open(wav_path, "rb")
    model = Model(str(MODEL_DIR))
    rec = KaldiRecognizer(model, wf.getframerate())
    rec.SetWords(True)

    words = []
    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            r = json.loads(rec.Result())
            words += [w["word"] for w in r.get("result", [])]
    final = json.loads(rec.FinalResult())
    words += [w["word"] for w in final.get("result", [])]
    return words


def correct_words(words: list[str], registered_terms: list[str], threshold: float = 0.34, max_ngram: int = 3):
    """単語列に対し、登録用語の読みに近いn-gram区間を探して置き換える。
    候補をスコア順に並べ、重複しない範囲だけを貪欲に採用することで
    v1で起きた重複置換を防ぐ。
    """
    candidates = []  # (score, start, end, term)
    for term in registered_terms:
        term_reading = to_reading(term)
        for n in range(1, max_ngram + 1):
            for start in range(0, len(words) - n + 1):
                span = "".join(words[start:start + n])
                span_reading = to_reading(span)
                dist = edit_distance(term_reading, span_reading)
                score = dist / max(len(term_reading), 1)
                if score < threshold:
                    candidates.append((score, start, start + n, term))

    # スコアが良い順。同スコアなら大きい区間（=複数語をまとめて置換）を優先し、
    # 「表彰症状」を「表彰」「症状」に分割して二重置換してしまう事故を防ぐ
    candidates.sort(key=lambda c: (c[0], -(c[2] - c[1])))

    used = [False] * len(words)
    replacements = {}  # start -> (end, term)
    for score, start, end, term in candidates:
        if any(used[start:end]):
            continue
        for i in range(start, end):
            used[i] = True
        replacements[start] = (end, term)

    out = []
    i = 0
    while i < len(words):
        if i in replacements:
            end, term = replacements[i]
            out.append(term)
            i = end
        else:
            out.append(words[i])
            i += 1
    return "".join(out)


if __name__ == "__main__":
    cases = [
        {
            "wav": "sample.wav",
            "registered": ["功績"],
        },
        {
            "wav": "name_test.wav",
            "registered": ["高橋", "美咲", "表彰状", "授与"],
        },
    ]

    for c in cases:
        words = recognize_words(c["wav"])
        raw_text = "".join(words)
        corrected = correct_words(words, c["registered"])
        print(f"=== {c['wav']} ===")
        print(f"補正前: {raw_text}")
        print(f"補正後: {corrected}")
        print()
