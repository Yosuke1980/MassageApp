#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MQTT を購読し、受信ごとにポップアップウィンドウを前面表示して本文を見せる。
Publisher が publish する JSON は以下を想定:
  { uid, message_id, date, from, subject, body }
"""
import os, json, queue, threading
import tkinter as tk
from tkinter import ttk, messagebox
import paho.mqtt.client as mqtt
from dotenv import load_dotenv
try:
    import pystray
    from pystray import MenuItem as item
    from PIL import Image
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False
    print("Note: pystray not available. System tray functionality disabled.")

# Load environment variables
load_dotenv()

# Global configuration variables
config = {
    'MQTT_HOST': os.environ.get('MQTT_HOST', 'localhost'),
    'MQTT_PORT': int(os.environ.get('MQTT_PORT', '1883')),
    'MQTT_TLS': os.environ.get('MQTT_TLS', 'false').lower() == 'true',
    'MQTT_TOPIC': os.environ.get('MQTT_TOPIC', 'inbox/matches'),
    'MQTT_USER': os.environ.get('MQTT_USER', ''),
    'MQTT_PASS': os.environ.get('MQTT_PASS', ''),
    'MQTT_TLS_INSECURE': os.environ.get('MQTT_TLS_INSECURE', 'false').lower() == 'true'
}

inbox_q = queue.Queue()
seen_uids = set()
mqtt_thread = None
mqtt_client = None

def mqtt_worker():
    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            print("MQTT connected successfully")
            client.subscribe(config['MQTT_TOPIC'], qos=1)
        else:
            print("MQTT connect failed rc=", rc)
    
    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
            uid = payload.get("uid")
            if uid and uid not in seen_uids:
                seen_uids.add(uid)
                inbox_q.put(payload)
                print(f"New message queued: UID={uid}, Subject={payload.get('subject', '')}")
        except json.JSONDecodeError:
            print("Failed to parse MQTT message JSON")
        except Exception as e:
            print(f"Error processing MQTT message: {e}")
    
    def on_disconnect(client, userdata, rc):
        print(f"MQTT disconnected with code: {rc}")
        if rc != 0:
            print("Unexpected disconnection, attempting to reconnect...")
    
    try:
        c = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        c.username_pw_set(config['MQTT_USER'], config['MQTT_PASS'])
        if config['MQTT_TLS']:
            # Use system's default certificate store (includes Let's Encrypt certificates)
            c.tls_set()
            if config['MQTT_TLS_INSECURE']:
                c.tls_insecure_set(True)
        c.on_connect = on_connect
        c.on_message = on_message
        c.on_disconnect = on_disconnect
        print("→ connecting to", config['MQTT_HOST'], ":", config['MQTT_PORT'])
        c.connect(config['MQTT_HOST'], config['MQTT_PORT'], keepalive=60)
        c.loop_forever()
    except Exception as e:
        print(f"MQTT connection error: {e}")
        print("Please check network connectivity and MQTT broker status")


class SettingsDialog:
    def __init__(self, parent, config, on_save_callback=None):
        self.parent = parent
        self.config = config.copy()
        self.on_save_callback = on_save_callback
        self.create_dialog()
    
    def create_dialog(self):
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("MQTT Settings")
        self.dialog.geometry("500x400")
        self.dialog.transient(self.parent)
        self.dialog.grab_set()
        
        # Center the dialog
        self.dialog.update_idletasks()
        sw, sh = self.dialog.winfo_screenwidth(), self.dialog.winfo_screenheight()
        dw, dh = 500, 400
        x, y = int((sw-dw)/2), int((sh-dh)/2)
        self.dialog.geometry(f"{dw}x{dh}+{x}+{y}")
        
        main_frame = ttk.Frame(self.dialog, padding="20")
        main_frame.pack(fill="both", expand=True)
        
        # MQTT Host
        ttk.Label(main_frame, text="MQTT Host:").grid(row=0, column=0, sticky="w", pady=5)
        self.host_var = tk.StringVar(value=self.config['MQTT_HOST'])
        ttk.Entry(main_frame, textvariable=self.host_var, width=40).grid(row=0, column=1, sticky="ew", padx=(10, 0))
        
        # MQTT Port
        ttk.Label(main_frame, text="MQTT Port:").grid(row=1, column=0, sticky="w", pady=5)
        self.port_var = tk.StringVar(value=str(self.config['MQTT_PORT']))
        ttk.Entry(main_frame, textvariable=self.port_var, width=40).grid(row=1, column=1, sticky="ew", padx=(10, 0))
        
        # MQTT Topic
        ttk.Label(main_frame, text="MQTT Topic:").grid(row=2, column=0, sticky="w", pady=5)
        self.topic_var = tk.StringVar(value=self.config['MQTT_TOPIC'])
        ttk.Entry(main_frame, textvariable=self.topic_var, width=40).grid(row=2, column=1, sticky="ew", padx=(10, 0))
        
        # MQTT Username
        ttk.Label(main_frame, text="Username:").grid(row=3, column=0, sticky="w", pady=5)
        self.user_var = tk.StringVar(value=self.config['MQTT_USER'])
        ttk.Entry(main_frame, textvariable=self.user_var, width=40).grid(row=3, column=1, sticky="ew", padx=(10, 0))
        
        # MQTT Password
        ttk.Label(main_frame, text="Password:").grid(row=4, column=0, sticky="w", pady=5)
        self.pass_var = tk.StringVar(value=self.config['MQTT_PASS'])
        ttk.Entry(main_frame, textvariable=self.pass_var, width=40, show="*").grid(row=4, column=1, sticky="ew", padx=(10, 0))
        
        # TLS Options
        self.tls_var = tk.BooleanVar(value=self.config['MQTT_TLS'])
        ttk.Checkbutton(main_frame, text="Use TLS/SSL", variable=self.tls_var).grid(row=5, column=0, columnspan=2, sticky="w", pady=5)
        
        self.tls_insecure_var = tk.BooleanVar(value=self.config['MQTT_TLS_INSECURE'])
        ttk.Checkbutton(main_frame, text="Allow insecure TLS (for testing only)", variable=self.tls_insecure_var).grid(row=6, column=0, columnspan=2, sticky="w", pady=5)
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=7, column=0, columnspan=2, pady=20, sticky="ew")
        
        ttk.Button(button_frame, text="Save", command=self.save_settings).pack(side="right", padx=(5, 0))
        ttk.Button(button_frame, text="Cancel", command=self.dialog.destroy).pack(side="right")
        ttk.Button(button_frame, text="Test Connection", command=self.test_connection).pack(side="left")
        
        main_frame.columnconfigure(1, weight=1)
    
    def test_connection(self):
        # Simple connection test
        test_config = self.get_current_config()
        messagebox.showinfo("Test Connection", f"Testing connection to {test_config['MQTT_HOST']}:{test_config['MQTT_PORT']}...\n(Full test not implemented yet)", parent=self.dialog)
    
    def get_current_config(self):
        try:
            return {
                'MQTT_HOST': self.host_var.get(),
                'MQTT_PORT': int(self.port_var.get()),
                'MQTT_TOPIC': self.topic_var.get(),
                'MQTT_USER': self.user_var.get(),
                'MQTT_PASS': self.pass_var.get(),
                'MQTT_TLS': self.tls_var.get(),
                'MQTT_TLS_INSECURE': self.tls_insecure_var.get()
            }
        except ValueError:
            messagebox.showerror("Invalid Input", "Port must be a valid number", parent=self.dialog)
            return None
    
    def save_settings(self):
        new_config = self.get_current_config()
        if new_config:
            if self.on_save_callback:
                self.on_save_callback(new_config)
            self.dialog.destroy()

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("MQTT Mail Popup")
        self.root.withdraw()  # Hide main window
        
        # Create system tray icon if available
        if TRAY_AVAILABLE:
            self.create_tray_icon()
        else:
            # Show a simple control window if no tray support
            self.create_control_window()
        
        self.poll_queue()
    
    def create_tray_icon(self):
        # Create a simple icon (you may want to use a proper icon file)
        try:
            # Create a simple colored icon
            image = Image.new('RGB', (64, 64), color='blue')
            self.icon = pystray.Icon("MQTT Mail Popup", image, menu=pystray.Menu(
                item('Settings', self.show_settings),
                item('Show Window', self.show_window),
                pystray.Menu.SEPARATOR,
                item('Quit', self.quit_application)
            ))
            
            # Start the tray icon in a separate thread
            threading.Thread(target=self.icon.run, daemon=True).start()
        except Exception as e:
            print(f"Failed to create tray icon: {e}")
            self.create_control_window()
    
    def create_control_window(self):
        # Simple control window for systems without tray support
        self.control = tk.Toplevel(self.root)
        self.control.title("MQTT Mail Popup - Controls")
        self.control.geometry("250x150")
        
        frame = ttk.Frame(self.control, padding="10")
        frame.pack(fill="both", expand=True)
        
        ttk.Label(frame, text="MQTT Mail Popup Running").pack(pady=5)
        ttk.Button(frame, text="Settings", command=self.show_settings).pack(pady=5, fill="x")
        ttk.Button(frame, text="Quit", command=self.quit_application).pack(pady=5, fill="x")
        
        self.control.protocol("WM_DELETE_WINDOW", self.hide_control_window)
    
    def hide_control_window(self):
        self.control.withdraw()
    
    def show_window(self):
        if hasattr(self, 'control'):
            self.control.deiconify()
            self.control.lift()
    
    def show_settings(self):
        SettingsDialog(self.root, config, self.on_settings_saved)
    
    def on_settings_saved(self, new_config):
        global config, mqtt_thread, mqtt_client
        config.update(new_config)
        self.save_config_to_env()
        messagebox.showinfo("Settings Saved", "Settings have been saved. Restart the application to apply MQTT changes.")
    
    def save_config_to_env(self):
        env_content = []
        env_path = ".env"
        
        # Read existing .env file and preserve non-MQTT settings
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key = line.split('=', 1)[0]
                        if not key.startswith('MQTT_'):
                            env_content.append(line)
                    else:
                        env_content.append(line)
        
        # Add MQTT settings
        env_content.extend([
            "# --- MQTT ---",
            f"MQTT_HOST={config['MQTT_HOST']}",
            f"MQTT_PORT={config['MQTT_PORT']}",
            f"MQTT_TLS={'true' if config['MQTT_TLS'] else 'false'}",
            f"MQTT_TOPIC={config['MQTT_TOPIC']}",
            f"MQTT_USER={config['MQTT_USER']}",
            f"MQTT_PASS={config['MQTT_PASS']}",
            f"MQTT_TLS_INSECURE={'true' if config['MQTT_TLS_INSECURE'] else 'false'}"
        ])
        
        with open(env_path, 'w') as f:
            f.write('\n'.join(env_content))
    
    def quit_application(self):
        if TRAY_AVAILABLE and hasattr(self, 'icon'):
            self.icon.stop()
        self.root.quit()

    def popup(self, p: dict):
        frm  = p.get("from") or ""
        subj = p.get("subject") or "(no subject)"
        body = p.get("body") or p.get("snippet") or ""

        win = tk.Toplevel(self.root)
        win.title(subj if len(subj) <= 120 else subj[:117] + "…")
        # 中央付近
        win.update_idletasks()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        ww, wh = 820, 580
        x, y = int((sw-ww)/2), int((sh-wh)/3)
        win.geometry(f"{ww}x{wh}+{x}+{y}")
        # いったん最前面
        win.attributes("-topmost", True)
        win.after(300, lambda: win.attributes("-topmost", False))

        header = ttk.Frame(win, padding=(12, 12, 12, 6))
        header.pack(fill="x")
        ttk.Label(header, text="From:", width=7).grid(row=0, column=0, sticky="w")
        ttk.Label(header, text=frm, wraplength=650).grid(row=0, column=1, sticky="w")
        ttk.Label(header, text="Subject:", width=7).grid(row=1, column=0, sticky="w")
        ttk.Label(header, text=subj, font=("", 10, "bold"), wraplength=650).grid(row=1, column=1, sticky="w")

        body_frame = ttk.Frame(win, padding=(12, 6, 12, 6))
        body_frame.pack(fill="both", expand=True)

        txt = tk.Text(body_frame, wrap="word")
        txt.insert("1.0", body.lstrip("\r\n"))
        txt.configure(state="disabled")
        txt.pack(side="left", fill="both", expand=True)

        scroll = ttk.Scrollbar(body_frame, command=txt.yview)
        scroll.pack(side="right", fill="y")
        txt.config(yscrollcommand=scroll.set)

        btns = ttk.Frame(win, padding=(12, 6, 12, 12))
        btns.pack(fill="x")
        def copy_body():
            self.root.clipboard_clear()
            self.root.clipboard_append(body)
            messagebox.showinfo("Copied", "本文をコピーしました。", parent=win)
        ttk.Button(btns, text="本文をコピー", command=copy_body).pack(side="left")
        ttk.Button(btns, text="閉じる", command=win.destroy).pack(side="right")

        win.bind("<Escape>", lambda e: win.destroy())

    def poll_queue(self):
        try:
            while True:
                p = inbox_q.get_nowait()
                self.popup(p)
        except queue.Empty:
            pass
        self.root.after(50, self.poll_queue)

def main():
    global mqtt_thread
    mqtt_thread = threading.Thread(target=mqtt_worker, daemon=True)
    mqtt_thread.start()
    
    root = tk.Tk()
    app = App(root)
    
    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        if TRAY_AVAILABLE and hasattr(app, 'icon'):
            app.icon.stop()

if __name__ == "__main__":
    main()
