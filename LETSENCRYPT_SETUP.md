# Let's Encrypt + DuckDNS MQTT TLS設定

## 概要
DuckDNSドメイン `add-message-app-0922.duckdns.org` とLet's Encrypt証明書を使用したMQTT over TLS設定。

## 前提条件
- DuckDNSアカウントとドメイン設定済み
- Google Compute Engine VM実行中
- Mosquitto MQTT ブローカーインストール済み

## 1. DuckDNS設定確認

```bash
# 現在のIPを確認
curl ifconfig.me

# DuckDNSで設定したIPが正しいか確認
nslookup add-message-app-0922.duckdns.org
```

## 2. Let's Encrypt証明書取得（GCE VM上で実行）

```bash
# Certbotインストール
sudo apt update
sudo apt install -y certbot

# HTTP-01チャレンジ用にポート80を一時的に開放
sudo ufw allow 80/tcp

# 証明書取得（standalone mode）
sudo certbot certonly --standalone \
  -d add-message-app-0922.duckdns.org \
  --email yosking0922@gmail.com \
  --agree-tos \
  --non-interactive

# ポート80を閉じる
sudo ufw delete allow 80/tcp
```

## 3. Mosquitto設定更新

`/etc/mosquitto/mosquitto.conf`を以下のように編集：

```bash
sudo nano /etc/mosquitto/mosquitto.conf
```

```conf
# 1883ポート（localhost のみ）
listener 1883 localhost
allow_anonymous false
password_file /etc/mosquitto/passwd

# 8883ポート（TLS、外部接続許可）- Let's Encrypt証明書使用
listener 8883
cafile /etc/letsencrypt/live/add-message-app-0922.duckdns.org/chain.pem
certfile /etc/letsencrypt/live/add-message-app-0922.duckdns.org/cert.pem
keyfile /etc/letsencrypt/live/add-message-app-0922.duckdns.org/privkey.pem
tls_version tlsv1.2
allow_anonymous false
password_file /etc/mosquitto/passwd
```

## 4. 証明書ファイル権限設定

```bash
# mosquittoユーザーに証明書読み取り権限を付与
sudo usermod -a -G ssl-cert mosquitto

# または証明書ディレクトリの権限を調整
sudo chmod 755 /etc/letsencrypt/live/
sudo chmod 755 /etc/letsencrypt/archive/
sudo chmod 640 /etc/letsencrypt/live/add-message-app-0922.duckdns.org/*.pem
sudo chgrp ssl-cert /etc/letsencrypt/live/add-message-app-0922.duckdns.org/*.pem
```

## 5. Mosquitto再起動

```bash
sudo systemctl restart mosquitto
sudo systemctl status mosquitto

# エラーログ確認
sudo journalctl -u mosquitto -n 20
```

## 6. 証明書自動更新設定

```bash
# 自動更新スクリプト作成
sudo tee /etc/cron.d/certbot-renewal > /dev/null << 'EOF'
0 12 * * * root certbot renew --quiet --post-hook "systemctl reload mosquitto"
EOF
```

## 7. 接続テスト

```bash
# クライアント側からのテスト
mosquitto_pub -h add-message-app-0922.duckdns.org -p 8883 \
  --capath /etc/ssl/certs \
  -u alice -P 9221w8bSEqoF9221 \
  -t test -m "Let's Encrypt TLS test"

mosquitto_sub -h add-message-app-0922.duckdns.org -p 8883 \
  --capath /etc/ssl/certs \
  -u alice -P 9221w8bSEqoF9221 \
  -t test
```

## クライアント設定変更点

### .env設定
```env
MQTT_HOST=add-message-app-0922.duckdns.org
MQTT_PORT=8883
MQTT_TLS=true
MQTT_CAFILE=                    # 空にする（システム証明書を使用）
MQTT_TLS_INSECURE=false
```

## トラブルシューティング

### 証明書エラーの場合
```bash
# 証明書の有効期限確認
sudo certbot certificates

# Mosquittoが証明書にアクセスできるか確認
sudo -u mosquitto cat /etc/letsencrypt/live/add-message-app-0922.duckdns.org/cert.pem
```

### DuckDNS IP更新
```bash
# DuckDNS IP更新（必要に応じて）
curl "https://www.duckdns.org/update?domains=add-message-app-0922&token=YOUR_TOKEN&ip="
```

## セキュリティ上の利点

1. **信頼された証明書**: Let's EncryptはブラウザとOSに信頼されている
2. **自動更新**: 証明書の期限切れを防止
3. **ドメイン検証済み**: IPアドレス直接接続より安全
4. **完全なTLS暗号化**: 通信内容の保護

## 更新履歴
- 2024-08-28: Let's Encrypt + DuckDNS設定追加