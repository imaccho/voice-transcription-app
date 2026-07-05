# VoiceSync バックエンド（フェーズ2: 基盤実装）

マイク入力 → Vosk（`recognizer.py`）→ WebSocket配信 という最小構成。
`app/main.html`（運用者用メイン画面）と `app/display.html`（HDMI外部モニタ用表示画面）の
両方に、同じ認識結果をリアルタイムで配信する。

## セットアップ

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Voskの日本語モデルは `poc/vosk-check/vosk-model-small-ja-0.22` を参照する。
まだ無い場合は `poc/vosk-check/README.md` の手順でダウンロードしておくこと。

## 起動

```bash
source venv/bin/activate
uvicorn server:app --port 8000
```

- 運用者用メイン画面: http://localhost:8000/
- HDMI外部モニタ用表示画面: http://localhost:8000/display （外部ディスプレイ側でブラウザをフルスクリーン表示する）

## 動作確認について

この開発環境には実マイクでの通しテストの手段がなかったため、`/api/start` に
`wav_path` を渡すことでWAVファイルをマイクの代わりに流し込めるようにしてある
（`poc/vosk-check/sample.wav` 等で確認済み）。実機のマイクでの動作は、
実際に運用するPC上で下記のように確認すること。

```bash
# マイク一覧の確認
curl http://localhost:8000/api/devices

# 実マイクで開始（device_indexは上記で確認した番号）
curl -X POST http://localhost:8000/api/start -H "Content-Type: application/json" -d '{"device_index": 0}'

# 停止
curl -X POST http://localhost:8000/api/stop
```

## 表示許可リストの登録

```bash
curl -X POST http://localhost:8000/api/names -H "Content-Type: application/json" -d '{"terms": ["功績", "高橋", "美咲"]}'
```

登録した用語は、Voskの生の認識結果に対して読みベースの後処理補正（`recognizer.py` の
`correct_words`、PoCの `correct_by_reading_v2.py` と同じアルゴリズム）で反映される。
まだ資料からの自動抽出・登録UIは未実装のため、現時点ではこのAPIを直接叩く形になる。

## 未実装・既知の制約

- 実マイクでの継続的な動作確認（本番相当の長時間稼働・雑音環境）は未実施
- ログ保存（SQLite等）は未実装。現状は画面に表示されるのみで永続化されない
- 表示許可リストの登録UI（資料からの候補抽出・画像を見ながらの手動入力）は未実装。`docs/app-design.md` の設計に基づき今後実装する
- 設定画面（文字サイズ・色、HDMI出力先の選択など）は未実装
