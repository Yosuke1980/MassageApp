#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gmail IMAP IDLE Monitor - Test Mode Runner
全てのメールを通すテストモードで実行
"""
import asyncio
import logging
from gmail_idle_to_mqtt_improved import GmailToMqttMonitor

# ログレベルをDEBUGに設定
logging.getLogger().setLevel(logging.DEBUG)

async def main():
    """Test mode runner"""
    print("🧪 Gmail IMAP IDLE Monitor - TEST MODE")
    print("📧 All emails will be processed and sent to MQTT")
    print("⏹️  Press Ctrl+C to stop")
    print("-" * 50)
    
    monitor = GmailToMqttMonitor()
    await monitor.start()

if __name__ == "__main__":
    asyncio.run(main())