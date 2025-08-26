# MQTT TLS設定手順

## 概要
Gmail監視アプリとMQTTブローカー間の通信をTLS暗号化する設定手順。

## 環境
- MQTTブローカー: Google Compute Engine上のMosquitto
- ブローカーIP: 23.251.158.46
- 認証: alice / 9221w8bSEqoF9221

## 1. SSL証明書生成（GCE VM上で実行）

```bash
# 証明書ディレクトリ作成
sudo mkdir -p /etc/mosquitto/certs
cd /etc/mosquitto/certs

# CA証明書を生成
sudo openssl genrsa -out ca.key 2048
sudo openssl req -new -x509 -days 365 -key ca.key -out ca.crt \
  -subj "/C=JP/ST=Tokyo/L=Tokyo/O=Test/CN=mosquitto-ca"

# サーバー証明書を生成
sudo openssl genrsa -out server.key 2048
sudo openssl req -new -key server.key -out server.csr \
  -subj "/C=JP/ST=Tokyo/L=Tokyo/O=Test/CN=23.251.158.46"
sudo openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key \
  -CAcreateserial -out server.crt -days 365

# 権限設定
sudo chown mosquitto:mosquitto /etc/mosquitto/certs/*
sudo chmod 600 /etc/mosquitto/certs/*.key
```

## 2. Mosquitto設定更新

`/etc/mosquitto/mosquitto.conf`を編集：

```
# 1883ポート（localhost のみ）
listener 1883 localhost
allow_anonymous false
password_file /etc/mosquitto/passwd

# 8883ポート（TLS、外部接続許可）
listener 8883
cafile /etc/mosquitto/certs/ca.crt
certfile /etc/mosquitto/certs/server.crt
keyfile /etc/mosquitto/certs/server.key
tls_version tlsv1.2
allow_anonymous false
password_file /etc/mosquitto/passwd
```

## 3. ファイアウォール設定

### GCP ファイアウォールルール
```bash
# 8883ポートを開放
gcloud compute firewall-rules create allow-mqtt-tls \
  --allow tcp:8883 \
  --source-ranges 0.0.0.0/0 \
  --description "MQTT over TLS"

# 既存の1883ルールを確認
gcloud compute firewall-rules list --filter="name~mqtt"

# 1883ポートを閉じる（セキュリティ向上）
# 既存ルールから1883を削除または専用ルールを削除
```

### VM内ファイアウォール
```bash
# Ubuntu/Debian
sudo ufw allow 8883/tcp

# 必要に応じて1883を閉じる
sudo ufw delete allow 1883/tcp
```

## 4. Mosquitto再起動

```bash
sudo systemctl restart mosquitto
sudo systemctl status mosquitto

# ログ確認
sudo journalctl -u mosquitto -f
```

## 5. 接続テスト

```bash
# TLS接続テスト
mosquitto_pub -h 23.251.158.46 -p 8883 --cafile /etc/mosquitto/certs/ca.crt \
  -u alice -P 9221w8bSEqoF9221 -t test -m "TLS test"

mosquitto_sub -h 23.251.158.46 -p 8883 --cafile /etc/mosquitto/certs/ca.crt \
  -u alice -P 9221w8bSEqoF9221 -t test
```

## 6. アプリケーション設定

### 環境変数
```bash
MQTT_HOST=23.251.158.46
MQTT_PORT=8883
MQTT_TLS=true
MQTT_USER=alice
MQTT_PASS=9221w8bSEqoF9221
MQTT_TOPIC=inbox/matches
```

### 変更されたファイル
- `gmail_idle_to_mqtt.py`: TLS設定とポート変更
- `gmail_idle_to_mqtt_improved.py`: TLS設定とポート変更  
- `mqtt_mail_popup.py`: TLS設定とポート変更

## セキュリティメモ

- 1883ポート（平文）は外部接続を無効化
- 8883ポート（TLS）のみ外部接続を許可
- 自己署名証明書使用（本番環境では適切なCA証明書を推奨）
- 認証必須（allow_anonymous false）

## トラブルシューティング

### 接続エラーの場合
1. ファイアウォールルール確認
2. Mosquittoログ確認: `sudo journalctl -u mosquitto`
3. 証明書ファイルの権限確認
4. 設定ファイルの構文確認: `sudo mosquitto -c /etc/mosquitto/mosquitto.conf -v`

### 証明書エラーの場合
クライアント側で証明書検証を無効化（テスト用）：
```python
client.tls_set(ca_certs=None, certfile=None, keyfile=None, cert_reqs=ssl.CERT_NONE)
client.tls_insecure_set(True)
```

## 更新履歴
- 2024-08-26: 初回作成、TLS設定追加