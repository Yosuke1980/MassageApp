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
from ssl import CERT_REQUIRED
import time
import json
import logging
import asyncio
import signal
import sys
import subprocess
import threading
from typing import Dict, Any
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
from dotenv import load_dotenv
import paho.mqtt.client as mqtt
try:
    import tkinter as tk
    from tkinter import ttk, messagebox
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False

# IMAP client and email processing
from imapclient import IMAPClient
import email
import email.message
import socket
from email.header import decode_header, make_header
import backoff
from typing import Set, Callable, Optional

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

class EventEmitter:
    """Simple EventEmitter implementation for Python"""
    def __init__(self):
        self._listeners: Dict[str, list] = {}
    
    def on(self, event: str, callback: Callable):
        """Register event listener"""
        if event not in self._listeners:
            self._listeners[event] = []
        self._listeners[event].append(callback)
    
    def emit(self, event: str, *args, **kwargs):
        """Emit event to all listeners"""
        if event in self._listeners:
            for callback in self._listeners[event]:
                try:
                    callback(*args, **kwargs)
                except Exception as e:
                    logging.error(f"Error in event listener for '{event}': {e}")

class ImapIdleService(EventEmitter):
    """Gmail IMAP IDLE monitoring service with robust reconnection and duplicate prevention"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__()
        self.config = config
        self.imap: Optional[IMAPClient] = None
        self.is_connected = False
        self.is_idling = False
        self.reconnect_attempts = 0
        self.reconnect_timer = None
        self.last_activity = time.time()
        self.processed_uids: Set[int] = set()  # 重複処理防止
        self.idle_thread = None
        self.should_stop = False
        self.last_exists_count = 0  # フォルダのEXISTS数を追跡
        
        # Statistics tracking
        self.stats = {
            'start_time': time.time(),
            'emails_received': 0,
            'emails_processed': 0,
            'emails_filtered': 0,
            'idle_notifications': 0,
            'last_idle_notification': None,
            'last_email_processed': None,
            'processing_times': [],
            'filter_matches': {
                'keyword': 0,
                'domain': 0,
                'both': 0
            }
        }
        
        # Status reporting
        self.status_thread = None
        self.status_report_interval = 300  # 5 minutes
        
        # Configuration defaults
        self.max_reconnect_attempts = config.get('max_reconnect_attempts', 10)
        self.reconnect_delay = config.get('reconnect_delay', 5000) / 1000.0  # Convert to seconds
        self.reconnect_backoff_multiplier = config.get('reconnect_backoff_multiplier', 1.5)
        self.idle_timeout = config.get('idle_timeout', 300)  # 5 minutes
        self.inbox_folder = config.get('inbox_folder', 'INBOX')
        
        logging.info("ImapIdleService initialized")
    
    async def start(self):
        """Start IMAP IDLE monitoring service"""
        logging.info("Starting IMAP IDLE monitoring service")
        
        if not self.config.get('user') or not self.config.get('password'):
            raise Exception("Gmail credentials not configured. Please set GMAIL_USER and GMAIL_APP_PASSWORD in environment variables.")
        
        await self._connect()
    
    async def _connect(self):
        """Establish IMAP connection"""
        try:
            logging.info("Connecting to IMAP server...")
            
            # Create SSL context
            context = ssl.create_default_context()
            
            # Initialize IMAP client
            self.imap = IMAPClient(
                host=self.config.get('host', 'imap.gmail.com'),
                port=self.config.get('port', 993),
                ssl=True,
                ssl_context=context
            )
            
            # Login
            self.imap.login(self.config['user'], self.config['password'])
            
            logging.info("✓ IMAP connection established")
            self.is_connected = True
            self.reconnect_attempts = 0
            self.last_activity = time.time()
            self.emit('connected')
            
            # Open inbox and start IDLE
            self._open_inbox_and_start_idle()
            
            # Start status reporting thread
            self._start_status_reporting()
            
        except Exception as e:
            logging.error(f"IMAP connection error: {e}")
            self.is_connected = False
            self.emit('error', e)
            
            if self.reconnect_attempts == 0:
                raise e
            
            self._schedule_reconnect()
    
    def _open_inbox_and_start_idle(self):
        """Open INBOX and start IDLE monitoring"""
        try:
            # Select folder
            select_info = self.imap.select_folder(self.inbox_folder, readonly=False)
            exists_count = int(select_info[b'EXISTS'])
            
            # Set startup baselines - only process emails received AFTER startup
            self.startup_exists_count = exists_count
            self.last_exists_count = exists_count
            
            # Get the highest UID at startup as baseline
            if exists_count > 0:
                try:
                    # Get the highest UID in the mailbox at startup
                    all_uids = self.imap.search(['ALL'])
                    if all_uids:
                        self.startup_max_uid = max(all_uids)
                        self.last_processed_uid = self.startup_max_uid
                        logging.info(f"📊 Startup baseline: {exists_count} messages, max UID: {self.startup_max_uid}")
                    else:
                        self.startup_max_uid = 0
                        self.last_processed_uid = 0
                        logging.info("📊 Startup baseline: mailbox is empty")
                except Exception as uid_error:
                    logging.warning(f"⚠️ Could not get startup max UID: {uid_error}")
                    self.startup_max_uid = 0
                    self.last_processed_uid = 0
            else:
                self.startup_max_uid = 0
                self.last_processed_uid = 0
                logging.info("📊 Startup baseline: mailbox is empty")
            
            logging.info(f"🚀 Opened {self.inbox_folder} - ONLY processing new emails received after startup")
            logging.info(f"📊 Startup EXISTS count: {self.startup_exists_count}, Startup max UID: {self.startup_max_uid}")
            logging.debug(f"📊 Initial tracking - EXISTS: {self.last_exists_count}, last_processed_uid: {self.last_processed_uid}")
            
            # Start IDLE in separate thread
            self._start_idle()
            
        except Exception as e:
            logging.error(f"Failed to open INBOX: {e}")
            self.emit('error', e)
    
    def _start_idle(self):
        """Start IDLE monitoring in separate thread"""
        if self.is_idling or not self.is_connected:
            return
        
        def idle_worker():
            try:
                logging.info("IDLE started - waiting for new messages")
                self.is_idling = True
                self.emit('idle_started')
                
                # Start IDLE
                self.imap.idle()
                
                # Monitor for changes
                while self.is_idling and self.is_connected and not self.should_stop:
                    try:
                        # Check for IDLE responses with timeout
                        responses = self.imap.idle_check(timeout=30)  # 30 second timeout
                        
                        if responses:
                            self.stats['idle_notifications'] += 1
                            self.stats['last_idle_notification'] = time.time()
                            
                            logging.info(f"🔔 IDLE notification #{self.stats['idle_notifications']} received: {responses}")
                            logging.info(f"🔔 Response details: {[str(r) for r in responses]}")
                            self.last_activity = time.time()
                            
                            # Parse EXISTS information from IDLE notification
                            new_exists_count = self._parse_exists_from_idle(responses)
                            if new_exists_count and new_exists_count > self.last_exists_count:
                                # Only process if new messages arrived AFTER startup
                                if new_exists_count > self.startup_exists_count:
                                    logging.info(f"🔍 New messages detected: EXISTS {new_exists_count} (startup: {self.startup_exists_count})")
                                    logging.info("🔍 Starting to process new messages using EXISTS-based detection...")
                                else:
                                    logging.info(f"ℹ️ EXISTS count increased to {new_exists_count} but still within startup range ({self.startup_exists_count}), skipping")
                                    self.last_exists_count = new_exists_count
                                    continue
                                
                                # CRITICAL: End IDLE before fetch operations
                                logging.info("⏹️ Ending IDLE mode before message processing...")
                                try:
                                    self.imap.idle_done()
                                    self.is_idling = False
                                    logging.info("✅ IDLE mode ended successfully")
                                except Exception as idle_end_error:
                                    logging.error(f"❌ Error ending IDLE: {idle_end_error}")
                                
                                # Process messages (now safe to use fetch)
                                self._process_new_messages_by_exists(new_exists_count)
                                
                                # Restart IDLE after processing
                                logging.info("🔄 Restarting IDLE mode after message processing...")
                                try:
                                    if self.is_connected and not self.should_stop:
                                        self.imap.idle()
                                        self.is_idling = True
                                        logging.info("✅ IDLE mode restarted successfully")
                                except Exception as idle_restart_error:
                                    logging.error(f"❌ Error restarting IDLE: {idle_restart_error}")
                                    # If we can't restart IDLE, break the loop for reconnection
                                    break
                                    
                            else:
                                logging.info("ℹ️ No new messages detected from IDLE notification")
                        
                        # Refresh IDLE periodically (Gmail limitation workaround)
                        if time.time() - self.last_activity > self.idle_timeout:
                            if self.is_idling:
                                logging.debug("Refreshing IDLE connection")
                                self._refresh_idle()
                            
                    except socket.timeout:
                        # Normal timeout, continue monitoring
                        continue
                    except Exception as e:
                        logging.error(f"IDLE monitoring error: {e}")
                        break
                
                # Stop IDLE
                if self.is_idling:
                    try:
                        logging.debug("⏹️ Stopping IDLE in worker thread...")
                        self.imap.idle_done()
                        logging.debug("✅ IDLE stopped successfully")
                    except Exception as e:
                        logging.debug(f"⚠️ Error stopping IDLE: {e}")
                    self.is_idling = False
                
            except Exception as e:
                logging.error(f"IDLE worker error: {e}")
                self.is_idling = False
                self.emit('error', e)
        
        # Start IDLE in separate thread
        self.idle_thread = threading.Thread(target=idle_worker, daemon=True)
        self.idle_thread.start()
        
        # Schedule IDLE refresh
        self._schedule_idle_refresh()
    
    def _refresh_idle(self):
        """Refresh IDLE connection (Gmail limitation workaround)"""
        if not self.is_connected or not self.is_idling:
            return
        
        try:
            logging.debug("🔄 Refreshing IDLE connection...")
            # End current IDLE
            self.imap.idle_done()
            self.is_idling = False
            time.sleep(1)  # Brief pause
            
            # Restart IDLE
            if self.is_connected and not self.should_stop:
                self.imap.idle()
                self.is_idling = True
                self.last_activity = time.time()
                logging.debug("✅ IDLE connection refreshed successfully")
            
        except Exception as e:
            logging.error(f"❌ Failed to refresh IDLE: {e}")
            self.is_idling = False
            self._schedule_reconnect()
    
    def _schedule_idle_refresh(self):
        """Schedule periodic IDLE refresh"""
        def refresh_timer():
            if self.is_idling and self.is_connected and not self.should_stop:
                time.sleep(self.idle_timeout)
                if self.is_idling and self.is_connected:
                    logging.debug("Scheduled IDLE refresh")
                    self._refresh_idle()
                    # Schedule next refresh
                    self._schedule_idle_refresh()
        
        refresh_thread = threading.Thread(target=refresh_timer, daemon=True)
        refresh_thread.start()
    
    def _start_status_reporting(self):
        """Start periodic status reporting thread"""
        def status_reporter():
            while self.is_connected and not self.should_stop:
                try:
                    time.sleep(self.status_report_interval)
                    if self.is_connected and not self.should_stop:
                        self._report_status()
                except Exception as e:
                    logging.error(f"Status reporting error: {e}")
                    break
        
        self.status_thread = threading.Thread(target=status_reporter, daemon=True)
        self.status_thread.start()
        logging.debug(f"📊 Status reporting thread started (interval: {self.status_report_interval}s)")
    
    def _report_status(self):
        """Generate detailed status report"""
        uptime = time.time() - self.stats['start_time']
        uptime_str = f"{uptime/3600:.1f}h" if uptime > 3600 else f"{uptime/60:.1f}m"
        
        idle_duration = time.time() - (self.stats['last_idle_notification'] or self.stats['start_time'])
        idle_str = f"{idle_duration/60:.1f}m" if idle_duration > 60 else f"{idle_duration:.0f}s"
        
        # Calculate averages
        avg_processing_time = 0
        if self.stats['processing_times']:
            avg_processing_time = sum(self.stats['processing_times']) / len(self.stats['processing_times'])
        
        filter_rate = 0
        if self.stats['emails_received'] > 0:
            filter_rate = (self.stats['emails_filtered'] / self.stats['emails_received']) * 100
        
        logging.info("📊 === IMAP IDLE Status Report ===")
        logging.info(f"📊 Uptime: {uptime_str} | IDLE: {'Active' if self.is_idling else 'Inactive'} | Last activity: {idle_str} ago")
        logging.info(f"📊 Mailbox: {self.inbox_folder} ({self.last_exists_count} messages)")
        logging.info(f"📊 Received: {self.stats['emails_received']} | Processed: {self.stats['emails_processed']} | Filtered: {self.stats['emails_filtered']} ({filter_rate:.1f}%)")
        logging.info(f"📊 IDLE notifications: {self.stats['idle_notifications']} | Avg processing: {avg_processing_time:.2f}s")
        logging.info(f"📊 Filter matches - Keywords: {self.stats['filter_matches']['keyword']} | Domains: {self.stats['filter_matches']['domain']} | Both: {self.stats['filter_matches']['both']}")
        logging.info(f"📊 Processed UIDs: {len(self.processed_uids)} | Reconnections: {self.reconnect_attempts}")
        logging.info("📊 ==============================")
    
    def _parse_exists_from_idle(self, responses) -> Optional[int]:
        """Parse EXISTS count from IDLE notification responses"""
        try:
            exists_count = None
            # Find the LAST EXISTS value in responses (in case there are multiple)
            for response in responses:
                if isinstance(response, tuple) and len(response) >= 2:
                    # Looking for (count, b'EXISTS') pattern
                    if response[1] == b'EXISTS':
                        exists_count = int(response[0])
                        logging.debug(f"📊 Found EXISTS count in IDLE response: {exists_count}")
            
            if exists_count is not None:
                logging.debug(f"📊 Final parsed EXISTS count from IDLE: {exists_count}")
                return exists_count
            else:
                logging.debug(f"ℹ️ No EXISTS information found in IDLE responses: {responses}")
                return None
            
        except Exception as e:
            logging.error(f"❌ Error parsing EXISTS from IDLE responses: {e}")
            return None
    
    def _process_new_messages_by_exists(self, new_exists_count: int):
        """Process new messages based on EXISTS count change"""
        if not self.is_connected:
            logging.warning("⚠️ Not connected to IMAP server")
            return
        
        try:
            logging.info(f"📊 EXISTS count change: {self.last_exists_count} → {new_exists_count}")
            logging.info(f"📊 Startup baseline: {self.startup_exists_count}")
            
            if new_exists_count <= self.last_exists_count:
                logging.info("ℹ️ No new messages (EXISTS count did not increase)")
                return
            
            # Only process messages that are truly new (arrived after startup)
            if new_exists_count <= self.startup_exists_count:
                logging.info(f"ℹ️ EXISTS count {new_exists_count} is within startup baseline ({self.startup_exists_count}), skipping")
                self.last_exists_count = new_exists_count
                return
            
            # Calculate new UID range
            # Note: UID might not be sequential with EXISTS count, so we'll fetch recent messages
            new_message_count = new_exists_count - self.last_exists_count
            logging.info(f"🔢 Detected {new_message_count} new message(s) (all post-startup)")
            
            # Get UIDs of recent messages (safer approach)
            # Search for messages in the recent range based on sequence numbers
            try:
                # Get UIDs for the new sequence numbers
                start_seqno = self.last_exists_count + 1
                end_seqno = new_exists_count
                
                logging.info(f"🔍 Preparing to fetch UIDs for sequence numbers {start_seqno}:{end_seqno}")
                
                # Use sequence number to UID mapping
                seqno_range = f"{start_seqno}:{end_seqno}" if start_seqno != end_seqno else str(start_seqno)
                logging.info(f"📋 Using sequence range: '{seqno_range}'")
                
                # Check IMAP connection before fetch
                logging.debug(f"🔧 IMAP connection status: connected={self.is_connected}")
                if not self.imap:
                    raise Exception("IMAP client is None")
                
                logging.info(f"⬇️ Starting IMAP fetch for range '{seqno_range}' with ['UID']...")
                uid_mapping = self.imap.fetch(seqno_range, ['UID'])
                logging.info(f"✅ IMAP fetch completed successfully. Result type: {type(uid_mapping)}, length: {len(uid_mapping) if uid_mapping else 'None'}")
                
                if uid_mapping:
                    logging.debug(f"🔍 UID mapping keys: {list(uid_mapping.keys())}")
                    for key in list(uid_mapping.keys())[:3]:  # Show first 3 entries
                        logging.debug(f"🔍 UID mapping[{key}]: {uid_mapping[key]}")
                else:
                    logging.warning("⚠️ UID mapping returned empty or None")
                
                logging.info("🔍 Extracting UIDs from fetch results...")
                new_uids = []
                
                if uid_mapping:
                    for seqno, data in uid_mapping.items():
                        logging.debug(f"🔍 Processing seqno {seqno}, data type: {type(data)}")
                        if isinstance(data, dict) and b'UID' in data:
                            uid = data[b'UID']
                            new_uids.append(uid)
                            logging.debug(f"✅ Extracted UID {uid} from seqno {seqno}")
                        else:
                            logging.debug(f"⚠️ No UID found in data for seqno {seqno}: {data}")
                
                logging.info(f"📋 New UIDs to process: {new_uids}")
                
                if not new_uids:
                    logging.warning("⚠️ No UIDs extracted from fetch results")
                    # Try alternative approach
                    logging.info("🔄 Attempting alternative UID detection...")
                    self._process_new_messages_fallback()
                    return
                
                # Process each new message
                logging.info(f"🔄 Starting to process {len(new_uids)} UIDs...")
                processed_count = 0
                
                for uid in new_uids:
                    if uid not in self.processed_uids:
                        logging.info(f"📧 Processing new message UID {uid}")
                        self._process_message(uid)
                        processed_count += 1
                        # Update UID tracking for fallback method
                        if not hasattr(self, 'last_processed_uid'):
                            self.last_processed_uid = 0
                        if uid > self.last_processed_uid:
                            self.last_processed_uid = uid
                    else:
                        logging.debug(f"⏭️ UID {uid} already processed")
                        # Still update UID tracking even for already processed messages
                        if not hasattr(self, 'last_processed_uid'):
                            self.last_processed_uid = 0
                        if uid > self.last_processed_uid:
                            self.last_processed_uid = uid
                
                logging.info(f"✅ Successfully processed {processed_count} new messages")
                
                # Update EXISTS count
                self.last_exists_count = new_exists_count
                logging.debug(f"📊 Updated last_exists_count to: {self.last_exists_count}")
                logging.debug(f"📊 Updated last_processed_uid to: {getattr(self, 'last_processed_uid', 0)}")
                
            except Exception as fetch_error:
                logging.error(f"❌ CRITICAL: Error fetching new message UIDs: {fetch_error}")
                import traceback
                logging.error(f"📄 Fetch error traceback: {traceback.format_exc()}")
                
                # Log the attempted operation for debugging
                logging.error(f"🔧 Failed operation details:")
                logging.error(f"   - start_seqno: {start_seqno}")
                logging.error(f"   - end_seqno: {end_seqno}")
                logging.error(f"   - seqno_range: '{seqno_range}'")
                logging.error(f"   - IMAP connected: {self.is_connected}")
                logging.error(f"   - IMAP client exists: {self.imap is not None}")
                
                # Fallback: try to get all recent messages
                logging.info("🔄 Attempting fallback: searching recent messages")
                self._process_new_messages_fallback()
        
        except Exception as e:
            logging.error(f"❌ Error processing new messages by EXISTS: {e}")
            import traceback
            logging.error(f"📄 Traceback: {traceback.format_exc()}")
    
    def _process_new_messages_fallback(self):
        """Fallback method: process messages using UID-based tracking"""
        logging.info("🔄 Fallback: Using UID-based message detection")
        logging.info("ℹ️ Note: UNSEEN search would return 0 during IDLE monitoring since messages are already marked as seen")
        self._process_new_messages_by_uid()
    
    def _process_new_messages_by_uid(self):
        """Process new messages using UID-based tracking"""
        if not self.is_connected:
            logging.warning("⚠️ Not connected to IMAP server")
            return
        
        try:
            # Use startup baseline to only process post-startup emails
            if not hasattr(self, 'startup_max_uid'):
                self.startup_max_uid = 0
            if not hasattr(self, 'last_processed_uid'):
                self.last_processed_uid = self.startup_max_uid
                
            logging.info(f"🔎 Searching for messages with UID > {self.startup_max_uid} (startup baseline)")
            logging.info(f"📊 Current last_processed_uid: {self.last_processed_uid}")
            
            # Check connection before search
            if not self.imap:
                logging.error("❌ IMAP client is None")
                return
            
            try:
                # Search for messages with UID greater than startup baseline
                search_criteria = ['UID', f'{self.startup_max_uid + 1}:*']
                logging.debug(f"🔍 Executing IMAP search with criteria: {search_criteria}")
                uids = self.imap.search(search_criteria)
                logging.debug(f"🔍 IMAP search completed, type: {type(uids)}, content: {uids}")
                
            except Exception as search_error:
                logging.error(f"❌ IMAP search failed: {search_error}")
                import traceback
                logging.error(f"📄 Search error traceback: {traceback.format_exc()}")
                return
            
            # Handle search results
            if uids is None:
                logging.warning("⚠️ UID search returned None")
                return
                
            logging.info(f"📊 UID search result: {len(uids)} messages")
            if uids and len(uids) <= 10:
                logging.info(f"📋 Found UIDs: {uids}")
            elif uids:
                logging.info(f"📋 Found UIDs: {uids[:5]}... (+{len(uids)-5} more)")
            
            if not uids:
                logging.info("✅ No new post-startup messages found with UID tracking")
                return
            
            # Filter out any UIDs that are not actually post-startup (double check)
            post_startup_uids = [uid for uid in uids if uid > self.startup_max_uid]
            
            if not post_startup_uids:
                logging.info("✅ All found UIDs are pre-startup, skipping")
                return
                
            if len(post_startup_uids) < len(uids):
                skipped_pre_startup = len(uids) - len(post_startup_uids)
                logging.info(f"ℹ️ Skipped {skipped_pre_startup} pre-startup messages, processing {len(post_startup_uids)} post-startup messages")
            else:
                logging.info(f"🔄 Processing {len(post_startup_uids)} post-startup messages...")
            
            # Process each post-startup message and update last_processed_uid
            processed_count = 0
            skipped_count = 0
            
            for uid in post_startup_uids:
                if uid not in self.processed_uids:
                    logging.info(f"📧 Processing post-startup message UID {uid}")
                    self._process_message(uid)
                    processed_count += 1
                    # Update the highest UID we've processed
                    if uid > self.last_processed_uid:
                        self.last_processed_uid = uid
                else:
                    logging.debug(f"⏭️ Message UID {uid} already processed")
                    skipped_count += 1
                    # Still update last_processed_uid even for skipped messages
                    if uid > self.last_processed_uid:
                        self.last_processed_uid = uid
            
            logging.info(f"✅ Message processing complete: {processed_count} processed, {skipped_count} skipped")
        
        except Exception as e:
            logging.error(f"❌ Error processing new messages: {e}")
            import traceback
            logging.error(f"📄 Traceback: {traceback.format_exc()}")
    
    def _process_message(self, uid: int):
        """Process individual message"""
        process_start = time.time()
        try:
            logging.info(f"📝 Processing message UID {uid}")
            self.stats['emails_received'] += 1
            
            # Fetch message
            fetch_start = time.time()
            logging.debug(f"🔽 Fetching message data for UID {uid}")
            fetch_data = self.imap.fetch([uid], ['ENVELOPE', 'RFC822'])
            fetch_time = time.time() - fetch_start
            logging.debug(f"⏱️ Message fetch took {fetch_time:.3f}s")
            message_data = fetch_data.get(uid)
            
            if not message_data:
                logging.warning(f"⚠️ No data for UID {uid}")
                return
            
            logging.debug(f"✅ Message data fetched successfully for UID {uid}")
            
            # Parse email
            raw_email = message_data[b'RFC822']
            msg = email.message_from_bytes(raw_email)
            
            # Decode headers
            from_header = self._decode_mime_header(msg.get("From", ""))
            subject_header = self._decode_mime_header(msg.get("Subject", ""))
            
            # Extract body
            body = self._extract_text_body(msg)
            
            logging.info(f"📧 Parsed email UID {uid}: From={from_header[:50]}, Subject={subject_header[:50]}")
            
            # Check if this is an alert-related email
            filter_start = time.time()
            logging.debug(f"🔍 Checking if email UID {uid} is alert-related")
            filter_result = self._is_alert_related_email(from_header, subject_header, body)
            filter_time = time.time() - filter_start
            logging.debug(f"⏱️ Filter check took {filter_time:.3f}s")
            
            if filter_result:
                logging.info(f"🚨 Alert email detected UID {uid}: {subject_header}")
                self.stats['emails_processed'] += 1
                self.stats['last_email_processed'] = time.time()
                
                # Create parsed email object
                parsed_email = {
                    'uid': uid,
                    'from': from_header,
                    'subject': subject_header,
                    'body': body,
                    'date': msg.get("Date", ""),
                    'message_id': msg.get("Message-Id", "")
                }
                
                logging.info(f"📤 Emitting alert_email event for UID {uid}")
                # Emit alert event
                self.emit('alert_email', parsed_email, uid)
                
                # Mark as processed
                self.processed_uids.add(uid)
                logging.debug(f"✅ UID {uid} marked as processed (total processed: {len(self.processed_uids)})")
                
                # Mark as seen
                try:
                    seen_start = time.time()
                    self.imap.add_flags([uid], ['\\Seen'])
                    seen_time = time.time() - seen_start
                    logging.debug(f"👁️ UID {uid} marked as seen ({seen_time:.3f}s)")
                except Exception as e:
                    logging.error(f"❌ Failed to mark message {uid} as seen: {e}")
            else:
                logging.info(f"🚫 Email UID {uid} filtered out")
                self.stats['emails_filtered'] += 1
            
            # Record total processing time
            total_time = time.time() - process_start
            self.stats['processing_times'].append(total_time)
            if len(self.stats['processing_times']) > 100:  # Keep last 100 times
                self.stats['processing_times'] = self.stats['processing_times'][-100:]
            
            logging.info(f"⏱️ Message UID {uid} processing completed in {total_time:.3f}s")
        
        except Exception as e:
            logging.error(f"❌ Failed to process message UID {uid}: {e}")
            import traceback
            logging.error(f"📄 Traceback: {traceback.format_exc()}")
    
    def _decode_mime_header(self, raw: str) -> str:
        """Decode MIME header"""
        if not raw:
            return ""
        try:
            return str(make_header(decode_header(raw)))
        except Exception:
            return raw
    
    def _extract_text_body(self, msg: email.message.Message) -> str:
        """Extract text body from email message"""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = part.get("Content-Disposition", "") or ""
                
                if content_type == "text/plain" and "attachment" not in disposition.lower():
                    charset = part.get_content_charset() or "utf-8"
                    return part.get_payload(decode=True).decode(charset, errors="replace")
            
            # Fallback to HTML
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
    
    def _is_alert_related_email(self, from_addr: str, subject: str, body: str) -> bool:
        """Check if email is alert-related"""
        # Get filter settings from config
        search_keywords = self.config.get('search_keywords', [])
        from_domains = self.config.get('from_domains', [])
        
        # Clean up empty strings from split
        search_keywords = [k.strip() for k in search_keywords if k.strip()]
        from_domains = [d.strip() for d in from_domains if d.strip()]
        
        logging.debug(f"🔍 Filter check - Keywords: {search_keywords}, Domains: {from_domains}")
        logging.debug(f"🔍 Email details - From: {from_addr[:50]}, Subject: {subject[:50]}")
        
        # If no filters configured, accept all (for backward compatibility)
        if not search_keywords and not from_domains:
            logging.info("⚠️ No filters configured - accepting all emails")
            return True
        
        keyword_match = False
        domain_match = False
        
        # Check subject and body for keywords
        if search_keywords:
            text_to_search = f"{subject} {body}".lower()
            keyword_match = any(keyword.lower() in text_to_search for keyword in search_keywords)
            if keyword_match:
                matched_keywords = [k for k in search_keywords if k.lower() in text_to_search]
                logging.info(f"✅ Keyword match found: {matched_keywords}")
            else:
                logging.debug(f"❌ No keyword match in: {text_to_search[:100]}")
        
        # Check sender domain
        if from_domains:
            from_addr_lower = from_addr.lower()
            domain_match = any(domain.lower() in from_addr_lower for domain in from_domains)
            if domain_match:
                matched_domains = [d for d in from_domains if d.lower() in from_addr_lower]
                logging.info(f"✅ Domain match found: {matched_domains}")
            else:
                logging.debug(f"❌ No domain match in: {from_addr_lower}")
        
        # Email passes if it matches keywords OR domains (OR logic)
        passes_filter = keyword_match or domain_match
        
        # Update filter statistics
        if passes_filter:
            if keyword_match and domain_match:
                self.stats['filter_matches']['both'] += 1
                logging.info(f"✅ Email passes filter (BOTH keyword+domain) - Subject: {subject[:50]}")
            elif keyword_match:
                self.stats['filter_matches']['keyword'] += 1
                logging.info(f"✅ Email passes filter (KEYWORD match) - Subject: {subject[:50]}")
            elif domain_match:
                self.stats['filter_matches']['domain'] += 1
                logging.info(f"✅ Email passes filter (DOMAIN match) - Subject: {subject[:50]}")
        else:
            logging.info(f"🚫 Email filtered out - Subject: {subject[:50]}")
        
        return passes_filter
    
    def _schedule_reconnect(self):
        """Schedule reconnection with exponential backoff"""
        if self.should_stop or self.reconnect_attempts >= self.max_reconnect_attempts:
            if self.reconnect_attempts >= self.max_reconnect_attempts:
                logging.error("Max reconnection attempts reached. Manual intervention required.")
                self.emit('max_reconnects_reached')
            return
        
        self.reconnect_attempts += 1
        delay = self.reconnect_delay * (self.reconnect_backoff_multiplier ** (self.reconnect_attempts - 1))
        
        logging.info(f"Scheduling reconnection attempt {self.reconnect_attempts} in {delay:.2f} seconds")
        
        def reconnect_timer():
            time.sleep(delay)
            if not self.should_stop:
                try:
                    if self.imap:
                        try:
                            self.imap.logout()
                        except:
                            pass
                    # Schedule reconnection in event loop
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.run_coroutine_threadsafe(self._connect(), loop)
                        else:
                            asyncio.run(self._connect())
                    except RuntimeError:
                        # No event loop running, create new one
                        asyncio.run(self._connect())
                except Exception as e:
                    logging.error(f"Reconnection failed: {e}")
        
        reconnect_thread = threading.Thread(target=reconnect_timer, daemon=True)
        reconnect_thread.start()
    
    def stop(self):
        """Stop IMAP IDLE service"""
        logging.info("Stopping IMAP IDLE service")
        
        # Generate final status report
        if self.is_connected:
            self._report_status()
        
        self.should_stop = True
        self.is_idling = False
        
        if self.imap:
            try:
                if self.is_idling:
                    self.imap.idle_done()
                self.imap.logout()
            except:
                pass
            self.imap = None
        
        self.is_connected = False
        self.emit('stopped')
    
    def get_status(self) -> Dict[str, Any]:
        """Get connection status"""
        return {
            'connected': self.is_connected,
            'idling': self.is_idling,
            'reconnect_attempts': self.reconnect_attempts,
            'last_activity': self.last_activity,
            'processed_count': len(self.processed_uids),
            'last_exists_count': self.last_exists_count,
            'stats': self.stats
        }

class MonitorGUI:
    """Gmail MQTT Monitor GUI"""
    
    def __init__(self, monitor=None):
        if not GUI_AVAILABLE:
            raise RuntimeError("GUI not available - tkinter not installed")
        
        self.monitor = monitor
        self.root = tk.Tk()
        self.root.title("Gmail MQTT Monitor")
        self.root.geometry("500x400")
        
        # GUI状態
        self.is_running = False
        self.monitor_thread = None
        
        self.setup_ui()
        self.center_window()
    
    def setup_ui(self):
        """UIを構築"""
        # メインフレーム
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill="both", expand=True)
        
        # タイトル
        title_label = ttk.Label(main_frame, text="Gmail MQTT Monitor", 
                               font=("", 16, "bold"))
        title_label.pack(pady=(0, 20))
        
        # 状態表示
        status_frame = ttk.LabelFrame(main_frame, text="状態", padding="10")
        status_frame.pack(fill="x", pady=(0, 10))
        
        self.status_var = tk.StringVar(value="停止中")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var,
                                     font=("", 12))
        self.status_label.pack()
        
        # 統計情報
        stats_frame = ttk.LabelFrame(main_frame, text="統計情報", padding="10")
        stats_frame.pack(fill="x", pady=(0, 10))
        
        self.stats_text = tk.Text(stats_frame, height=6, wrap="word", 
                                 state="disabled")
        stats_scroll = ttk.Scrollbar(stats_frame, command=self.stats_text.yview)
        self.stats_text.config(yscrollcommand=stats_scroll.set)
        
        self.stats_text.pack(side="left", fill="both", expand=True)
        stats_scroll.pack(side="right", fill="y")
        
        # ボタンフレーム
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill="x", pady=(10, 0))
        
        # 開始/停止ボタン
        self.start_button = ttk.Button(button_frame, text="監視開始", 
                                      command=self.toggle_monitoring)
        self.start_button.pack(side="left", padx=(0, 10))
        
        # 設定ボタン
        settings_button = ttk.Button(button_frame, text="設定", 
                                   command=self.open_settings)
        settings_button.pack(side="left", padx=(0, 10))
        
        # ログ表示ボタン
        log_button = ttk.Button(button_frame, text="ログ表示", 
                               command=self.show_logs)
        log_button.pack(side="left", padx=(0, 10))
        
        # MQTT送信テストボタン
        test_send_button = ttk.Button(button_frame, text="MQTT送信テスト", 
                                     command=self.test_mqtt_send)
        test_send_button.pack(side="left", padx=(0, 10))
        
        # 終了ボタン
        quit_button = ttk.Button(button_frame, text="終了", 
                                command=self.quit_app)
        quit_button.pack(side="right")
        
        # 定期更新開始
        self.update_stats()
    
    def center_window(self):
        """ウィンドウを画面中央に配置"""
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')
    
    def toggle_monitoring(self):
        """監視の開始/停止を切り替え"""
        if not self.is_running:
            self.start_monitoring()
        else:
            self.stop_monitoring()
    
    def start_monitoring(self):
        """監視を開始"""
        try:
            self.is_running = True
            self.status_var.set("監視中...")
            self.start_button.config(text="監視停止")
            
            # バックグラウンドでモニターを実行
            self.monitor_thread = threading.Thread(
                target=self.run_monitor_async, daemon=True
            )
            self.monitor_thread.start()
            
        except Exception as e:
            messagebox.showerror("エラー", f"監視開始に失敗しました:\n{str(e)}")
            self.is_running = False
            self.status_var.set("停止中")
            self.start_button.config(text="監視開始")
    
    def stop_monitoring(self):
        """監視を停止"""
        self.is_running = False
        self.status_var.set("停止中")
        self.start_button.config(text="監視開始")
        
        if self.monitor:
            self.monitor.stop()
    
    def run_monitor_async(self):
        """非同期でモニターを実行"""
        try:
            if not self.monitor:
                self.monitor = GmailToMqttMonitor()
            
            # 新しいイベントループで実行
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                loop.run_until_complete(self.monitor.start())
            finally:
                loop.close()
                
        except Exception as e:
            error_msg = str(e)
            logging.error(f"Monitor error: {error_msg}")
            self.root.after(0, lambda msg=error_msg: self.handle_monitor_error(msg))
    
    def handle_monitor_error(self, error_msg):
        """モニターエラーを処理"""
        self.is_running = False
        self.status_var.set("エラー発生")
        self.start_button.config(text="監視開始")
        messagebox.showerror("監視エラー", f"監視中にエラーが発生しました:\n{error_msg}")
    
    def open_settings(self):
        """設定画面を開く"""
        try:
            # gui_settings.pyを実行
            script_path = os.path.join(os.path.dirname(__file__), "gui_settings.py")
            python_path = sys.executable
            
            subprocess.Popen([python_path, script_path])
            
        except Exception as e:
            messagebox.showerror("エラー", f"設定画面を開けませんでした:\n{str(e)}")
    
    def show_logs(self):
        """ログ表示ウィンドウを開く"""
        log_window = tk.Toplevel(self.root)
        log_window.title("ログ")
        log_window.geometry("800x600")
        
        log_text = tk.Text(log_window, wrap="word")
        log_scroll = ttk.Scrollbar(log_window, command=log_text.yview)
        log_text.config(yscrollcommand=log_scroll.set)
        
        log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")
        
        # ログファイルがあれば読み込み
        try:
            # 最新のログメッセージを表示
            log_text.insert("1.0", "ログ機能は今後実装予定です。\n\n")
            log_text.insert("end", f"現在の状態: {self.status_var.get()}\n")
            if self.monitor and hasattr(self.monitor, 'stats'):
                log_text.insert("end", f"統計情報:\n{json.dumps(self.monitor.stats, indent=2, ensure_ascii=False)}")
        except Exception as e:
            log_text.insert("1.0", f"ログ表示エラー: {str(e)}\n")
        
        log_text.config(state="disabled")
    
    def update_stats(self):
        """統計情報を更新"""
        try:
            self.stats_text.config(state="normal")
            self.stats_text.delete("1.0", "end")
            
            if self.monitor and hasattr(self.monitor, 'stats'):
                stats = self.monitor.stats
                uptime = time.time() - stats.get('start_time', time.time())
                
                stats_info = [
                    f"稼働時間: {uptime:.0f}秒",
                    f"処理メール数: {stats.get('emails_processed', 0)}",
                    f"送信アラート数: {stats.get('alerts_sent', 0)}",
                    f"エラー数: {stats.get('errors', 0)}",
                ]
                
                if stats.get('last_activity'):
                    last_activity = time.strftime("%H:%M:%S", 
                        time.localtime(stats['last_activity']))
                    stats_info.append(f"最後の活動: {last_activity}")
                
                self.stats_text.insert("1.0", "\n".join(stats_info))
            else:
                self.stats_text.insert("1.0", "監視未開始")
            
            self.stats_text.config(state="disabled")
        except Exception as e:
            logging.error(f"Stats update error: {e}")
        
        # 1秒後に再実行
        self.root.after(1000, self.update_stats)
    
    def test_mqtt_send(self):
        """MQTT送信テスト"""
        try:
            # テスト用メッセージを作成
            from datetime import datetime
            test_message = {
                "uid": "TEST-" + str(int(time.time())),
                "message_id": f"test-{int(time.time())}@test.local",
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "from": "test@example.com",
                "subject": "MQTT送信テスト",
                "body": "これはMQTT接続をテストするためのメッセージです。\n送信時刻: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            if hasattr(self, 'monitor') and self.monitor:
                # 監視中の場合は、既存のモニターのMQTT機能を使用
                if self.monitor._mqtt_publish(test_message):
                    messagebox.showinfo("テスト成功", 
                                      "MQTT送信テストが成功しました！\n"
                                      "Tauriアプリでメッセージを確認してください。")
                else:
                    messagebox.showerror("テスト失敗", "MQTT送信に失敗しました。")
            else:
                # 監視停止中の場合は、一時的なモニターを作成してテスト
                test_monitor = GmailToMqttMonitor()
                if test_monitor._mqtt_publish(test_message):
                    messagebox.showinfo("テスト成功", 
                                      "MQTT送信テストが成功しました！\n"
                                      "Tauriアプリでメッセージを確認してください。")
                else:
                    messagebox.showerror("テスト失敗", "MQTT送信に失敗しました。")
                    
        except Exception as e:
            messagebox.showerror("エラー", f"テスト送信中にエラーが発生しました:\n{str(e)}")
    
    def quit_app(self):
        """アプリケーションを終了"""
        if self.is_running:
            self.stop_monitoring()
        
        self.root.quit()
        self.root.destroy()
    
    def run(self):
        """GUIを実行"""
        self.root.mainloop()

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
        
        # Setup graceful shutdown (only in non-GUI mode)
        try:
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
        except ValueError:
            # Signal handlers can only be set in main thread
            logging.debug("Signal handlers not set (not in main thread)")
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file with fallback to environment variables"""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, "config.yaml")
        
        # Try loading YAML config first
        if YAML_AVAILABLE and os.path.exists(config_path):
            return self._load_yaml_config(config_path)
        else:
            logging.warning("YAML config not available, falling back to environment variables")
            return self._load_env_config(base_dir)
    
    def _load_yaml_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            logging.info(f"Configuration loaded from {config_path}")
            
            # Validate required sections
            required_sections = ['gmail', 'mqtt', 'filters']
            for section in required_sections:
                if section not in config:
                    raise ValueError(f"Missing required section '{section}' in config.yaml")
            
            # Convert YAML structure to internal format
            return {
                # IMAP Configuration
                'user': config['gmail']['user'],
                'password': config['gmail']['password'],
                'host': config['gmail']['host'],
                'port': config['gmail']['port'],
                'inbox_folder': config['gmail']['folder'],
                'idle_timeout': config.get('imap_idle', {}).get('timeout', 300),
                'max_reconnect_attempts': config.get('imap_idle', {}).get('max_reconnect_attempts', 10),
                'reconnect_delay': config.get('imap_idle', {}).get('reconnect_delay', 5000),
                'reconnect_backoff_multiplier': config.get('imap_idle', {}).get('reconnect_backoff_multiplier', 1.5),
                
                # Search Keywords
                'search_keywords': config['filters']['search_keywords'],
                'from_domains': config['filters']['from_domains'],
                
                # MQTT Configuration
                'mqtt': {
                    'host': config['mqtt']['host'],
                    'port': config['mqtt']['port'],
                    'tls': config['mqtt']['tls'],
                    'user': config['mqtt']['user'],
                    'password': config['mqtt']['password'],
                    'topic': config['mqtt']['topic'],
                    'keepalive': config['mqtt']['keepalive']
                },
                
                # Processing Configuration
                'fetch_body_limit': config.get('processing', {}).get('fetch_body_limit', 4000),
                'poll_on_wake': config.get('processing', {}).get('poll_on_wake', False),
                
                # Additional YAML-specific configs
                'tls_insecure': config['mqtt'].get('tls_insecure', False),
                'use_system_ca': config['mqtt'].get('use_system_ca', True),
                'client_id': config['mqtt'].get('client_id', ''),
                'qos': config['mqtt'].get('qos', 1),
                'retain': config['mqtt'].get('retain', False),
                'ca_file': config.get('tls_certificates', {}).get('ca_file', ''),
                'cert_file': config.get('tls_certificates', {}).get('cert_file', ''),
                'key_file': config.get('tls_certificates', {}).get('key_file', ''),
                'log_level': config.get('logging', {}).get('level', 'INFO'),
                'service_mode': config.get('compute_engine', {}).get('service_mode', False),
                'pid_file': config.get('compute_engine', {}).get('pid_file', '/tmp/gmail_mqtt_monitor.pid'),
                'log_file': config.get('compute_engine', {}).get('log_file', '/var/log/gmail_mqtt_monitor.log')
            }
            
        except Exception as e:
            logging.error(f"Error loading YAML config: {e}")
            raise ValueError(f"Failed to load config.yaml: {e}")
    
    def _load_env_config(self, base_dir: str) -> Dict[str, Any]:
        """Load configuration from environment variables (fallback)"""
        # Load .env file
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
            'poll_on_wake': os.environ.get('POLL_ON_WAKE', 'False').lower() == 'true',
            
            # Environment-based configs
            'tls_insecure': os.environ.get('MQTT_TLS_INSECURE', 'false').lower() == 'true',
            'use_system_ca': os.environ.get('MQTT_USE_SYSTEM_CA', 'true').lower() == 'true',
            'client_id': os.environ.get('MQTT_CLIENT_ID', ''),
            'qos': int(os.environ.get('MQTT_QOS', '1')),
            'retain': os.environ.get('MQTT_RETAIN', 'false').lower() == 'true',
            'ca_file': os.environ.get('MQTT_CAFILE', ''),
            'cert_file': os.environ.get('MQTT_CERTFILE', ''),
            'key_file': os.environ.get('MQTT_KEYFILE', ''),
            'service_mode': False,
            'pid_file': '/tmp/gmail_mqtt_monitor.pid',
            'log_file': '/var/log/gmail_mqtt_monitor.log'
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
                client_id = self.config.get('client_id') or None
                client = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
                client.username_pw_set(
                    self.config['mqtt']['user'], 
                    self.config['mqtt']['password']
                )
                if self.config['mqtt']['tls']:
                    # TLS設定（Let's Encrypt対応）
                    ca_certs = None
                    certfile = None
                    keyfile = None
                    
                    # システムCA証明書を使用（Let's Encrypt対応）
                    if self.config.get('use_system_ca', True):
                        ca_certs = None  # システムのCA証明書を使用
                    else:
                        # 手動指定のCA証明書
                        ca_file = self.config.get('ca_file', '')
                        ca_certs = ca_file if ca_file else None
                    
                    # クライアント証明書（必要な場合）
                    cert_file = self.config.get('cert_file', '')
                    key_file = self.config.get('key_file', '')
                    if cert_file and key_file:
                        certfile = cert_file
                        keyfile = key_file
                    
                    client.tls_set(ca_certs=ca_certs, certfile=certfile, keyfile=keyfile)
                    
                    if self.config.get('tls_insecure', False):
                        client.tls_insecure_set(True)
                
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
                    qos=self.config.get('qos', 1), 
                    retain=self.config.get('retain', False)
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
            client_id = self.config.get('client_id') or None
            client = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
            client.username_pw_set(
                self.config['mqtt']['user'], 
                self.config['mqtt']['password']
            )
            if self.config['mqtt']['tls']:
                # TLS設定（Let's Encrypt対応）
                ca_certs = None
                certfile = None
                keyfile = None
                
                # システムCA証明書を使用（Let's Encrypt対応）
                if self.config.get('use_system_ca', True):
                    ca_certs = None  # システムのCA証明書を使用
                else:
                    # 手動指定のCA証明書
                    ca_file = self.config.get('ca_file', '')
                    ca_certs = ca_file if ca_file else None
                
                # クライアント証明書（必要な場合）
                cert_file = self.config.get('cert_file', '')
                key_file = self.config.get('key_file', '')
                if cert_file and key_file:
                    certfile = cert_file
                    keyfile = key_file
                
                client.tls_set(ca_certs=ca_certs, certfile=certfile, keyfile=keyfile)
                
                if self.config.get('tls_insecure', False):
                    client.tls_insecure_set(True)
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

def main_gui():
    """GUI mode entry point"""
    try:
        if not GUI_AVAILABLE:
            print("GUI not available. Please install tkinter.")
            print("Running in console mode...")
            asyncio.run(main())
            return
        
        gui = MonitorGUI()
        gui.run()
        
    except KeyboardInterrupt:
        logging.info("Stopped by user")
    except Exception as e:
        logging.error(f"GUI error: {e}")
        # Fallback to console mode
        print("GUI failed, running in console mode...")
        asyncio.run(main())

if __name__ == "__main__":
    # Fix asyncio issue with reconnection
    import asyncio
    
    # Add asyncio import to the ImapIdleService
    if 'asyncio' not in sys.modules:
        import asyncio
    
    # Check command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == "--console":
        # Console mode
        asyncio.run(main())
    else:
        # GUI mode (default)
        main_gui()