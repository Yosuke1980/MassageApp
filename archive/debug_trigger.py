#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gmail IMAP IDLE Debug Trigger
手動でメッセージ処理をトリガーするデバッグツール
"""
import asyncio
import logging
import signal
import sys
import os
from datetime import datetime

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gmail_idle_to_mqtt_improved import GmailToMqttMonitor

# ログレベルをDEBUGに設定
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

class DebugMonitor(GmailToMqttMonitor):
    """デバッグ用の拡張モニタークラス"""
    
    def __init__(self):
        super().__init__()
        self.debug_mode = True
    
    async def start_debug_mode(self):
        """デバッグモードで開始"""
        try:
            logging.info("🐛 === Gmail IMAP IDLE Debug Mode ===")
            logging.info("📋 Available commands:")
            logging.info("  - Press 'p' + Enter: Process new messages manually")
            logging.info("  - Press 's' + Enter: Show status")
            logging.info("  - Press 'r' + Enter: Show processed UIDs")
            logging.info("  - Press 'q' + Enter: Quit")
            logging.info("-" * 50)
            
            # Test connections first
            if not await self._test_connections():
                logging.error("Connection tests failed. Exiting.")
                return False
            
            # Initialize IMAP service
            from gmail_imap_service import ImapIdleService
            self.imap_service = ImapIdleService(self.config)
            self._setup_imap_service_events()
            
            # Add debug event handlers
            self.imap_service.on('alert_email', self._debug_alert_handler)
            
            # Start IMAP monitoring
            await self.imap_service.start()
            
            self.is_running = True
            logging.info("✅ Debug mode started successfully")
            
            # Debug command loop
            await self._debug_command_loop()
            
            return True
            
        except Exception as e:
            logging.error(f"Failed to start debug mode: {e}")
            import traceback
            logging.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    def _debug_alert_handler(self, parsed_email, uid):
        """デバッグ用のアラートハンドラー"""
        logging.info(f"🐛 DEBUG: Alert handler called for UID {uid}")
        logging.info(f"📧 Subject: {parsed_email.get('subject', 'N/A')}")
        logging.info(f"👤 From: {parsed_email.get('from', 'N/A')}")
        logging.info(f"📅 Date: {parsed_email.get('date', 'N/A')}")
        logging.info(f"📝 Body preview: {parsed_email.get('body', 'N/A')[:100]}...")
        
        # Call the original handler
        self._on_alert_email(parsed_email, uid)
    
    async def _debug_command_loop(self):
        """デバッグコマンドループ"""
        import sys
        import select
        
        while self.is_running:
            try:
                logging.info("\n💻 Enter command (p/s/r/q): ")
                
                # Wait for user input (non-blocking on Unix systems)
                if sys.stdin in select.select([sys.stdin], [], [], 1)[0]:
                    command = sys.stdin.readline().strip().lower()
                    
                    if command == 'p':
                        await self._debug_process_messages()
                    elif command == 's':
                        self._debug_show_status()
                    elif command == 'r':
                        self._debug_show_processed_uids()
                    elif command == 'q':
                        logging.info("👋 Quitting debug mode...")
                        break
                    else:
                        logging.info("❓ Unknown command. Use p/s/r/q")
                
                await asyncio.sleep(0.1)
                
            except KeyboardInterrupt:
                logging.info("\n👋 Debug mode interrupted by user")
                break
            except Exception as e:
                logging.error(f"Error in command loop: {e}")
    
    async def _debug_process_messages(self):
        """手動でメッセージ処理を実行"""
        logging.info("🔄 Manual message processing triggered...")
        
        if not self.imap_service or not self.imap_service.is_connected:
            logging.error("❌ IMAP service not connected")
            return
        
        try:
            # Get current processed UIDs count
            before_count = len(self.imap_service.processed_uids)
            
            # Force process new messages
            self.imap_service._process_new_messages()
            
            # Check results
            after_count = len(self.imap_service.processed_uids)
            new_processed = after_count - before_count
            
            logging.info(f"✅ Manual processing complete: {new_processed} new messages processed")
            
        except Exception as e:
            logging.error(f"❌ Error in manual processing: {e}")
    
    def _debug_show_status(self):
        """ステータス情報を表示"""
        logging.info("📊 === Current Status ===")
        
        if self.imap_service:
            status = self.imap_service.get_status()
            logging.info(f"🔌 IMAP Connected: {status['connected']}")
            logging.info(f"💤 IMAP Idling: {status['idling']}")
            logging.info(f"🔄 Reconnect attempts: {status['reconnect_attempts']}")
            logging.info(f"⏰ Last activity: {datetime.fromtimestamp(status['last_activity'])}")
            logging.info(f"📧 Processed count: {status['processed_count']}")
        
        logging.info(f"📊 Stats - Processed: {self.stats['emails_processed']}, Sent: {self.stats['alerts_sent']}, Errors: {self.stats['errors']}")
        
        uptime = time.time() - self.stats['start_time']
        logging.info(f"⏱️ Uptime: {uptime:.0f} seconds")
    
    def _debug_show_processed_uids(self):
        """処理済みUID一覧を表示"""
        if not self.imap_service:
            logging.info("❌ IMAP service not available")
            return
        
        processed_uids = self.imap_service.processed_uids
        logging.info(f"📋 === Processed UIDs ({len(processed_uids)}) ===")
        
        if not processed_uids:
            logging.info("📝 No UIDs processed yet")
            return
        
        # Show last 20 UIDs
        sorted_uids = sorted(list(processed_uids))
        if len(sorted_uids) <= 20:
            logging.info(f"📝 All UIDs: {sorted_uids}")
        else:
            logging.info(f"📝 Last 20 UIDs: {sorted_uids[-20:]}")
            logging.info(f"📝 (... and {len(sorted_uids) - 20} more)")

async def main():
    """メイン関数"""
    import time
    
    try:
        # Handle Ctrl+C gracefully  
        def signal_handler(signum, frame):
            logging.info(f"\n👋 Received signal {signum}, exiting...")
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        monitor = DebugMonitor()
        success = await monitor.start_debug_mode()
        
        if not success:
            logging.error("Failed to start debug monitor")
            sys.exit(1)
    
    except KeyboardInterrupt:
        logging.info("Stopped by user")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)

if __name__ == "__main__":
    import time
    asyncio.run(main())