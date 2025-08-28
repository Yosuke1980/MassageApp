#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gmail IMAP IDLE - 簡素化テスト版
fetch処理をスキップして、EXISTS更新とダミーUID処理のテスト
"""
import asyncio
import logging
import sys
import os
import time

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gmail_idle_to_mqtt_improved import GmailToMqttMonitor

# ログレベルをINFOに設定
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class SimpleTestMonitor(GmailToMqttMonitor):
    """fetch処理を簡素化したテスト用モニター"""
    
    def __init__(self):
        super().__init__()
        self.simple_test_mode = True
    
    async def start_simple_test(self):
        """簡素化テストモードで開始"""
        try:
            logging.info("🧪 === Gmail IMAP IDLE Simple Test Mode ===")
            logging.info("📝 This version bypasses complex UID fetching for testing")
            logging.info("-" * 50)
            
            # Test connections first
            if not await self._test_connections():
                logging.error("Connection tests failed. Exiting.")
                return False
            
            # Initialize IMAP service
            from gmail_imap_service import ImapIdleService
            
            # Create a simplified version of the IMAP service
            self.imap_service = SimplifiedImapIdleService(self.config)
            self._setup_imap_service_events()
            
            # Start IMAP monitoring
            await self.imap_service.start()
            
            self.is_running = True
            logging.info("✅ Simple test mode started successfully")
            
            # Keep the service running
            while self.is_running:
                await asyncio.sleep(1)
            
            return True
            
        except Exception as e:
            logging.error(f"Failed to start simple test: {e}")
            import traceback
            logging.error(f"Traceback: {traceback.format_exc()}")
            return False

class SimplifiedImapIdleService:
    """簡素化されたIMAP IDLEサービス - fetch処理をスキップ"""
    
    def __init__(self, config):
        self.config = config
        self.is_connected = False
        self.last_exists_count = 0
        self.processed_uids = set()
        self.listeners = {}
        
    def on(self, event, callback):
        """イベントリスナー登録"""
        if event not in self.listeners:
            self.listeners[event] = []
        self.listeners[event].append(callback)
    
    def emit(self, event, *args):
        """イベント発火"""
        if event in self.listeners:
            for callback in self.listeners[event]:
                try:
                    callback(*args)
                except Exception as e:
                    logging.error(f"Error in event listener: {e}")
    
    async def start(self):
        """サービス開始（ダミー実装）"""
        logging.info("🧪 Starting simplified IMAP service")
        self.is_connected = True
        self.last_exists_count = 1291  # ダミー初期値
        
        logging.info(f"📊 Set initial EXISTS count to: {self.last_exists_count}")
        
        # 2秒後にダミーIDLE通知をシミュレート
        await asyncio.sleep(2)
        self._simulate_idle_notification()
    
    def _simulate_idle_notification(self):
        """IDLE通知をシミュレート"""
        logging.info("🔔 Simulating IDLE notification...")
        
        # 新しいEXISTS数をシミュレート
        new_exists_count = self.last_exists_count + 1
        logging.info(f"📊 EXISTS count change: {self.last_exists_count} → {new_exists_count}")
        
        if new_exists_count > self.last_exists_count:
            # 簡素化: ダミーUIDを生成してアラート送信
            dummy_uid = new_exists_count  # UIDをEXISTS数と同じに設定
            
            logging.info(f"🧪 Generating dummy UID: {dummy_uid}")
            
            # ダミーメール情報を作成
            dummy_email = {
                'uid': dummy_uid,
                'from': 'test@example.com',
                'subject': f'Test Message {dummy_uid}',
                'body': f'This is a test message with UID {dummy_uid}',
                'date': time.strftime("%Y-%m-%d %H:%M:%S"),
                'message_id': f'<test-{dummy_uid}@example.com>'
            }
            
            logging.info(f"📧 Emitting alert_email event for UID {dummy_uid}")
            self.emit('alert_email', dummy_email, dummy_uid)
            
            # EXISTS数を更新
            self.last_exists_count = new_exists_count
            logging.info(f"📊 Updated last_exists_count to: {self.last_exists_count}")
            
        # 10秒後に次のシミュレーションを実行
        asyncio.create_task(self._schedule_next_simulation())
    
    async def _schedule_next_simulation(self):
        """次のシミュレーションをスケジュール"""
        await asyncio.sleep(10)
        if self.is_connected:
            self._simulate_idle_notification()
    
    def stop(self):
        """サービス停止"""
        logging.info("🧪 Stopping simplified IMAP service")
        self.is_connected = False
        self.emit('stopped')
    
    def get_status(self):
        """ステータス取得"""
        return {
            'connected': self.is_connected,
            'idling': True,
            'reconnect_attempts': 0,
            'last_activity': time.time(),
            'processed_count': len(self.processed_uids),
            'last_exists_count': self.last_exists_count
        }

async def main():
    """メイン関数"""
    try:
        monitor = SimpleTestMonitor()
        success = await monitor.start_simple_test()
        
        if not success:
            logging.error("Failed to start simple test")
            sys.exit(1)
    
    except KeyboardInterrupt:
        logging.info("Simple test stopped by user")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())