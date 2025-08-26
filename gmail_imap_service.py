#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gmail IMAP IDLE Service with EventEmitter-like functionality
Based on alertapp's ImapIdleService.js implementation
"""
import os
import ssl
import time
import email
import email.message
import logging
import socket
import threading
import asyncio
import traceback
from email.header import decode_header, make_header
from imapclient import IMAPClient
import backoff
from typing import Set, Callable, Dict, Any, Optional

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
            self.last_exists_count = exists_count
            
            logging.info(f"Opened {self.inbox_folder} with {exists_count} messages (tracking EXISTS count)")
            logging.debug(f"📊 Initial EXISTS count set to: {self.last_exists_count}")
            
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
                            logging.info(f"🔔 IDLE notification received: {responses}")
                            self.last_activity = time.time()
                            
                            # Parse EXISTS information from IDLE notification
                            new_exists_count = self._parse_exists_from_idle(responses)
                            if new_exists_count and new_exists_count > self.last_exists_count:
                                logging.info("🔍 Starting to process new messages using EXISTS-based detection...")
                                
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
            
            if new_exists_count <= self.last_exists_count:
                logging.info("ℹ️ No new messages (EXISTS count did not increase)")
                return
            
            # Calculate new UID range
            # Note: UID might not be sequential with EXISTS count, so we'll fetch recent messages
            new_message_count = new_exists_count - self.last_exists_count
            logging.info(f"🔢 Detected {new_message_count} new message(s)")
            
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
                    else:
                        logging.debug(f"⏭️ UID {uid} already processed")
                
                logging.info(f"✅ Successfully processed {processed_count} new messages")
                
                # Update EXISTS count
                self.last_exists_count = new_exists_count
                logging.debug(f"📊 Updated last_exists_count to: {self.last_exists_count}")
                
            except Exception as fetch_error:
                logging.error(f"❌ CRITICAL: Error fetching new message UIDs: {fetch_error}")
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
            logging.error(f"📄 Traceback: {traceback.format_exc()}")
    
    def _process_new_messages_fallback(self):
        """Fallback method: process messages using traditional UNSEEN search"""
        logging.info("🔄 Fallback: Using UNSEEN search")
        self._process_new_messages()
    
    def _process_new_messages(self):
        """Process new messages"""
        if not self.is_connected:
            logging.warning("⚠️ Not connected to IMAP server")
            return
        
        try:
            logging.info("🔎 Searching for UNSEEN messages...")
            
            # Check connection before search
            if not self.imap:
                logging.error("❌ IMAP client is None")
                return
            
            try:
                # Search for unseen messages with detailed logging
                logging.debug("🔍 Executing IMAP search for UNSEEN...")
                uids = self.imap.search(['UNSEEN'])
                logging.debug(f"🔍 IMAP search completed, type: {type(uids)}, content: {uids}")
                
            except Exception as search_error:
                logging.error(f"❌ IMAP search failed: {search_error}")
                logging.error(f"📄 Search error traceback: {traceback.format_exc()}")
                return
            
            # Handle search results
            if uids is None:
                logging.warning("⚠️ UNSEEN search returned None")
                return
                
            logging.info(f"📊 UNSEEN search result: {len(uids)} messages")
            if uids and len(uids) <= 10:
                logging.info(f"📋 Found UIDs: {uids}")
            elif uids:
                logging.info(f"📋 Found UIDs: {uids[:5]}... (+{len(uids)-5} more)")
            
            if not uids:
                logging.info("✅ No new unseen messages found")
                return
            
            logging.info(f"🔄 Processing {len(uids)} unseen messages...")
            
            # Process each message
            processed_count = 0
            skipped_count = 0
            
            for uid in uids:
                if uid not in self.processed_uids:
                    logging.info(f"📧 Processing new message UID {uid}")
                    self._process_message(uid)
                    processed_count += 1
                else:
                    logging.debug(f"⏭️ Message UID {uid} already processed")
                    skipped_count += 1
            
            logging.info(f"✅ Message processing complete: {processed_count} processed, {skipped_count} skipped")
        
        except Exception as e:
            logging.error(f"❌ Error processing new messages: {e}")
            import traceback
            logging.error(f"📄 Traceback: {traceback.format_exc()}")
    
    def _process_message(self, uid: int):
        """Process individual message"""
        try:
            logging.info(f"📝 Processing message UID {uid}")
            
            # Fetch message
            logging.debug(f"🔽 Fetching message data for UID {uid}")
            fetch_data = self.imap.fetch([uid], ['ENVELOPE', 'RFC822'])
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
            logging.debug(f"🔍 Checking if email UID {uid} is alert-related")
            if self._is_alert_related_email(from_header, subject_header, body):
                logging.info(f"🚨 Alert email detected UID {uid}: {subject_header}")
                
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
                    self.imap.add_flags([uid], ['\\Seen'])
                    logging.debug(f"👁️ UID {uid} marked as seen")
                except Exception as e:
                    logging.error(f"❌ Failed to mark message {uid} as seen: {e}")
            else:
                logging.info(f"🚫 Email UID {uid} filtered out")
        
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
        """Check if email is alert-related - TEST MODE: All emails accepted"""
        # TEST MODE: Accept all emails
        logging.info(f"TEST MODE: All emails accepted - Subject: {subject[:50]}")
        return True
    
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
            'last_exists_count': self.last_exists_count
        }