#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI Settings Application for Gmail MQTT Monitor
総合的な設定画面を提供し、.envファイルへの設定保存機能を含む
"""

import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json
from dotenv import load_dotenv
import threading
import paho.mqtt.client as mqtt
from imapclient import IMAPClient
import ssl

class SettingsApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Gmail MQTT Monitor - 設定")
        self.root.geometry("900x800")
        
        # Load current configuration
        self.config = self.load_config()
        
        # Setup UI
        self.setup_ui()
        
        # Center window
        self.center_window()
    
    def load_config(self):
        """環境変数から設定を読み込み"""
        load_dotenv()
        return {
            # Gmail/IMAP設定
            'GMAIL_USER': os.environ.get('GMAIL_USER', ''),
            'GMAIL_PASS': os.environ.get('GMAIL_PASS', ''),
            'IMAP_FOLDER': os.environ.get('IMAP_FOLDER', 'INBOX'),
            'IDLE_TIMEOUT': os.environ.get('IDLE_TIMEOUT', '300'),
            'FETCH_BODY_LIMIT': os.environ.get('FETCH_BODY_LIMIT', '4000'),
            'POLL_ON_WAKE': os.environ.get('POLL_ON_WAKE', 'False'),
            
            # 検索条件
            'SEARCH_KEYWORDS': os.environ.get('SEARCH_KEYWORDS', '地震情報,津波情報'),
            'FROM_DOMAINS': os.environ.get('FROM_DOMAINS', 'bosai-jma@jmainfo.go.jp'),
            
            # MQTT設定
            'MQTT_HOST': os.environ.get('MQTT_HOST', 'localhost'),
            'MQTT_PORT': os.environ.get('MQTT_PORT', '8883'),
            'MQTT_TLS': os.environ.get('MQTT_TLS', 'true'),
            'MQTT_USER': os.environ.get('MQTT_USER', ''),
            'MQTT_PASS': os.environ.get('MQTT_PASS', ''),
            'MQTT_TOPIC': os.environ.get('MQTT_TOPIC', 'inbox/matches') or 'inbox/matches',
            'MQTT_CLIENT_ID': os.environ.get('MQTT_CLIENT_ID', ''),
            'MQTT_QOS': os.environ.get('MQTT_QOS', '1'),
            'MQTT_RETAIN': os.environ.get('MQTT_RETAIN', 'false'),
            'MQTT_TLS_INSECURE': os.environ.get('MQTT_TLS_INSECURE', 'false'),
            'MQTT_CAFILE': os.environ.get('MQTT_CAFILE', ''),
            'MQTT_CERTFILE': os.environ.get('MQTT_CERTFILE', ''),
            'MQTT_KEYFILE': os.environ.get('MQTT_KEYFILE', ''),
            'MQTT_USE_SYSTEM_CA': os.environ.get('MQTT_USE_SYSTEM_CA', 'true'),
            'LETSENCRYPT_DOMAIN': os.environ.get('LETSENCRYPT_DOMAIN', ''),
            
            # その他
            'LOG_LEVEL': os.environ.get('LOG_LEVEL', 'INFO')
        }
    
    def setup_ui(self):
        """UIを構築"""
        # ノートブック（タブ）を作成
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)
        
        # タブを作成
        self.create_gmail_tab(notebook)
        self.create_filtering_tab(notebook)
        self.create_mqtt_tab(notebook)
        self.create_advanced_tab(notebook)
        
        # ボタンフレーム
        self.create_button_frame()
    
    def create_gmail_tab(self, notebook):
        """Gmail/IMAP設定タブ"""
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="Gmail/IMAP")
        
        # メインフレーム
        main_frame = ttk.Frame(tab, padding="20")
        main_frame.pack(fill="both", expand=True)
        
        # Gmail認証情報
        auth_frame = ttk.LabelFrame(main_frame, text="Gmail認証情報", padding="10")
        auth_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(auth_frame, text="Gmailアドレス:").grid(row=0, column=0, sticky="w", pady=5)
        self.gmail_user_var = tk.StringVar(value=self.config['GMAIL_USER'])
        ttk.Entry(auth_frame, textvariable=self.gmail_user_var, width=50).grid(row=0, column=1, sticky="ew", padx=(10, 0))
        
        ttk.Label(auth_frame, text="アプリパスワード:").grid(row=1, column=0, sticky="w", pady=5)
        self.gmail_pass_var = tk.StringVar(value=self.config['GMAIL_PASS'])
        ttk.Entry(auth_frame, textvariable=self.gmail_pass_var, width=50, show="*").grid(row=1, column=1, sticky="ew", padx=(10, 0))
        
        auth_frame.columnconfigure(1, weight=1)
        
        # IMAP設定
        imap_frame = ttk.LabelFrame(main_frame, text="IMAP設定", padding="10")
        imap_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(imap_frame, text="監視フォルダ:").grid(row=0, column=0, sticky="w", pady=5)
        self.imap_folder_var = tk.StringVar(value=self.config['IMAP_FOLDER'])
        ttk.Entry(imap_frame, textvariable=self.imap_folder_var, width=30).grid(row=0, column=1, sticky="ew", padx=(10, 0))
        
        ttk.Label(imap_frame, text="IDLEタイムアウト（秒）:").grid(row=1, column=0, sticky="w", pady=5)
        self.idle_timeout_var = tk.StringVar(value=self.config['IDLE_TIMEOUT'])
        ttk.Entry(imap_frame, textvariable=self.idle_timeout_var, width=10).grid(row=1, column=1, sticky="w", padx=(10, 0))
        
        ttk.Label(imap_frame, text="本文取得制限（文字数）:").grid(row=2, column=0, sticky="w", pady=5)
        self.fetch_body_limit_var = tk.StringVar(value=self.config['FETCH_BODY_LIMIT'])
        ttk.Entry(imap_frame, textvariable=self.fetch_body_limit_var, width=10).grid(row=2, column=1, sticky="w", padx=(10, 0))
        
        self.poll_on_wake_var = tk.BooleanVar(value=self.config['POLL_ON_WAKE'].lower() == 'true')
        ttk.Checkbutton(imap_frame, text="起動時にポーリング実行", variable=self.poll_on_wake_var).grid(row=3, column=0, columnspan=2, sticky="w", pady=5)
        
        imap_frame.columnconfigure(1, weight=1)
        
        # テストボタン
        test_frame = ttk.Frame(main_frame)
        test_frame.pack(fill="x", pady=10)
        ttk.Button(test_frame, text="Gmail接続テスト", command=self.test_gmail_connection).pack(side="left")
    
    def create_filtering_tab(self, notebook):
        """フィルタリング設定タブ"""
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="フィルタリング")
        
        main_frame = ttk.Frame(tab, padding="20")
        main_frame.pack(fill="both", expand=True)
        
        # 検索キーワード
        keywords_frame = ttk.LabelFrame(main_frame, text="検索キーワード", padding="10")
        keywords_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(keywords_frame, text="キーワード（カンマ区切り）:").pack(anchor="w")
        self.search_keywords_var = tk.StringVar(value=self.config['SEARCH_KEYWORDS'])
        keywords_entry = ttk.Entry(keywords_frame, textvariable=self.search_keywords_var, width=80)
        keywords_entry.pack(fill="x", pady=5)
        
        ttk.Label(keywords_frame, text="例: 地震情報,津波情報,気象警報", foreground="gray").pack(anchor="w")
        
        # 送信元ドメイン
        domains_frame = ttk.LabelFrame(main_frame, text="送信元フィルタ", padding="10")
        domains_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(domains_frame, text="許可する送信元（カンマ区切り）:").pack(anchor="w")
        self.from_domains_var = tk.StringVar(value=self.config['FROM_DOMAINS'])
        domains_entry = ttk.Entry(domains_frame, textvariable=self.from_domains_var, width=80)
        domains_entry.pack(fill="x", pady=5)
        
        ttk.Label(domains_frame, text="例: bosai-jma@jmainfo.go.jp,alerts@example.com", foreground="gray").pack(anchor="w")
    
    def create_mqtt_tab(self, notebook):
        """MQTT設定タブ"""
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="MQTT")
        
        main_frame = ttk.Frame(tab, padding="20")
        main_frame.pack(fill="both", expand=True)
        
        # 接続設定
        conn_frame = ttk.LabelFrame(main_frame, text="MQTT接続設定", padding="10")
        conn_frame.pack(fill="x", pady=(0, 10))
        
        # MQTTホスト
        host_frame = ttk.Frame(conn_frame)
        host_frame.pack(fill="x", pady=2)
        ttk.Label(host_frame, text="MQTTホスト:", width=12).pack(side="left")
        self.mqtt_host_var = tk.StringVar(value=self.config['MQTT_HOST'])
        ttk.Entry(host_frame, textvariable=self.mqtt_host_var).pack(side="right", fill="x", expand=True, padx=(10, 0))
        
        # ポート
        port_frame = ttk.Frame(conn_frame)
        port_frame.pack(fill="x", pady=2)
        ttk.Label(port_frame, text="ポート:", width=12).pack(side="left")
        self.mqtt_port_var = tk.StringVar(value=self.config['MQTT_PORT'])
        port_entry = ttk.Entry(port_frame, textvariable=self.mqtt_port_var, width=10)
        port_entry.pack(side="left", padx=(10, 0))
        
        # ユーザー名
        user_frame = ttk.Frame(conn_frame)
        user_frame.pack(fill="x", pady=2)
        ttk.Label(user_frame, text="ユーザー名:", width=12).pack(side="left")
        self.mqtt_user_var = tk.StringVar(value=self.config['MQTT_USER'])
        ttk.Entry(user_frame, textvariable=self.mqtt_user_var).pack(side="right", fill="x", expand=True, padx=(10, 0))
        
        # パスワード
        pass_frame = ttk.Frame(conn_frame)
        pass_frame.pack(fill="x", pady=2)
        ttk.Label(pass_frame, text="パスワード:", width=12).pack(side="left")
        self.mqtt_pass_var = tk.StringVar(value=self.config['MQTT_PASS'])
        ttk.Entry(pass_frame, textvariable=self.mqtt_pass_var, show="*").pack(side="right", fill="x", expand=True, padx=(10, 0))
        
        # TLS設定をスクロール可能にする
        tls_canvas = tk.Canvas(main_frame)
        tls_scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=tls_canvas.yview)
        tls_scrollable_frame = ttk.Frame(tls_canvas)
        
        tls_scrollable_frame.bind(
            "<Configure>",
            lambda e: tls_canvas.configure(scrollregion=tls_canvas.bbox("all"))
        )
        
        tls_canvas.create_window((0, 0), window=tls_scrollable_frame, anchor="nw")
        tls_canvas.configure(yscrollcommand=tls_scrollbar.set)
        
        # TLS設定フレーム
        tls_frame = ttk.LabelFrame(tls_scrollable_frame, text="TLS設定", padding="10")
        tls_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        self.mqtt_tls_var = tk.BooleanVar(value=self.config['MQTT_TLS'].lower() == 'true')
        ttk.Checkbutton(tls_frame, text="TLS/SSL使用", variable=self.mqtt_tls_var, command=self._on_tls_toggle).pack(anchor="w", pady=2)
        
        # Let's Encrypt設定
        letsencrypt_frame = ttk.LabelFrame(tls_frame, text="Let's Encrypt設定", padding="5")
        letsencrypt_frame.pack(fill="x", pady=5)
        
        domain_frame = ttk.Frame(letsencrypt_frame)
        domain_frame.pack(fill="x", pady=2)
        ttk.Label(domain_frame, text="ドメイン:").pack(side="left")
        self.letsencrypt_domain_var = tk.StringVar(value=self.config['LETSENCRYPT_DOMAIN'])
        domain_entry = ttk.Entry(domain_frame, textvariable=self.letsencrypt_domain_var, width=50)
        domain_entry.pack(side="right", fill="x", expand=True, padx=(10, 0))
        
        ttk.Label(letsencrypt_frame, text="例: your-domain.duckdns.org", foreground="gray").pack(anchor="w")
        
        self.mqtt_use_system_ca_var = tk.BooleanVar(value=self.config['MQTT_USE_SYSTEM_CA'].lower() == 'true')
        ttk.Checkbutton(letsencrypt_frame, text="システム証明書ストアを使用（Let's Encrypt推奨）", 
                       variable=self.mqtt_use_system_ca_var).pack(anchor="w", pady=2)
        
        # 証明書ファイル設定（上級者向け）
        cert_frame = ttk.LabelFrame(tls_frame, text="証明書ファイル（上級者向け）", padding="5")
        cert_frame.pack(fill="x", pady=5)
        
        # CAファイル
        ca_frame = ttk.Frame(cert_frame)
        ca_frame.pack(fill="x", pady=2)
        ttk.Label(ca_frame, text="CAファイル:", width=12).pack(side="left")
        self.mqtt_cafile_var = tk.StringVar(value=self.config['MQTT_CAFILE'])
        ca_entry = ttk.Entry(ca_frame, textvariable=self.mqtt_cafile_var)
        ca_entry.pack(side="left", fill="x", expand=True, padx=(5, 5))
        ttk.Button(ca_frame, text="参照", width=8, command=lambda: self._browse_file(self.mqtt_cafile_var)).pack(side="right")
        
        # 証明書ファイル
        cert_file_frame = ttk.Frame(cert_frame)
        cert_file_frame.pack(fill="x", pady=2)
        ttk.Label(cert_file_frame, text="証明書:", width=12).pack(side="left")
        self.mqtt_certfile_var = tk.StringVar(value=self.config['MQTT_CERTFILE'])
        cert_entry = ttk.Entry(cert_file_frame, textvariable=self.mqtt_certfile_var)
        cert_entry.pack(side="left", fill="x", expand=True, padx=(5, 5))
        ttk.Button(cert_file_frame, text="参照", width=8, command=lambda: self._browse_file(self.mqtt_certfile_var)).pack(side="right")
        
        # 秘密鍵ファイル
        key_frame = ttk.Frame(cert_frame)
        key_frame.pack(fill="x", pady=2)
        ttk.Label(key_frame, text="秘密鍵:", width=12).pack(side="left")
        self.mqtt_keyfile_var = tk.StringVar(value=self.config['MQTT_KEYFILE'])
        key_entry = ttk.Entry(key_frame, textvariable=self.mqtt_keyfile_var)
        key_entry.pack(side="left", fill="x", expand=True, padx=(5, 5))
        ttk.Button(key_frame, text="参照", width=8, command=lambda: self._browse_file(self.mqtt_keyfile_var)).pack(side="right")
        
        # その他のTLS設定
        self.mqtt_tls_insecure_var = tk.BooleanVar(value=self.config['MQTT_TLS_INSECURE'].lower() == 'true')
        ttk.Checkbutton(tls_frame, text="証明書検証をスキップ（テスト用のみ）", variable=self.mqtt_tls_insecure_var).pack(anchor="w", pady=2)
        
        # キャンバスとスクロールバーを配置
        tls_canvas.pack(side="left", fill="both", expand=True)
        tls_scrollbar.pack(side="right", fill="y")
        
        # パブリッシュ設定
        pub_frame = ttk.LabelFrame(main_frame, text="パブリッシュ設定", padding="10")
        pub_frame.pack(fill="x", pady=(0, 10))
        
        # トピック
        topic_frame = ttk.Frame(pub_frame)
        topic_frame.pack(fill="x", pady=2)
        ttk.Label(topic_frame, text="トピック:", width=12).pack(side="left")
        self.mqtt_topic_var = tk.StringVar(value=self.config['MQTT_TOPIC'])
        topic_entry = ttk.Entry(topic_frame, textvariable=self.mqtt_topic_var)
        topic_entry.pack(side="right", fill="x", expand=True, padx=(10, 0))
        
        # トピックのヒントを追加
        hint_frame = ttk.Frame(pub_frame)
        hint_frame.pack(fill="x", pady=(0, 5))
        ttk.Label(hint_frame, text="", width=12).pack(side="left")  # スペーサー
        hint_label = ttk.Label(hint_frame, text="※ パブリッシュ用トピックです。ワイルドカード（# +）は使用できません。", 
                              font=("", 8), foreground="gray")
        hint_label.pack(side="left", padx=(10, 0))
        
        # クライアントID
        client_frame = ttk.Frame(pub_frame)
        client_frame.pack(fill="x", pady=2)
        ttk.Label(client_frame, text="クライアントID:", width=12).pack(side="left")
        self.mqtt_client_id_var = tk.StringVar(value=self.config['MQTT_CLIENT_ID'])
        ttk.Entry(client_frame, textvariable=self.mqtt_client_id_var).pack(side="right", fill="x", expand=True, padx=(10, 0))
        
        # QoS
        qos_frame = ttk.Frame(pub_frame)
        qos_frame.pack(fill="x", pady=2)
        ttk.Label(qos_frame, text="QoS:", width=12).pack(side="left")
        self.mqtt_qos_var = tk.StringVar(value=self.config['MQTT_QOS'])
        qos_combo = ttk.Combobox(qos_frame, textvariable=self.mqtt_qos_var, values=['0', '1', '2'], width=5)
        qos_combo.pack(side="left", padx=(10, 0))
        qos_combo.state(['readonly'])
        
        # Retain フラグ
        self.mqtt_retain_var = tk.BooleanVar(value=self.config['MQTT_RETAIN'].lower() == 'true')
        ttk.Checkbutton(pub_frame, text="Retain フラグ", variable=self.mqtt_retain_var).pack(anchor="w", pady=2)
        
        # テストボタン
        test_frame = ttk.Frame(main_frame)
        test_frame.pack(fill="x", pady=10)
        ttk.Button(test_frame, text="MQTT接続テスト", command=self.test_mqtt_connection).pack(side="left")
    
    def create_advanced_tab(self, notebook):
        """高度な設定タブ"""
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="高度な設定")
        
        main_frame = ttk.Frame(tab, padding="20")
        main_frame.pack(fill="both", expand=True)
        
        # ログ設定
        log_frame = ttk.LabelFrame(main_frame, text="ログ設定", padding="10")
        log_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(log_frame, text="ログレベル:").grid(row=0, column=0, sticky="w", pady=5)
        self.log_level_var = tk.StringVar(value=self.config['LOG_LEVEL'])
        log_combo = ttk.Combobox(log_frame, textvariable=self.log_level_var, 
                                values=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], width=15)
        log_combo.grid(row=0, column=1, sticky="w", padx=(10, 0))
        log_combo.state(['readonly'])
        
        # 設定ファイル管理
        file_frame = ttk.LabelFrame(main_frame, text="設定ファイル管理", padding="10")
        file_frame.pack(fill="x", pady=(0, 10))
        
        btn_frame = ttk.Frame(file_frame)
        btn_frame.pack(fill="x")
        
        ttk.Button(btn_frame, text="設定をJSONで保存", command=self.export_json).pack(side="left", padx=(0, 10))
        ttk.Button(btn_frame, text="JSONから設定を読込", command=self.import_json).pack(side="left", padx=(0, 10))
        ttk.Button(btn_frame, text=".envファイルを開く", command=self.open_env_file).pack(side="left")
        
        # 現在の設定表示
        current_frame = ttk.LabelFrame(main_frame, text="現在の設定状況", padding="10")
        current_frame.pack(fill="both", expand=True, pady=(10, 0))
        
        self.status_text = tk.Text(current_frame, height=8, wrap="word")
        status_scroll = ttk.Scrollbar(current_frame, command=self.status_text.yview)
        self.status_text.config(yscrollcommand=status_scroll.set)
        
        self.status_text.pack(side="left", fill="both", expand=True)
        status_scroll.pack(side="right", fill="y")
        
        self.update_status_display()
    
    def create_button_frame(self):
        """下部のボタンフレーム"""
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill="x", padx=10, pady=10)
        
        ttk.Button(btn_frame, text="設定を保存", command=self.save_config, 
                  style="Accent.TButton").pack(side="right", padx=(10, 0))
        ttk.Button(btn_frame, text="キャンセル", command=self.root.quit).pack(side="right")
        ttk.Button(btn_frame, text="設定をリロード", command=self.reload_config).pack(side="left")
        ttk.Button(btn_frame, text="デフォルトに戻す", command=self.reset_to_default).pack(side="left", padx=(10, 0))
    
    def center_window(self):
        """ウィンドウを画面中央に配置"""
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')
    
    def get_current_config(self):
        """現在のUI値から設定辞書を作成"""
        return {
            'GMAIL_USER': self.gmail_user_var.get(),
            'GMAIL_PASS': self.gmail_pass_var.get(),
            'IMAP_FOLDER': self.imap_folder_var.get(),
            'IDLE_TIMEOUT': self.idle_timeout_var.get(),
            'FETCH_BODY_LIMIT': self.fetch_body_limit_var.get(),
            'POLL_ON_WAKE': 'true' if self.poll_on_wake_var.get() else 'false',
            
            'SEARCH_KEYWORDS': self.search_keywords_var.get(),
            'FROM_DOMAINS': self.from_domains_var.get(),
            
            'MQTT_HOST': self.mqtt_host_var.get(),
            'MQTT_PORT': self.mqtt_port_var.get(),
            'MQTT_TLS': 'true' if self.mqtt_tls_var.get() else 'false',
            'MQTT_USER': self.mqtt_user_var.get(),
            'MQTT_PASS': self.mqtt_pass_var.get(),
            'MQTT_TOPIC': self.mqtt_topic_var.get() or 'inbox/matches',
            'MQTT_CLIENT_ID': self.mqtt_client_id_var.get(),
            'MQTT_QOS': self.mqtt_qos_var.get(),
            'MQTT_RETAIN': 'true' if self.mqtt_retain_var.get() else 'false',
            'MQTT_TLS_INSECURE': 'true' if self.mqtt_tls_insecure_var.get() else 'false',
            'MQTT_CAFILE': self.mqtt_cafile_var.get(),
            'MQTT_CERTFILE': self.mqtt_certfile_var.get(),
            'MQTT_KEYFILE': self.mqtt_keyfile_var.get(),
            'MQTT_USE_SYSTEM_CA': 'true' if self.mqtt_use_system_ca_var.get() else 'false',
            'LETSENCRYPT_DOMAIN': self.letsencrypt_domain_var.get(),
            
            'LOG_LEVEL': self.log_level_var.get()
        }
    
    def save_config(self):
        """設定を.envファイルに保存"""
        try:
            config = self.get_current_config()
            
            # 基本的な検証
            if not config['GMAIL_USER'] or not config['GMAIL_PASS']:
                messagebox.showerror("設定エラー", "Gmail認証情報は必須です。")
                return
            
            if not config['MQTT_HOST']:
                messagebox.showerror("設定エラー", "MQTTホストは必須です。")
                return
                
            if not config['MQTT_TOPIC']:
                messagebox.showerror("設定エラー", "MQTTトピックは必須です。")
                return
            
            # MQTTトピックにワイルドカード文字が含まれていないかチェック（パブリッシュ用）
            if '#' in config['MQTT_TOPIC'] or '+' in config['MQTT_TOPIC']:
                messagebox.showerror("設定エラー", "MQTTトピックにワイルドカード文字（# または +）は使用できません。\n具体的なトピック名を指定してください。")
                return
            
            try:
                int(config['MQTT_PORT'])
                int(config['IDLE_TIMEOUT'])
                int(config['FETCH_BODY_LIMIT'])
                int(config['MQTT_QOS'])
            except ValueError:
                messagebox.showerror("設定エラー", "数値フィールドに正しい値を入力してください。")
                return
            
            # .envファイルに保存
            env_path = ".env"
            env_content = []
            
            # 既存の.envファイルを読み込み、非設定項目を保持
            if os.path.exists(env_path):
                with open(env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key = line.split('=', 1)[0]
                            if key not in config:
                                env_content.append(line)
                        elif not line or line.startswith('#'):
                            env_content.append(line)
            
            # 設定項目を追加
            env_content.extend([
                "",
                "# --- Gmail/IMAP Configuration ---",
                f"GMAIL_USER={config['GMAIL_USER']}",
                f"GMAIL_PASS={config['GMAIL_PASS']}",
                f"IMAP_FOLDER={config['IMAP_FOLDER']}",
                f"IDLE_TIMEOUT={config['IDLE_TIMEOUT']}",
                f"FETCH_BODY_LIMIT={config['FETCH_BODY_LIMIT']}",
                f"POLL_ON_WAKE={config['POLL_ON_WAKE']}",
                "",
                "# --- Search Configuration ---",
                f"SEARCH_KEYWORDS={config['SEARCH_KEYWORDS']}",
                f"FROM_DOMAINS={config['FROM_DOMAINS']}",
                "",
                "# --- MQTT Configuration ---",
                f"MQTT_HOST={config['MQTT_HOST']}",
                f"MQTT_PORT={config['MQTT_PORT']}",
                f"MQTT_TLS={config['MQTT_TLS']}",
                f"MQTT_USER={config['MQTT_USER']}",
                f"MQTT_PASS={config['MQTT_PASS']}",
                f"MQTT_TOPIC={config['MQTT_TOPIC']}",
                f"MQTT_CLIENT_ID={config['MQTT_CLIENT_ID']}",
                f"MQTT_QOS={config['MQTT_QOS']}",
                f"MQTT_RETAIN={config['MQTT_RETAIN']}",
                f"MQTT_TLS_INSECURE={config['MQTT_TLS_INSECURE']}",
                f"MQTT_CAFILE={config['MQTT_CAFILE']}",
                f"MQTT_CERTFILE={config['MQTT_CERTFILE']}",
                f"MQTT_KEYFILE={config['MQTT_KEYFILE']}",
                f"MQTT_USE_SYSTEM_CA={config['MQTT_USE_SYSTEM_CA']}",
                "",
                "# --- Let's Encrypt Configuration ---",
                f"LETSENCRYPT_DOMAIN={config['LETSENCRYPT_DOMAIN']}",
                "",
                "# --- Logging ---",
                f"LOG_LEVEL={config['LOG_LEVEL']}"
            ])
            
            with open(env_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(env_content))
            
            messagebox.showinfo("保存完了", f"設定が {env_path} に保存されました。")
            self.update_status_display()
            
        except Exception as e:
            messagebox.showerror("保存エラー", f"設定の保存に失敗しました:\n{str(e)}")
    
    def reload_config(self):
        """設定をリロード"""
        self.config = self.load_config()
        self.update_ui_from_config()
        self.update_status_display()
        messagebox.showinfo("リロード完了", "設定をリロードしました。")
    
    def reset_to_default(self):
        """デフォルト設定にリセット"""
        if messagebox.askyesno("確認", "設定をデフォルトにリセットしますか？"):
            default_config = {
                'GMAIL_USER': '',
                'GMAIL_PASS': '',
                'IMAP_FOLDER': 'INBOX',
                'IDLE_TIMEOUT': '300',
                'FETCH_BODY_LIMIT': '4000',
                'POLL_ON_WAKE': 'False',
                'SEARCH_KEYWORDS': '地震情報,津波情報',
                'FROM_DOMAINS': 'bosai-jma@jmainfo.go.jp',
                'MQTT_HOST': 'localhost',
                'MQTT_PORT': '8883',
                'MQTT_TLS': 'true',
                'MQTT_USER': '',
                'MQTT_PASS': '',
                'MQTT_TOPIC': 'inbox/matches',
                'MQTT_CLIENT_ID': '',
                'MQTT_QOS': '1',
                'MQTT_RETAIN': 'false',
                'MQTT_TLS_INSECURE': 'false',
                'MQTT_CAFILE': '',
                'MQTT_CERTFILE': '',
                'MQTT_KEYFILE': '',
                'MQTT_USE_SYSTEM_CA': 'true',
                'LETSENCRYPT_DOMAIN': '',
                'LOG_LEVEL': 'INFO'
            }
            self.config = default_config
            self.update_ui_from_config()
    
    def update_ui_from_config(self):
        """設定からUIを更新"""
        self.gmail_user_var.set(self.config['GMAIL_USER'])
        self.gmail_pass_var.set(self.config['GMAIL_PASS'])
        self.imap_folder_var.set(self.config['IMAP_FOLDER'])
        self.idle_timeout_var.set(self.config['IDLE_TIMEOUT'])
        self.fetch_body_limit_var.set(self.config['FETCH_BODY_LIMIT'])
        self.poll_on_wake_var.set(self.config['POLL_ON_WAKE'].lower() == 'true')
        
        self.search_keywords_var.set(self.config['SEARCH_KEYWORDS'])
        self.from_domains_var.set(self.config['FROM_DOMAINS'])
        
        self.mqtt_host_var.set(self.config['MQTT_HOST'])
        self.mqtt_port_var.set(self.config['MQTT_PORT'])
        self.mqtt_tls_var.set(self.config['MQTT_TLS'].lower() == 'true')
        self.mqtt_user_var.set(self.config['MQTT_USER'])
        self.mqtt_pass_var.set(self.config['MQTT_PASS'])
        self.mqtt_topic_var.set(self.config['MQTT_TOPIC'])
        self.mqtt_client_id_var.set(self.config['MQTT_CLIENT_ID'])
        self.mqtt_qos_var.set(self.config['MQTT_QOS'])
        self.mqtt_retain_var.set(self.config['MQTT_RETAIN'].lower() == 'true')
        self.mqtt_tls_insecure_var.set(self.config['MQTT_TLS_INSECURE'].lower() == 'true')
        self.mqtt_cafile_var.set(self.config['MQTT_CAFILE'])
        self.mqtt_certfile_var.set(self.config['MQTT_CERTFILE'])
        self.mqtt_keyfile_var.set(self.config['MQTT_KEYFILE'])
        self.mqtt_use_system_ca_var.set(self.config['MQTT_USE_SYSTEM_CA'].lower() == 'true')
        self.letsencrypt_domain_var.set(self.config['LETSENCRYPT_DOMAIN'])
        
        self.log_level_var.set(self.config['LOG_LEVEL'])
    
    def update_status_display(self):
        """ステータス表示を更新"""
        self.status_text.delete(1.0, tk.END)
        
        status_info = []
        status_info.append(f"Gmail: {'設定済み' if self.config['GMAIL_USER'] else '未設定'}")
        status_info.append(f"MQTT: {self.config['MQTT_HOST']}:{self.config['MQTT_PORT']}")
        status_info.append(f"TLS: {'有効' if self.config['MQTT_TLS'].lower() == 'true' else '無効'}")
        status_info.append(f"監視フォルダ: {self.config['IMAP_FOLDER']}")
        status_info.append(f"検索キーワード数: {len(self.config['SEARCH_KEYWORDS'].split(','))}")
        status_info.append(f"Let's Encrypt: {'有効' if self.config['LETSENCRYPT_DOMAIN'] else '無効'}")
        status_info.append(f"システムCA: {'使用' if self.config['MQTT_USE_SYSTEM_CA'].lower() == 'true' else '未使用'}")
        
        env_path = ".env"
        if os.path.exists(env_path):
            status_info.append(f".envファイル: 存在 ({os.path.getsize(env_path)} bytes)")
        else:
            status_info.append(".envファイル: 存在しません")
        
        self.status_text.insert(1.0, "\n".join(status_info))
    
    def test_gmail_connection(self):
        """Gmail接続テスト"""
        def test_connection():
            try:
                config = self.get_current_config()
                if not config['GMAIL_USER'] or not config['GMAIL_PASS']:
                    messagebox.showerror("テストエラー", "Gmail認証情報を入力してください。")
                    return
                
                messagebox.showinfo("接続テスト", "Gmail接続をテストしています...\n少々お待ちください。")
                
                context = ssl.create_default_context()
                with IMAPClient('imap.gmail.com', port=993, ssl=True, ssl_context=context) as conn:
                    conn.login(config['GMAIL_USER'], config['GMAIL_PASS'])
                    folders = conn.list_folders()
                    
                messagebox.showinfo("接続テスト成功", 
                                  f"Gmail接続に成功しました。\n利用可能フォルダ数: {len(folders)}")
                
            except Exception as e:
                messagebox.showerror("接続テスト失敗", f"Gmail接続に失敗しました:\n{str(e)}")
        
        threading.Thread(target=test_connection, daemon=True).start()
    
    def test_mqtt_connection(self):
        """MQTT接続テスト"""
        def test_connection():
            try:
                config = self.get_current_config()
                if not config['MQTT_HOST']:
                    messagebox.showerror("テストエラー", "MQTTホストを入力してください。")
                    return
                
                messagebox.showinfo("接続テスト", "MQTT接続をテストしています...\n少々お待ちください。")
                
                client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
                if config['MQTT_USER'] and config['MQTT_PASS']:
                    client.username_pw_set(config['MQTT_USER'], config['MQTT_PASS'])
                
                if config['MQTT_TLS'].lower() == 'true':
                    # TLS設定
                    ca_certs = None
                    certfile = None
                    keyfile = None
                    
                    # Let's Encrypt/システム証明書を使用
                    if config['MQTT_USE_SYSTEM_CA'].lower() == 'true':
                        # システムの証明書ストアを使用（Let's Encrypt対応）
                        ca_certs = None
                    else:
                        # 手動指定のCA証明書を使用
                        ca_certs = config['MQTT_CAFILE'] if config['MQTT_CAFILE'] else None
                    
                    # クライアント証明書（必要な場合）
                    if config['MQTT_CERTFILE'] and config['MQTT_KEYFILE']:
                        certfile = config['MQTT_CERTFILE']
                        keyfile = config['MQTT_KEYFILE']
                    
                    client.tls_set(ca_certs=ca_certs, certfile=certfile, keyfile=keyfile)
                    
                    if config['MQTT_TLS_INSECURE'].lower() == 'true':
                        client.tls_insecure_set(True)
                
                client.connect(config['MQTT_HOST'], int(config['MQTT_PORT']), keepalive=10)
                client.disconnect()
                
                messagebox.showinfo("接続テスト成功", 
                                  f"MQTT接続に成功しました。\nブローカー: {config['MQTT_HOST']}:{config['MQTT_PORT']}")
                
            except Exception as e:
                messagebox.showerror("接続テスト失敗", f"MQTT接続に失敗しました:\n{str(e)}")
        
        threading.Thread(target=test_connection, daemon=True).start()
    
    def export_json(self):
        """設定をJSONファイルにエクスポート"""
        try:
            filename = filedialog.asksaveasfilename(
                defaultextension=".json",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
                title="設定をJSON形式で保存"
            )
            
            if filename:
                config = self.get_current_config()
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
                messagebox.showinfo("エクスポート完了", f"設定を {filename} に保存しました。")
                
        except Exception as e:
            messagebox.showerror("エクスポートエラー", f"設定のエクスポートに失敗しました:\n{str(e)}")
    
    def import_json(self):
        """JSONファイルから設定をインポート"""
        try:
            filename = filedialog.askopenfilename(
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
                title="設定JSONファイルを選択"
            )
            
            if filename:
                with open(filename, 'r', encoding='utf-8') as f:
                    imported_config = json.load(f)
                
                # 設定を更新
                self.config.update(imported_config)
                self.update_ui_from_config()
                self.update_status_display()
                
                messagebox.showinfo("インポート完了", f"{filename} から設定を読み込みました。")
                
        except Exception as e:
            messagebox.showerror("インポートエラー", f"設定のインポートに失敗しました:\n{str(e)}")
    
    def open_env_file(self):
        """システムの既定のエディタで.envファイルを開く"""
        env_path = ".env"
        if not os.path.exists(env_path):
            if messagebox.askyesno("ファイル作成", ".envファイルが存在しません。作成しますか？"):
                with open(env_path, 'w', encoding='utf-8') as f:
                    f.write("# Gmail MQTT Monitor Configuration\n")
        
        try:
            if os.name == 'nt':  # Windows
                os.startfile(env_path)
            elif os.name == 'posix':  # macOS/Linux
                os.system(f'open "{env_path}"' if os.uname().sysname == 'Darwin' else f'xdg-open "{env_path}"')
        except Exception as e:
            messagebox.showerror("ファイルオープンエラー", f".envファイルを開けませんでした:\n{str(e)}")
    
    def _browse_file(self, var):
        """ファイル参照ダイアログを開く"""
        filename = filedialog.askopenfilename(
            title="証明書ファイルを選択",
            filetypes=[
                ("証明書ファイル", "*.pem *.crt *.cer"),
                ("秘密鍵ファイル", "*.key *.pem"),
                ("すべてのファイル", "*.*")
            ]
        )
        if filename:
            var.set(filename)
    
    def _on_tls_toggle(self):
        """TLSチェックボックスの状態変更時の処理"""
        pass  # 必要に応じて追加の処理を実装
    
    def run(self):
        """アプリケーションを実行"""
        self.root.mainloop()

def main():
    """メイン関数"""
    try:
        app = SettingsApp()
        app.run()
    except Exception as e:
        messagebox.showerror("アプリケーションエラー", f"アプリケーションの起動に失敗しました:\n{str(e)}")

if __name__ == "__main__":
    main()