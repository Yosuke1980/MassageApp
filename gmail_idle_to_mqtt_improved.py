#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gmail IMAP IDLE to MQTT Monitor (Improved Version)
Features:
- Robust IMAP IDLE monitoring with EventEmitter architecture
- Exponential backoff reconnection
- Duplicate message processing prevention
- Periodic IDLE refresh for Gmail limitations
- Enhanced error handling and logging
"""
import os
import ssl
import time
import json
import logging
import asyncio
import signal
import sys
from typing import Dict, Any
from dotenv import load_dotenv
import paho.mqtt.client as mqtt

# Import the new IMAP service
from gmail_imap_service import ImapIdleService

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

class GmailToMqttMonitor:
    """Main monitor class integrating IMAP IDLE service with MQTT publishing"""
    
    def __init__(self):
        self.config = self._load_config()
        self.imap_service = None
        self.is_running = False
        self.stats = {
            'emails_processed': 0,
            'alerts_sent': 0,
            'errors': 0,
            'last_activity': None,
            'start_time': time.time()
        }
        
        # Setup graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from environment variables"""
        # Load .env file
        base_dir = os.path.dirname(os.path.abspath(__file__))
        load_dotenv(dotenv_path=os.path.join(base_dir, ".env"))
        
        # Validate required environment variables
        required_vars = ['GMAIL_USER', 'GMAIL_PASS', 'MQTT_HOST', 'MQTT_USER', 'MQTT_PASS']
        missing_vars = [var for var in required_vars if not os.environ.get(var)]
        
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
        
        return {
            # IMAP Configuration
            'user': os.environ['GMAIL_USER'],
            'password': os.environ['GMAIL_PASS'],
            'host': 'imap.gmail.com',
            'port': 993,
            'inbox_folder': os.environ.get('IMAP_FOLDER', 'INBOX'),
            'idle_timeout': int(os.environ.get('IDLE_TIMEOUT', '300')),  # 5 minutes
            'max_reconnect_attempts': 10,
            'reconnect_delay': 5000,  # milliseconds
            'reconnect_backoff_multiplier': 1.5,
            
            # Search Keywords
            'search_keywords': os.environ.get('SEARCH_KEYWORDS', '地震情報,津波情報').split(','),
            'from_domains': os.environ.get('FROM_DOMAINS', 'bosai-jma@jmainfo.go.jp').split(','),
            
            # MQTT Configuration
            'mqtt': {
                'host': os.environ['MQTT_HOST'],
                'port': int(os.environ.get('MQTT_PORT', '8883')),
                'tls': os.environ.get('MQTT_TLS', 'true').lower() == 'true',
                'user': os.environ['MQTT_USER'],
                'password': os.environ['MQTT_PASS'],
                'topic': os.environ.get('MQTT_TOPIC', 'inbox/matches'),
                'keepalive': 60
            },
            
            # Processing Configuration
            'fetch_body_limit': int(os.environ.get('FETCH_BODY_LIMIT', '4000')),
            'poll_on_wake': os.environ.get('POLL_ON_WAKE', 'False').lower() == 'true'
        }
    
    async def start(self):
        """Start the monitoring service"""
        try:
            logging.info("=== Gmail to MQTT Monitor Starting ===")
            logging.info(f"Monitoring folder: {self.config['inbox_folder']}")
            logging.info(f"Search keywords: {', '.join(self.config['search_keywords'])}")
            logging.info(f"MQTT topic: {self.config['mqtt']['topic']}")
            
            # Test connections first
            if not await self._test_connections():
                logging.error("Connection tests failed. Exiting.")
                return False
            
            # Initialize IMAP service
            self.imap_service = ImapIdleService(self.config)
            self._setup_imap_service_events()
            
            # Start IMAP monitoring
            await self.imap_service.start()
            
            self.is_running = True
            logging.info("=== Gmail to MQTT Monitor Started Successfully ===")
            
            # Keep the service running
            while self.is_running:
                await asyncio.sleep(1)
            
            return True
            
        except Exception as e:
            logging.error(f"Failed to start monitor: {e}")
            return False
    
    def _setup_imap_service_events(self):
        """Setup event handlers for IMAP service"""
        
        # Connection events
        self.imap_service.on('connected', self._on_imap_connected)
        self.imap_service.on('disconnected', self._on_imap_disconnected)
        self.imap_service.on('error', self._on_imap_error)
        self.imap_service.on('max_reconnects_reached', self._on_max_reconnects_reached)
        
        # Message events
        self.imap_service.on('alert_email', self._on_alert_email)
        self.imap_service.on('idle_started', self._on_idle_started)
    
    def _on_imap_connected(self):
        """Handle IMAP connection established"""
        logging.info("✓ IMAP service connected")
    
    def _on_imap_disconnected(self):
        """Handle IMAP disconnection"""
        logging.warning("⚠️ IMAP service disconnected")
    
    def _on_imap_error(self, error):
        """Handle IMAP service errors"""
        logging.error(f"❌ IMAP service error: {error}")
        self.stats['errors'] += 1
    
    def _on_max_reconnects_reached(self):
        """Handle max reconnection attempts reached"""
        logging.error("💥 Max IMAP reconnection attempts reached. Service may need restart.")
    
    def _on_idle_started(self):
        """Handle IDLE monitoring started"""
        logging.debug("📡 IMAP IDLE monitoring started")
    
    def _on_alert_email(self, parsed_email, uid):
        """Handle alert email received"""
        try:
            logging.info(f"🚨 Processing alert email UID {uid}: {parsed_email['subject']}")
            self.stats['emails_processed'] += 1
            self.stats['last_activity'] = time.time()
            
            # Check if message matches criteria
            logging.debug(f"🔍 Checking message criteria for UID {uid}")
            if self._message_matches(parsed_email):
                logging.info(f"✅ Message UID {uid} matches criteria, creating MQTT payload")
                
                # Create MQTT payload
                payload = self._create_mqtt_payload(parsed_email, uid)
                logging.debug(f"📦 MQTT payload created for UID {uid}: {json.dumps(payload, ensure_ascii=False)[:200]}...")
                
                # Publish to MQTT
                logging.info(f"📤 Publishing to MQTT for UID {uid}")
                if self._mqtt_publish(payload):
                    self.stats['alerts_sent'] += 1
                    logging.info(f"✅ Alert published successfully: {parsed_email['subject'][:80]}")
                else:
                    logging.error(f"❌ Failed to publish alert: {parsed_email['subject'][:80]}")
                    self.stats['errors'] += 1
            else:
                logging.info(f"🚫 Message filtered out: {parsed_email['subject'][:80]}")
        
        except Exception as e:
            logging.error(f"❌ Error processing alert email: {e}")
            import traceback
            logging.error(f"📄 Traceback: {traceback.format_exc()}")
            self.stats['errors'] += 1
    
    def _message_matches(self, parsed_email) -> bool:
        """Check if message matches filtering criteria - TEST MODE: All messages pass"""
        subject = parsed_email.get('subject', '').lower()
        from_addr = parsed_email.get('from', '').lower()
        
        # TEST MODE: Accept all messages
        logging.info(f"TEST MODE: All messages accepted - Subject: {subject[:50]}, From: {from_addr[:50]}")
        return True
    
    def _create_mqtt_payload(self, parsed_email, uid) -> dict:
        """Create MQTT payload from email data"""
        body = parsed_email.get('body', '')
        body_limit = self.config['fetch_body_limit']
        
        return {
            "uid": int(uid),
            "message_id": parsed_email.get('message_id', '').strip(),
            "date": parsed_email.get('date', ''),
            "from": parsed_email.get('from', ''),
            "subject": parsed_email.get('subject', ''),
            "body": body[:body_limit] if body else '',
            "timestamp": time.time(),
            "processed_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
    
    def _mqtt_publish(self, payload: dict) -> bool:
        """Publish message to MQTT with retry logic"""
        max_retries = 3
        retry_delay = 2
        
        logging.info(f"🔌 Starting MQTT publish - Host: {self.config['mqtt']['host']}, Topic: {self.config['mqtt']['topic']}")
        
        for attempt in range(max_retries):
            try:
                logging.debug(f"🤝 Creating MQTT client (attempt {attempt + 1})")
                client = mqtt.Client()
                client.username_pw_set(
                    self.config['mqtt']['user'], 
                    self.config['mqtt']['password']
                )
                if self.config['mqtt']['tls']:
                    client.tls_set()
                
                logging.info(f"📤 MQTT publish attempt {attempt + 1}/{max_retries}")
                logging.debug(f"🔗 Connecting to MQTT broker: {self.config['mqtt']['host']}:{self.config['mqtt']['port']}")
                
                client.connect(
                    self.config['mqtt']['host'], 
                    self.config['mqtt']['port'], 
                    keepalive=self.config['mqtt']['keepalive']
                )
                
                logging.debug(f"📝 Publishing payload size: {len(json.dumps(payload, ensure_ascii=False))} bytes")
                result = client.publish(
                    self.config['mqtt']['topic'],
                    json.dumps(payload, ensure_ascii=False),
                    qos=1
                )
                
                logging.debug(f"✂️ Disconnecting from MQTT broker")
                client.disconnect()
                
                if result.rc == mqtt.MQTT_ERR_SUCCESS:
                    logging.info(f"✅ MQTT published successfully - Message ID: {result.mid}")
                    return True
                else:
                    logging.warning(f"⚠️ MQTT publish returned code: {result.rc} (Message ID: {result.mid})")
            
            except Exception as e:
                logging.error(f"❌ MQTT publish failed (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    logging.info(f"⏱️ Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
        
        logging.error("💥 All MQTT publish attempts failed")
        return False
    
    async def _test_connections(self) -> bool:
        """Test MQTT and IMAP connections"""
        logging.info("Running connectivity tests...")
        
        # Test MQTT connection
        mqtt_ok = self._test_mqtt_connection()
        
        # Test IMAP connection
        imap_ok = self._test_imap_connection()
        
        if not mqtt_ok or not imap_ok:
            logging.error("Some connectivity tests failed.")
            return False
        
        logging.info("All connectivity tests passed ✓")
        return True
    
    def _test_mqtt_connection(self) -> bool:
        """Test MQTT connection"""
        try:
            logging.info("Testing MQTT connection...")
            client = mqtt.Client()
            client.username_pw_set(
                self.config['mqtt']['user'], 
                self.config['mqtt']['password']
            )
            if self.config['mqtt']['tls']:
                client.tls_set()
            client.connect(
                self.config['mqtt']['host'], 
                self.config['mqtt']['port'], 
                keepalive=10
            )
            client.disconnect()
            logging.info("✓ MQTT connection successful")
            return True
        except Exception as e:
            logging.error(f"✗ MQTT connection failed: {e}")
            return False
    
    def _test_imap_connection(self) -> bool:
        """Test IMAP connection"""
        try:
            logging.info("Testing IMAP connection...")
            from imapclient import IMAPClient
            
            context = ssl.create_default_context()
            with IMAPClient(
                self.config['host'], 
                port=self.config['port'], 
                ssl=True, 
                ssl_context=context
            ) as conn:
                conn.login(self.config['user'], self.config['password'])
                logging.info("✓ IMAP connection and authentication successful")
                return True
        except Exception as e:
            logging.error(f"✗ IMAP connection failed: {e}")
            return False
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logging.info(f"Received signal {signum}, shutting down gracefully...")
        _ = frame  # Suppress unused parameter warning
        self.is_running = False
        
        if self.imap_service:
            self.imap_service.stop()
        
        # Print statistics
        uptime = time.time() - self.stats['start_time']
        logging.info(f"=== Final Statistics ===")
        logging.info(f"Uptime: {uptime:.0f} seconds")
        logging.info(f"Emails processed: {self.stats['emails_processed']}")
        logging.info(f"Alerts sent: {self.stats['alerts_sent']}")
        logging.info(f"Errors: {self.stats['errors']}")
        
        sys.exit(0)
    
    def stop(self):
        """Stop the monitor"""
        logging.info("Stopping Gmail to MQTT monitor...")
        self.is_running = False
        
        if self.imap_service:
            self.imap_service.stop()

async def main():
    """Main entry point"""
    try:
        monitor = GmailToMqttMonitor()
        success = await monitor.start()
        
        if not success:
            logging.error("Failed to start monitor")
            sys.exit(1)
    
    except KeyboardInterrupt:
        logging.info("Stopped by user")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Fix asyncio issue with reconnection
    import asyncio
    
    # Add asyncio import to the ImapIdleService
    if 'asyncio' not in sys.modules:
        import asyncio
    
    asyncio.run(main())