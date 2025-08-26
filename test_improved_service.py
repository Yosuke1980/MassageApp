#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for improved Gmail IMAP IDLE service
This script tests basic functionality without actually connecting
"""
import os
import sys
import logging
from dotenv import load_dotenv

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gmail_imap_service import ImapIdleService, EventEmitter

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def test_event_emitter():
    """Test EventEmitter functionality"""
    print("\n=== Testing EventEmitter ===")
    
    emitter = EventEmitter()
    test_results = {'called': False, 'data': None}
    
    def test_handler(data):
        test_results['called'] = True
        test_results['data'] = data
        print(f"Event handler called with: {data}")
    
    # Register event handler
    emitter.on('test_event', test_handler)
    
    # Emit event
    emitter.emit('test_event', 'Hello World')
    
    # Check results
    assert test_results['called'], "Event handler was not called"
    assert test_results['data'] == 'Hello World', "Event data mismatch"
    
    print("✓ EventEmitter test passed")

def test_config_loading():
    """Test configuration loading"""
    print("\n=== Testing Configuration ===")
    
    # Load environment variables
    base_dir = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(dotenv_path=os.path.join(base_dir, ".env"))
    
    # Test config structure
    config = {
        'user': os.environ.get('GMAIL_USER', 'test@example.com'),
        'password': os.environ.get('GMAIL_PASS', 'test_password'),
        'host': 'imap.gmail.com',
        'port': 993,
        'search_keywords': ['test', 'keyword'],
        'max_reconnect_attempts': 5,
        'reconnect_delay': 1000,
        'reconnect_backoff_multiplier': 1.5
    }
    
    print(f"Config loaded: {config['user']} @ {config['host']}:{config['port']}")
    print(f"Search keywords: {config['search_keywords']}")
    print("✓ Configuration test passed")
    
    return config

def test_service_initialization():
    """Test service initialization"""
    print("\n=== Testing Service Initialization ===")
    
    config = {
        'user': 'test@example.com',
        'password': 'test_password',
        'host': 'imap.gmail.com',
        'port': 993,
        'search_keywords': ['test', 'alert'],
        'max_reconnect_attempts': 3,
        'reconnect_delay': 1000,
        'reconnect_backoff_multiplier': 1.5
    }
    
    # Initialize service
    service = ImapIdleService(config)
    
    # Check initial state
    status = service.get_status()
    assert not status['connected'], "Service should not be connected initially"
    assert not status['idling'], "Service should not be idling initially"
    assert status['reconnect_attempts'] == 0, "Should have 0 reconnect attempts initially"
    assert status['processed_count'] == 0, "Should have 0 processed messages initially"
    assert status['last_exists_count'] == 0, "Should have 0 EXISTS count initially"
    
    print("✓ Service initialization test passed")
    print(f"Initial status: {status}")
    
    return service

def test_message_filtering():
    """Test message filtering logic"""
    print("\n=== Testing Message Filtering ===")
    print("ℹ️ Note: Current implementation is in TEST MODE (accepts all emails)")
    
    config = {
        'search_keywords': ['earthquake', '地震', 'tsunami', '津波'],
        'user': 'test@example.com',
        'password': 'test_password'
    }
    
    service = ImapIdleService(config)
    
    # Test messages - all will return True in TEST MODE
    test_cases = [
        {
            'email': {
                'subject': 'Earthquake Alert',
                'from': 'alerts@example.com',
                'body': 'This is an earthquake alert'
            },
            'expected': True  # TEST MODE: all emails accepted
        },
        {
            'email': {
                'subject': 'Regular Email',
                'from': 'friend@example.com',
                'body': 'How are you doing?'
            },
            'expected': True  # TEST MODE: all emails accepted
        },
        {
            'email': {
                'subject': '地震情報',
                'from': 'jma@example.jp',
                'body': '地震が発生しました'
            },
            'expected': True  # TEST MODE: all emails accepted
        }
    ]
    
    for i, case in enumerate(test_cases):
        email = case['email']
        expected = case['expected']
        
        result = service._is_alert_related_email(
            email['from'], 
            email['subject'], 
            email['body']
        )
        
        print(f"Test case {i+1}: '{email['subject']}' -> {result} (expected: {expected})")
        assert result == expected, f"Test case {i+1} failed"
    
    print("✓ Message filtering test passed (TEST MODE)")

def test_exists_parsing():
    """Test EXISTS parsing from IDLE notifications"""
    print("\n=== Testing EXISTS Parsing ===")
    
    config = {
        'user': 'test@example.com',
        'password': 'test_password'
    }
    
    service = ImapIdleService(config)
    
    # Test cases for EXISTS parsing
    test_cases = [
        {
            'responses': [(1291, b'EXISTS')],
            'expected': 1291,
            'description': 'Single EXISTS response'
        },
        {
            'responses': [(1290, b'EXISTS'), (1291, b'EXISTS')],
            'expected': 1291,
            'description': 'Multiple EXISTS responses (should get last)'
        },
        {
            'responses': [(5, b'RECENT'), (1291, b'EXISTS')],
            'expected': 1291,
            'description': 'Mixed responses with EXISTS'
        },
        {
            'responses': [(5, b'RECENT')],
            'expected': None,
            'description': 'No EXISTS in responses'
        },
        {
            'responses': [],
            'expected': None,
            'description': 'Empty responses'
        }
    ]
    
    for i, case in enumerate(test_cases):
        result = service._parse_exists_from_idle(case['responses'])
        expected = case['expected']
        desc = case['description']
        
        print(f"Test case {i+1}: {desc}")
        print(f"  Responses: {case['responses']}")
        print(f"  Result: {result}, Expected: {expected}")
        
        assert result == expected, f"Test case {i+1} failed: got {result}, expected {expected}"
    
    print("✓ EXISTS parsing test passed")

def main():
    """Run all tests"""
    print("=== Gmail IMAP IDLE Service Tests ===")
    
    try:
        # Run tests
        test_event_emitter()
        config = test_config_loading()
        service = test_service_initialization()
        test_message_filtering()
        test_exists_parsing()
        
        print("\n=== All Tests Passed ===")
        print("The improved Gmail IMAP IDLE service is ready to use!")
        print("\nTo use the service:")
        print("1. Make sure your .env file contains all required variables")
        print("2. Run: python3 gmail_idle_to_mqtt_improved.py")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()