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

MQTT_HOST = "23.251.158.46"   # GCP VM の外部IP
MQTT_PORT = 8883
MQTT_TLS = True
MQTT_TOPIC = "inbox/matches"
MQTT_USER = "alice"
MQTT_PASS = "9221w8bSEqoF9221"

inbox_q = queue.Queue()
seen_uids = set()

def mqtt_worker():
    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            print("MQTT connected successfully")
            client.subscribe(MQTT_TOPIC, qos=1)
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
        c.username_pw_set(MQTT_USER, MQTT_PASS)
        if MQTT_TLS:
            c.tls_set()
        c.on_connect = on_connect
        c.on_message = on_message
        c.on_disconnect = on_disconnect
        print("→ connecting to", MQTT_HOST, ":", MQTT_PORT)
        c.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        c.loop_forever()
    except Exception as e:
        print(f"MQTT connection error: {e}")
        print("Please check network connectivity and MQTT broker status")


class App:
    def __init__(self, root):
        self.root = root
        root.title("Inbox Listener")
        root.withdraw()  # 常駐（メインは隠す）
        self.poll_queue()

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
    t = threading.Thread(target=mqtt_worker, daemon=True)
    t.start()
    root = tk.Tk()
    App(root)
    root.mainloop()

if __name__ == "__main__":
    main()
