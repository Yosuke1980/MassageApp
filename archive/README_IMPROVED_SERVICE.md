# Gmail IMAP IDLE Service - 改善版

alertappの実績あるアーキテクチャをベースに、MassageAppのGmail監視機能を大幅に改善しました。

## 改善された機能

### ✅ EventEmitterベースのアーキテクチャ
- モジュール化された設計
- イベント駆動の処理
- 各コンポーネントの独立性

### ✅ 堅牢な接続管理
- **指数バックオフ再接続**: 一時的な接続障害に対する耐性
- **最大再試行回数制限**: 無限ループの防止
- **グレースフルシャットダウン**: 正常なサービス終了

### ✅ 重複処理防止
- **processedUIDs管理**: 同じメッセージの重複処理を防止
- **メッセージID追跡**: 確実な重複チェック

### ✅ Gmail制限への対応
- **定期的なIDLE再発行**: Gmail IMAP制限への対応
- **適切なタイムアウト処理**: 接続の安定性向上

### ✅ エラーハンドリング強化
- 詳細なログ出力
- 各段階でのエラー捕捉
- 統計情報の収集

## ファイル構成

```
/Volumes/MyDrive/GitHub/MassageApp/
├── gmail_imap_service.py           # 新しいIMAPサービスクラス
├── gmail_idle_to_mqtt_improved.py  # 改善されたメインスクリプト  
├── test_improved_service.py        # テストスクリプト
├── gmail_idle_to_mqtt.py           # 元のスクリプト（参考用）
└── .env                            # 環境設定ファイル
```

## 使用方法

### 1. 環境設定
`.env`ファイルに以下の変数を設定：

```bash
# Gmail設定
GMAIL_USER=your_email@gmail.com
GMAIL_PASS=your_app_password

# MQTT設定  
MQTT_HOST=your_mqtt_host
MQTT_PORT=1883
MQTT_USER=your_mqtt_user
MQTT_PASS=your_mqtt_password
MQTT_TOPIC=inbox/matches

# 監視設定
SEARCH_KEYWORDS=地震情報,津波情報,earthquake,tsunami
FROM_DOMAINS=bosai-jma@jmainfo.go.jp
IMAP_FOLDER=INBOX
IDLE_TIMEOUT=300
FETCH_BODY_LIMIT=4000
```

### 2. 実行
```bash
# テスト実行
python3 test_improved_service.py

# サービス開始
python3 gmail_idle_to_mqtt_improved.py
```

### 3. 動作確認
- 接続テストが自動実行されます
- ログでIMAPとMQTTの接続状況を確認できます
- Ctrl+C で正常にシャットダウンします

## ログ出力例

```
2025-08-26 02:35:33,111 INFO === Gmail to MQTT Monitor Starting ===
2025-08-26 02:35:33,111 INFO Running connectivity tests...
2025-08-26 02:35:33,111 INFO ✓ MQTT connection successful
2025-08-26 02:35:33,111 INFO ✓ IMAP connection and authentication successful
2025-08-26 02:35:33,111 INFO ✓ IMAP service connected
2025-08-26 02:35:33,111 INFO 📡 IMAP IDLE monitoring started
2025-08-26 02:35:33,111 INFO === Gmail to MQTT Monitor Started Successfully ===
```

## 主要な改善点

| 項目 | 元の実装 | 改善版 |
|------|----------|--------|
| アーキテクチャ | スクリプト形式 | EventEmitter + サービスクラス |
| 再接続 | backoffのみ | 指数バックオフ + 最大試行回数 |
| 重複処理 | 基本的なUID管理 | processedUIDs + 厳密なチェック |
| IDLE管理 | 基本的なタイムアウト | 定期再発行 + Gmail制限対応 |
| エラー処理 | 基本的なログ | 詳細なログ + 統計情報 |
| 接続監視 | 簡易チェック | 包括的な接続テスト |

## 互換性
- 既存の`.env`設定ファイルをそのまま使用可能
- MQTT出力フォーマットは既存と同じ
- 既存のスクリプトと並行実行可能（ポート衝突なし）