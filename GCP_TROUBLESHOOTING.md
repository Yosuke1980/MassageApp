# GCP Compute Engine トラブルシューティングガイド

## セットアップ手順

### 0. gcloud認証の確認・修正
```bash
# 認証状況確認
gcloud auth list

# 認証スコープエラーが出る場合は再認証
gcloud auth login --enable-gdrive-access

# またはアプリケーションデフォルト認証
gcloud auth application-default login
```

### 1. VMにログインしてディレクトリ作成
```bash
# VM にログイン
ggc

# ディレクトリを作成
mkdir -p ~/MassageApp

# ログアウト
exit
```

### 2. ファイルをGCP VMに転送
```bash
# ローカルから GCP VM へファイルを転送（フルパス指定）
gcloud compute scp /Volumes/MyDrive/GitHub/MassageApp/gmail_idle_to_mqtt.py message:~/MassageApp/ --zone=us-central1-c
gcloud compute scp /Volumes/MyDrive/GitHub/MassageApp/.env message:~/MassageApp/ --zone=us-central1-c
gcloud compute scp /Volumes/MyDrive/GitHub/MassageApp/gmail-idle.service message:~ --zone=us-central1-c
```

### 3. 仮想環境の確認
```bash
# VM にログイン
gcloud compute ssh message --zone=us-central1-c

# 仮想環境をアクティベート
source ~/venv-gmail/bin/activate

# 必要なパッケージがインストールされているか確認
pip list | grep -E "(imapclient|paho-mqtt|backoff|python-dotenv)"
```

### 4. systemdサービスの設定
```bash
# サービスファイルをsystemdディレクトリに移動（要sudo）
sudo cp ~/gmail-idle.service /etc/systemd/system/

# サービスを有効化
sudo systemctl daemon-reload
sudo systemctl enable gmail-idle.service
sudo systemctl start gmail-idle.service
```

## 一般的な問題と解決方法

### 1. 接続テストが失敗する

#### MQTT接続エラー
```bash
# ファイアウォール設定を確認
sudo ufw status

# MQTTポート（1883）が開いているか確認
telnet 23.251.158.46 1883
```

#### IMAP接続エラー
```bash
# Gmail IMAPポート（993）への接続確認
telnet imap.gmail.com 993
```

### 2. Gmail認証エラー

**症状**: `✗ Gmail login failed` エラー

**解決方法**:
1. Gmailで2段階認証が有効になっているか確認
2. アプリパスワードを使用しているか確認
3. IMAPが有効になっているか確認（Gmail設定 → 転送とPOP/IMAP）

### 3. 環境変数が読み込めない

**症状**: `KeyError: 'GMAIL_USER'` などのエラー

**解決方法**:
```bash
# .envファイルが正しい場所にあるか確認
ls -la ~/MassageApp/.env

# 環境変数が正しく設定されているか確認
cd ~/MassageApp
source ~/venv-gmail/bin/activate
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print(os.environ.get('GMAIL_USER'))"
```

### 4. systemdサービスが起動しない

#### ステータス確認
```bash
# サービスの状態を確認
sudo systemctl status gmail-idle.service

# 詳細ログを確認
sudo journalctl -u gmail-idle.service -f
```

#### 一般的な問題
- **ファイルパスが間違っている**: serviceファイル内のパスを確認
- **権限問題**: ユーザー名とファイル権限を確認
- **仮想環境のパス**: `/home/watanabeyousuke/venv-gmail/bin/python` が正しいか確認

### 5. GCPファイアウォール設定

#### エグレス（送信）ルールの確認
```bash
# 現在のファイアウォールルールを確認
gcloud compute firewall-rules list

# MQTT/IMAPへの送信を許可（必要に応じて）
gcloud compute firewall-rules create allow-egress-mqtt-imap \
  --direction=EGRESS \
  --action=ALLOW \
  --rules=tcp:993,tcp:1883 \
  --destination-ranges=0.0.0.0/0
```

## デバッグコマンド集

### 接続テスト
```bash
# スクリプトを手動実行してテスト
cd ~/MassageApp
source ~/venv-gmail/bin/activate
python gmail_idle_to_mqtt.py
```

### ログ監視
```bash
# リアルタイムでログを監視
sudo journalctl -u gmail-idle.service -f

# 過去のログを確認
sudo journalctl -u gmail-idle.service --since "1 hour ago"
```

### サービス管理
```bash
# サービス停止
sudo systemctl stop gmail-idle.service

# サービス再起動
sudo systemctl restart gmail-idle.service

# サービス無効化
sudo systemctl disable gmail-idle.service
```

## ログの見方

### 正常起動時のログ
```
INFO Running connectivity tests...
INFO Testing MQTT connection...
INFO ✓ MQTT connection successful
INFO Testing IMAP connection...
INFO ✓ IMAP connection and authentication successful
INFO All connectivity tests passed ✓
INFO Connecting IMAP…
INFO ✓ Gmail login successful
INFO Selected INBOX: {'EXISTS': 1234, 'RECENT': 0, ...}
INFO Entering IDLE…
```

### エラー発生時のログパターン
- `✗ MQTT connection failed`: MQTTブローカーへの接続失敗
- `✗ IMAP connection failed`: Gmailへの接続失敗
- `✗ Gmail login failed`: 認証失敗
- `Connectivity tests failed`: 初期接続テスト失敗

## パフォーマンス最適化

### VM仕様推奨
- **マシンタイプ**: e2-micro (十分)
- **リージョン**: アジア太平洋（Tokyo）推奨
- **ディスク**: 10GB SSD

### ネットワーク設定
- 静的IPアドレスの使用を検討
- ファイアウォールルールの最適化

## よくある質問

**Q: サービスが突然停止する**
A: `sudo journalctl -u gmail-idle.service` でログを確認。Gmail側のIDLE制限（30分）で正常に再接続しているか確認。

**Q: メッセージが重複して送信される**
A: MQTT QoS設定とGmailのUNSEEN検索ロジックを確認。

**Q: 一部のメールが検知されない**
A: `message_matches()` 関数の条件と、Gmail側でのフィルタ設定を確認。