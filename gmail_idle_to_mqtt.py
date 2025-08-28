from ssl import CERT_REQUIRED
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gmail を IMAP IDLE で監視し、条件に合致した新着だけ MQTT に publish する。
環境変数:
  GMAIL_USER, GMAIL_APP_PASSWORD
  MQTT_HOST=localhost, MQTT_PORT=1883, MQTT_TOPIC=inbox/matches
  (任意) IMAP_FOLDER=INBOX
条件編集: message_matches() をあなたの要件に合わせて変更。
"""
import os, ssl, time, json, email, logging, socket
from email.header import decode_header, make_header
from imapclient import IMAPClient
import backoff
import paho.mqtt.client as mqtt
from dotenv import load_dotenv
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def test_mqtt_connection():
    """MQTT接続をテストする"""
    try:
        logging.info("Testing MQTT connection...")
        client_id = os.environ.get('MQTT_CLIENT_ID','') or None
        client = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        client.username_pw_set(MQTT_USER, MQTT_PASS)
        if MQTT_TLS:
            # Use system's default certificate store (includes Let's Encrypt certificates)
            client.tls_set()
            if os.environ.get('MQTT_TLS_INSECURE','false').lower()=='true':
                client.tls_insecure_set(True)
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=10)
        client.disconnect()
        logging.info("✓ MQTT connection successful")
        return True
    except Exception as e:
        logging.error(f"✗ MQTT connection failed: {e}")
        return False

def test_imap_connection():
    """IMAP接続をテストする"""
    try:
        logging.info("Testing IMAP connection...")
        context = ssl.create_default_context()
        with IMAPClient(IMAP_HOST, port=IMAP_PORT, ssl=True, ssl_context=context) as conn:
            conn.login(GMAIL_USER, GMAIL_PASS)
            logging.info("✓ IMAP connection and authentication successful")
            return True
    except Exception as e:
        logging.error(f"✗ IMAP connection failed: {e}")
        return False

def run_connectivity_tests():
    """全ての接続テストを実行"""
    logging.info("Running connectivity tests...")
    mqtt_ok = test_mqtt_connection()
    imap_ok = test_imap_connection()
    
    if not mqtt_ok or not imap_ok:
        logging.error("Some connectivity tests failed. Check your network settings.")
        return False
    
    logging.info("All connectivity tests passed ✓")
    return True

# --- 設定 ---
IMAP_HOST   = "imap.gmail.com"
IMAP_PORT   = 993
IMAP_FOLDER = os.environ.get("IMAP_FOLDER", "INBOX")
IDLE_TIMEOUT = 5 * 60   # 5分に短縮してより頻繁に監視
FALLBACK_POLL_INTERVAL = 60  # IDLE失敗時の定期チェック間隔（秒）
FETCH_BODY_LIMIT = 4000 # MQTTに載せる本文の最大文字数
POLL_ON_WAKE = False     # 起動直後/IDLE脱出時にUNSEEN検索
# ---------------

# .env ファイルを同じフォルダから読み込む
base_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(base_dir, ".env"))

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_PASS = os.environ["GMAIL_PASS"]

MQTT_HOST = os.environ["MQTT_HOST"]
MQTT_PORT = int(os.environ.get("MQTT_PORT", "8883"))
MQTT_TLS = os.environ.get("MQTT_TLS", "true").lower() == "true"
MQTT_USER = os.environ["MQTT_USER"]
MQTT_PASS = os.environ["MQTT_PASS"]
MQTT_TOPIC = os.environ.get("MQTT_TOPIC", "inbox/matches")

# ---- 条件（例：件名キーワード & 送信元ドメイン）----
SUBJECT_KEYWORDS = ["地震情報","津波情報"]  # 任意
FROM_DOMAINS     = ["bosai-jma@jmainfo.go.jp"]          # 任意（部分一致OK）
BODY_REGEX       = None                       # 例: r"\bORD-\d{6}\b"
# ------------------------------------------------------

def decode_mime_header(raw):
    if not raw:
       return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw

def extract_text_body(msg: email.message.Message) -> str:
    # text/plain 優先、なければ text/html を簡易プレーンに
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = part.get("Content-Disposition", "") or ""
            if ctype == "text/plain" and "attachment" not in disp.lower():
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="replace")
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                charset = part.get_content_charset() or "utf-8"
                from html import unescape
                import re
                html = part.get_payload(decode=True).decode(charset, errors="replace")
                return unescape(re.sub(r"<[^>]+>", "", html))
        return ""
    else:
        charset = msg.get_content_charset() or "utf-8"
        return msg.get_payload(decode=True).decode(charset, errors="replace")

def message_matches(frm: str, subject: str, body: str) -> bool:
    _ = body  # 未使用パラメータ警告を回避
    logging.info(f"Checking message: From={frm}, Subject={subject}")
    
    # 地震・津波情報のフィルタリング
    subject_match = any(keyword in subject for keyword in SUBJECT_KEYWORDS)
    from_match = any(domain in frm for domain in FROM_DOMAINS)
    
    if subject_match and from_match:
        logging.info(f"✓ Message matches criteria: Subject contains {SUBJECT_KEYWORDS}, From contains {FROM_DOMAINS}")
        return True
    else:
        logging.info(f"✗ Message filtered out: Subject_match={subject_match}, From_match={from_match}")
        return False

def mqtt_publish(payload: dict):
    """MQTT メッセージ送信（エラーハンドリング強化版）"""
    max_retries = 3
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            client_id = os.environ.get('MQTT_CLIENT_ID','') or None
            client = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
            client.username_pw_set(MQTT_USER, MQTT_PASS)
            if MQTT_TLS:
                # Use system's default certificate store (includes Let's Encrypt certificates)
                client.tls_set()
                if os.environ.get('MQTT_TLS_INSECURE','false').lower()=='true':
                    client.tls_insecure_set(True)
            
            logging.info(f"📤 MQTT publish attempt {attempt + 1}/{max_retries}")
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            
            result = client.publish(
                MQTT_TOPIC,
                json.dumps(payload, ensure_ascii=False),
                qos=int(os.environ.get('MQTT_QOS','1')), retain=(os.environ.get('MQTT_RETAIN','false').lower()=='true')
            )
            
            client.disconnect()
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logging.info(f"✅ MQTT published: UID={payload.get('uid')}, Subject={payload.get('subject', '')[:50]}")
                return
            else:
                logging.warning(f"⚠️ MQTT publish returned code: {result.rc}")
                
        except Exception as e:
            logging.error(f"❌ MQTT publish failed (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2  # 指数バックオフ
            else:
                logging.error("💥 All MQTT publish attempts failed")

def fetch_and_process(conn: IMAPClient, uids):
    if not uids:
        return
    fetch_data = conn.fetch(uids, ["ENVELOPE", "RFC822", "BODY[HEADER.FIELDS (MESSAGE-ID DATE)]"])
    for uid in uids:
        data = fetch_data.get(uid)
        if not data: 
            continue
        raw = data[b"RFC822"]
        msg = email.message_from_bytes(raw)

        hdr_from = decode_mime_header(msg.get("From"))
        hdr_subj = decode_mime_header(msg.get("Subject"))
        body = extract_text_body(msg)
        body_out = body[:FETCH_BODY_LIMIT]

        if message_matches(hdr_from, hdr_subj, body):
            payload = {
                "uid": int(uid),
                "message_id": (msg.get("Message-Id") or msg.get("Message-ID") or "").strip(),
                "date": msg.get("Date") or "",
                "from": hdr_from,
                "subject": hdr_subj,
                "body": body_out,
                "timestamp": time.time(),
                "processed_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            logging.info(f"✅ Matched UID={uid}: {hdr_subj[:80]}")
            mqtt_publish(payload)
        else:
            logging.debug(f"🚫 Filtered UID={uid}: {hdr_subj[:80]}")

def search_new_unseen(conn: IMAPClient):
    try:
        uids = conn.search(["UNSEEN"])
        logging.info(f"📊 UNSEEN search result: {len(uids)} messages {uids if len(uids) < 10 else f'{uids[:5]}...(+{len(uids)-5} more)'}")
        return uids
    except Exception as e:
        logging.error(f"❌ UNSEEN search failed: {e}")
        return []

def ensure_selected(conn: IMAPClient):
    sel = conn.select_folder(IMAP_FOLDER, readonly=False)
    logging.info(f"Selected {IMAP_FOLDER}: {sel}")

@backoff.on_exception(backoff.expo, (socket.error, ssl.SSLError, IMAPClient.AbortError, IMAPClient.Error), max_time=None)
def run_loop():
    context = ssl.create_default_context()
    with IMAPClient(IMAP_HOST, port=IMAP_PORT, ssl=True, ssl_context=context) as conn:
        logging.info("Connecting IMAP…")
        try:
            conn.login(GMAIL_USER, GMAIL_PASS)
            logging.info("✓ Gmail login successful")
        except IMAPClient.Error as e:
            logging.error(f"✗ Gmail login failed: {e}")
            logging.error("Troubleshooting tips:")
            logging.error("1. Check if 2-factor authentication is enabled")
            logging.error("2. Make sure you're using an App Password, not your regular password")
            logging.error("3. Verify GMAIL_USER and GMAIL_PASS environment variables")
            logging.error("4. Check if IMAP is enabled in Gmail settings")
            raise e
        except Exception as e:
            logging.error(f"✗ Unexpected login error: {e}")
            raise e
            
        ensure_selected(conn)

        if POLL_ON_WAKE:
            uids = search_new_unseen(conn)
            fetch_and_process(conn, uids)

        last_unseen_check = time.time()
        last_unseen_count = 0
        
        while True:
            try:
                logging.info("📡 Starting IDLE mode for Gmail monitoring...")
                
                # IDLEモードを開始
                conn.idle()
                logging.info(f"⏳ IDLE started, waiting for notifications (timeout: {IDLE_TIMEOUT}s)")
                
                # 指定時間内で新着通知を待機
                response = conn.idle_check(timeout=IDLE_TIMEOUT)
                
                # IDLEモードを終了
                conn.idle_done()
                
                if response:
                    logging.info(f"🔔 IDLE notification received: {response}")
                    for i, r in enumerate(response):
                        logging.info(f"   [{i}] {type(r).__name__}: {r}")
                    
                    # 新着メール処理
                    uids = search_new_unseen(conn)
                    if uids:
                        fetch_and_process(conn, uids)
                    last_unseen_check = time.time()
                else:
                    logging.info("⏰ IDLE timeout - no notifications received")
                    
                # フォールバック: 定期的にUNSEEN検索で補完監視
                current_time = time.time()
                if current_time - last_unseen_check >= FALLBACK_POLL_INTERVAL:
                    logging.info(f"🔍 Fallback check (last: {int(current_time - last_unseen_check)}s ago)")
                    uids = search_new_unseen(conn)
                    current_count = len(uids)
                    
                    if current_count != last_unseen_count:
                        logging.info(f"📊 Unseen count changed: {last_unseen_count} → {current_count}")
                        if uids:
                            fetch_and_process(conn, uids)
                    
                    last_unseen_count = current_count
                    last_unseen_check = current_time
                    
            except IMAPClient.AbortError as e:
                logging.error(f"💔 IMAP connection aborted: {e}")
                logging.info("🔄 Reconnecting...")
                raise  # backoffで自動再接続
                
            except Exception as e:
                logging.error(f"⚠️ IDLE error: {e}")
                logging.info("🔄 Retrying IDLE in 5 seconds...")
                time.sleep(5)
                continue
                
            logging.info("🔄 IDLE session ended, restarting in 1 second...")
            time.sleep(1)

if __name__ == "__main__":
    try:
        # 接続テストを実行
        if not run_connectivity_tests():
            logging.error("Connectivity tests failed. Exiting.")
            exit(1)
        
        run_loop()
    except KeyboardInterrupt:
        logging.info("Stopped by user.")
