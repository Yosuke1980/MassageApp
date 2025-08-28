# Docker起動手順

## 前提条件

- Docker Engineがインストールされていること
- Docker Composeがインストールされていること
- `.env`ファイルが適切に設定されていること

## 起動手順

### 1. 環境変数の設定

`.env`ファイルが存在することを確認してください。必要な環境変数が設定されていることを確認します。

### 2. Dockerコンテナの起動

プロジェクトルートディレクトリで以下のコマンドを実行します：

```bash
docker-compose up -d
```

または、ログを表示しながら起動する場合：

```bash
docker-compose up
```

### 3. 起動確認

コンテナの状態を確認：

```bash
docker-compose ps
```

ログの確認：

```bash
# 全サービスのログ
docker-compose logs -f

# 特定のサービスのログ
docker-compose logs -f gmail-monitor
docker-compose logs -f client
```

## サービス構成

- **gmail-monitor**: GmailのIMAP監視サービス（サーバーサイド）
- **client**: MQTT経由でメッセージを受信してGUIポップアップを表示するクライアント

## GUI表示について

### Mac環境の場合

X11転送が必要です：

```bash
# XQuartzがインストールされていることを確認
xhost +localhost
```

### Windows環境の場合

VNC接続でGUIにアクセスできます：
- ポート: 5901
- VNCクライアントで `localhost:5901` に接続

## 停止・再起動

### 停止

```bash
docker-compose down
```

### 再起動

```bash
docker-compose restart
```

### 特定のサービスのみ再起動

```bash
docker-compose restart gmail-monitor
docker-compose restart client
```

## トラブルシューティング

### ログの詳細確認

```bash
# ログファイルの確認
ls -la logs/

# コンテナ内部の確認
docker-compose exec gmail-monitor /bin/sh
```

### 設定の再読み込み

環境変数を変更した場合は、コンテナを再起動してください：

```bash
docker-compose down
docker-compose up -d
```

### ヘルスチェック

Gmail監視サービスのヘルスチェック：

```bash
docker-compose exec gmail-monitor ps aux
```