# Gmail to MQTT Alert System

Gmailの新着メールを監視してMQTTで通知し、デスクトップにポップアップ表示するシステムです。

## システム構成

```
Gmail IMAP IDLE → MQTT Broker → GUI Popup
     ↑               ↑             ↑
 gmail_sender.py  MQTTサーバー  gmail_receiver.py
```

## 主要ファイル

### 実用アプリケーション
- **`gmail_sender.py`** - Gmail監視・MQTT送信側アプリ（サーバーで常駐）
- **`gmail_receiver.py`** - MQTT受信・GUIポップアップ側アプリ（クライアントPC用）
- **`mqtt_mail_popup.py`** - MQTT受信・GUIポップアップ側アプリ（オリジナル版）
- **`gmail_service.py`** - Gmail IMAP IDLE サービスモジュール

### 設定ファイル
- **`.env`** - 環境変数（認証情報、MQTT設定）
- **`pyproject.toml`** - Python依存関係管理

### Docker関連
- **`docker-compose.yml`** - Docker環境での実行
- **`Dockerfile.server`** - 送信側用Dockerファイル
- **`Dockerfile.client`** - 受信側用Dockerファイル

## セットアップ

### 1. 依存関係のインストール

```bash
# uvを使用（推奨）
uv sync

# または pip
pip install -r requirements.txt
```

### 2. 環境変数の設定

`.env`ファイルを作成し、以下の設定を行います：

```env
# Gmail設定
GMAIL_USER=your-email@gmail.com
GMAIL_PASS=your-app-password

# MQTT設定
MQTT_HOST=your-mqtt-broker.com
MQTT_PORT=8883
MQTT_TLS=true
MQTT_USER=your-mqtt-user
MQTT_PASS=your-mqtt-password
MQTT_TOPIC=inbox/matches
MQTT_CLIENT_ID=gmail2mqtt-client

# 監視設定
IMAP_FOLDER=INBOX
SEARCH_KEYWORDS=地震情報,津波情報
```

### 3. Gmail App Password の取得

1. Googleアカウントの2段階認証を有効化
2. [App passwords](https://myaccount.google.com/apppasswords) でアプリパスワードを生成
3. 生成されたパスワードを `GMAIL_PASS` に設定

## 使用方法

### 送信側（Gmail監視）

```bash
# 直接実行
uv run gmail_sender.py

# Dockerで実行
docker-compose up gmail-monitor
```

### 受信側（ポップアップ表示）

```bash
# 直接実行（推奨）
uv run mqtt_mail_popup.py

# または新しい版
uv run gmail_receiver.py

# Dockerで実行（VNC接続）
docker-compose up client
# VNC: localhost:5901 で接続
```

### 両方同時実行

```bash
docker-compose up -d
```

## 機能

### 送信側（gmail_sender.py）
- Gmail IMAP IDLE監視による即座の新着通知
- 指定キーワードでのメールフィルタリング
- MQTT経由での通知送信
- 重複処理防止
- 自動再接続機能
- 詳細なログ出力

### 受信側（mqtt_mail_popup.py / gmail_receiver.py）
- MQTT経由でのリアルタイム通知受信
- デスクトップポップアップ表示
- メール本文のコピー機能
- 重複通知防止（UIDベース）
- キーボードショートカット（ESC で閉じる）
- 環境変数からの設定読み込み

## 設定のカスタマイズ

### メールフィルタリング

`gmail_sender.py` の `_message_matches()` メソッドを編集してフィルタリング条件を変更：

```python
def _message_matches(self, parsed_email) -> bool:
    subject = parsed_email.get('subject', '').lower()
    from_addr = parsed_email.get('from', '').lower()
    
    # カスタムフィルタリング条件
    if '緊急' in subject or 'alert' in subject:
        return True
    if 'noreply@important.com' in from_addr:
        return True
        
    return False
```

### MQTT設定

MQTTブローカーの設定に応じて `.env` を調整：

```env
# 非暗号化接続の場合
MQTT_PORT=1883
MQTT_TLS=false

# カスタムトピック
MQTT_TOPIC=alerts/email
```

## ログとモニタリング

### ログの確認

```bash
# 送信側のログ
docker-compose logs -f gmail-monitor

# 受信側のログ  
docker-compose logs -f client

# すべてのログ
docker-compose logs -f
```

### ステータス確認

```bash
# コンテナ状態
docker-compose ps

# 詳細情報
docker-compose exec gmail-monitor ps aux
```

## トラブルシューティング

### よくある問題

1. **Gmail認証エラー**
   - App Passwordが正しく設定されているか確認
   - 2段階認証が有効になっているか確認

2. **MQTT接続エラー**
   - ブローカーのアドレスとポート番号を確認
   - TLS設定が正しいか確認
   - ファイアウォール設定を確認

3. **GUI表示されない（Docker）**
   - VNC接続: `localhost:5901`
   - Mac: X11転送設定を確認

### ログレベル変更

詳細なデバッグ情報が必要な場合：

```python
logging.basicConfig(level=logging.DEBUG)
```

## 開発・デバッグ

### テスト実行

```bash
# 接続テストのみ
uv run gmail_sender.py --test-only

# デバッグモード
DEBUG=true uv run gmail_sender.py
```

### 開発環境

```bash
# 依存関係の追加
uv add package-name

# 仮想環境の作成
uv venv
source .venv/bin/activate
```

## セキュリティ

- Gmail App Passwordは適切に管理してください
- MQTT認証情報を安全に保管してください  
- 本番環境では `MQTT_TLS_INSECURE=false` に設定してください
- `.env` ファイルをリポジトリにコミットしないでください

## ライセンス

MIT License