"""
後処理補正の検証: Voskの生の認識結果に対し、登録済み用語リストの「読み」と
照合してフレーズを置換できるかを試すプロトタイプ。

設計メモ（docs/app-design.md）で書いた「音声認識時の文脈活用」の
後処理補正方式が実際に機能するかを確認する。
"""
import sys
from pykakasi import kakasi

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


def correct(text: str, registered_terms: list[str], threshold: float = 0.3) -> str:
    """registered_terms の読みに近い部分文字列を探して置換する（貪欲・簡易実装）"""
    result = text
    for term in registered_terms:
        term_reading = to_reading(term)
        term_len = len(term)
        best_start, best_score = None, threshold
        # 用語の文字数 ±2 の範囲でスライドさせて読みを比較する
        for w in range(max(1, term_len - 2), term_len + 3):
            for start in range(0, len(result) - w + 1):
                window = result[start:start + w]
                window_reading = to_reading(window)
                dist = edit_distance(term_reading, window_reading)
                score = dist / max(len(term_reading), 1)
                if score < best_score:
                    best_score = score
                    best_start = (start, w)
        if best_start:
            start, w = best_start
            result = result[:start] + term + result[start + w:]
    return result


if __name__ == "__main__":
    cases = [
        {
            "raw": "今年度特に鉱石のあった皆様をご紹介いたします",
            "registered": ["功績"],
            "expected": "今年度特に功績のあった皆様をご紹介いたします",
        },
        {
            "raw": "高橋美咲さんに表彰症状を用意いたします",
            "registered": ["高橋", "美咲", "表彰状", "授与"],
            "expected": "高橋美咲さんに表彰状を授与いたします",
        },
    ]

    for i, c in enumerate(cases, 1):
        corrected = correct(c["raw"], c["registered"])
        ok = "OK" if corrected == c["expected"] else "NG"
        print(f"--- ケース{i} [{ok}] ---")
        print(f"認識結果(補正前): {c['raw']}")
        print(f"登録用語        : {c['registered']}")
        print(f"補正後          : {corrected}")
        print(f"期待値          : {c['expected']}")
        print()
