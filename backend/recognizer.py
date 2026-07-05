"""
Vosk音声認識エンジンのラッパー。

PoC（poc/vosk-check）で確認した以下の方針をそのまま実装に持ち込む：
- Voskのgrammar機能には辞書登録せず、素の認識結果をそのまま出す
- 表示許可リスト（人名・専門用語）は、認識結果に対する
  読みベースの後処理補正（correct_by_reading_v2.py と同じアルゴリズム）で反映する
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable

from pykakasi import kakasi
from vosk import KaldiRecognizer, Model

SAMPLE_RATE = 16000

_kks = kakasi()


def to_reading(text: str) -> str:
    return "".join(item["hira"] for item in _kks.convert(text))


def _edit_distance(a: str, b: str) -> int:
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


_SENTENCE_END_CHARS = "。！？!?」』"


def ensure_period(text: str) -> str:
    """文末に句読点が無ければ「。」を補う"""
    if text and text[-1] not in _SENTENCE_END_CHARS:
        return text + "。"
    return text


def correct_words(words: list[str], registered_terms: list[str], threshold: float = 0.34, max_ngram: int = 3) -> str:
    """表示許可リストの読みに近い単語(n-gram)を、登録済み表記に置き換える。

    同スコアの候補は大きい区間を優先することで、1つの誤認識を
    複数の部分区間として二重に置換してしまう事故を防ぐ
    （詳細は poc/vosk-check/README.md の v1/v2 比較を参照）。
    """
    if not registered_terms:
        return "".join(words)

    candidates = []
    for term in registered_terms:
        term_reading = to_reading(term)
        for n in range(1, max_ngram + 1):
            for start in range(0, len(words) - n + 1):
                span = "".join(words[start:start + n])
                span_reading = to_reading(span)
                dist = _edit_distance(term_reading, span_reading)
                score = dist / max(len(term_reading), 1)
                if score < threshold:
                    candidates.append((score, start, start + n, term))

    candidates.sort(key=lambda c: (c[0], -(c[2] - c[1])))

    used = [False] * len(words)
    replacements = {}
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


class VoskEngine:
    """1マイク分のストリーミング認識セッションを保持するエンジン。"""

    # 無音が無いまま喋り続けた場合でも、この文字数を超えたら強制的に
    # 区切って確定させる（早口で喋り続けると文字がどんどん縮小してしまうため）
    MAX_PARTIAL_CHARS = 25

    def __init__(self, model_dir: str | Path, sample_rate: int = SAMPLE_RATE):
        self.model = Model(str(model_dir))
        self.sample_rate = sample_rate
        self.registered_terms: list[str] = []

    def set_registered_terms(self, terms: list[str]) -> None:
        """表示許可リストを更新する（画面側の名前登録UIから呼ばれる想定）"""
        self.registered_terms = list(terms)

    def new_recognizer(self) -> KaldiRecognizer:
        rec = KaldiRecognizer(self.model, self.sample_rate)
        rec.SetWords(True)
        return rec

    def run(
        self,
        audio_chunks: Iterable[bytes],
        on_partial: Callable[[str], None],
        on_final: Callable[[str], None],
    ) -> None:
        """audio_chunks（16kHz/mono/16bit PCMの生バイト列）を順に食わせ、
        部分結果・確定結果をそれぞれコールバックへ渡す。
        """
        rec = self.new_recognizer()

        def finalize(natural_pause: bool) -> None:
            """今の暫定認識結果を確定させて次に備える。
            Result() は呼んだ時点までの認識結果を確定させつつ、
            デコーダの状態をリセットして続けて音声を受け付けられるようにする。

            natural_pause=True（無音を検知した本当の文の区切り）の時だけ
            句点を補う。文字数超過による強制区切りは文の途中でしかないため、
            句点を付けない。
            """
            result = json.loads(rec.Result())
            words = [w["word"] for w in result.get("result", [])]
            if words:
                text = correct_words(words, self.registered_terms)
                on_final(ensure_period(text) if natural_pause else text)

        for chunk in audio_chunks:
            if rec.AcceptWaveform(chunk):
                finalize(natural_pause=True)
            else:
                partial = json.loads(rec.PartialResult()).get("partial", "")
                if partial:
                    on_partial(partial)
                    if len(partial.replace(" ", "")) >= self.MAX_PARTIAL_CHARS:
                        finalize(natural_pause=False)

        final = json.loads(rec.FinalResult())
        words = [w["word"] for w in final.get("result", [])]
        if words:
            on_final(ensure_period(correct_words(words, self.registered_terms)))
