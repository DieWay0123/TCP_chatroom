import socket
import threading
import tkinter as tk
from tkinter.scrolledtext import ScrolledText
from tkinter import simpledialog, messagebox, filedialog, Toplevel, Canvas
from PIL import Image, ImageTk
import io
from datetime import datetime

class ChatClient:
    def __init__(self):
        self.server_ip = ''
        self.server_text_port = 10000
        self.server_image_port = 10001
        self.text_socket = None
        self.image_socket = None
        self.local_ip = self.get_local_ip()
        self.image_refs = []
        self.selected_image = None

        self.setup_gui()

    # 自動抓取本地IP位址
    def get_local_ip(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('10.255.255.255', 1))
            ip = s.getsockname()[0]
        except:
            ip = '127.0.0.1'
        finally:
            s.close()
        return ip
    
    # Client GUI畫面建立
    def setup_gui(self):
        self.window = tk.Tk()
        self.window.title("TCP Chat Client")
        self.window.geometry("600x600")

        self.window.grid_rowconfigure(1, weight=1)
        self.window.grid_columnconfigure(0, weight=1)

        # 上層：顯示本機 IP，輸入 Server IP 與 Port
        top_frame = tk.Frame(self.window)
        top_frame.grid(row=0, column=0, sticky="ew")
        top_frame.grid_columnconfigure(1, weight=1)
        top_frame.grid_columnconfigure(3, weight=1)

        tk.Label(top_frame, text="本機 IP:").grid(row=0, column=0, sticky="w", padx=5)
        tk.Label(top_frame, text=self.local_ip).grid(row=0, column=1, sticky="w")

        tk.Label(top_frame, text="Server IP:").grid(row=1, column=0, sticky="w", padx=5)
        self.server_ip_entry = tk.Entry(top_frame)
        self.server_ip_entry.insert(0, "127.0.0.1")
        self.server_ip_entry.grid(row=1, column=1, sticky="ew", padx=5)

        tk.Label(top_frame, text="Port:").grid(row=1, column=2, sticky="w", padx=5)
        self.server_port_entry = tk.Entry(top_frame)
        self.server_port_entry.insert(0, "10000")
        self.server_port_entry.grid(row=1, column=3, sticky="ew", padx=5)

        self.connect_button = tk.Button(top_frame, text="連線", command=self.connect)
        self.connect_button.grid(row=1, column=4, padx=5)
        tk.Button(top_frame, text="中斷連線", command=self.disconnect).grid(row=1, column=5, padx=5)

        self.server_ip = ''  # 清除舊值
        self.server_text_port = 10000

        # 中間訊息視窗
        self.log_text = ScrolledText(self.window, width=50, height=20)
        self.log_text.grid(row=1, column=0, sticky="nsew")

        # 下層輸入與傳送
        bottom_frame = tk.Frame(self.window)
        bottom_frame.grid(row=2, column=0, sticky="ew", pady=5)
        bottom_frame.grid_columnconfigure(1, weight=1)

        tk.Button(bottom_frame, text="選擇圖片", command=self.select_image).grid(row=0, column=0, padx=5)
        self.input_text = tk.Text(bottom_frame, height=3)
        self.input_text.grid(row=0, column=1, sticky="ew")
        tk.Button(bottom_frame, text="傳送", command=self.send_message).grid(row=0, column=2, padx=5)

        self.img_label = tk.Label(self.window)
        self.img_label.grid(row=3, column=0, pady=5)

    # client連線按鈕操作(嘗試和輸入欄位位址之Server IP和Port連線)
    def connect(self):
        self.server_ip = self.server_ip_entry.get().strip()
        try:
            self.server_text_port = int(self.server_port_entry.get())
        except:
            self.log("[錯誤] 請輸入有效的 Port 編號\n", tag="error")
            return
        try:
            self.connect_button.config(state="disabled")
            self.text_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.text_socket.connect((self.server_ip, self.server_text_port))
            
            self.log(f"已連線到 Server {self.server_ip}:{self.server_text_port}\n", tag="info")
            threading.Thread(target=self.receive_text, daemon=True).start()
        except Exception as e:
            self.log(f"[錯誤] 無法連線到 Server: {e}\n", tag="error")

    # 文字訊息接收處理
    def receive_text(self):
        while True:
            # 流程:
            # 1. 每段文字訊息都會先傳送第一段內容表示接下來訊息的長度
            # 2. 持續接收訊息直到超過長度
            # 不論多長的訊息都能進行傳輸           
            try:
                length_data = self.text_socket.recv(4)
                if not length_data:
                    break
                length = int.from_bytes(length_data, 'big')
                data = b''
                while len(data) < length:
                    chunk = self.text_socket.recv(length-len(data))
                    if not chunk:
                        break
                    data += chunk
                if not data:
                    break
                message = data.decode()
                self.received_text = message
                self.received_image_pending = True

                # 延遲顯示直到圖片來，避免當圖文同時接收時訊息框連跳兩次傳送者標頭
                def flush_text():
                    if self.received_text:
                        self.log(self.received_text)
                        self.received_text = ""
                        self.received_image_pending = False
                self.window.after(300, flush_text)
                    
                if ("已連線" in message or "歡迎進入聊天室" in message) and not self.image_socket:
                    try:
                        self.image_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        self.image_socket.connect((self.server_ip, self.server_image_port))
                        threading.Thread(target=self.receive_image, daemon=True).start()
                        # self.log("圖片通道已建立\n", tag="system")
                    except Exception as e:
                        self.log(f"[錯誤] 圖片連線失敗: {e}\n", tag="error")
            except:
                break
        self.connect_button.config(state="normal")
        self.log("(與server連線已中斷)\n", tag="system")

    # 圖片訊息接收處理
    def receive_image(self):
        while True:
            try:
                length_data = self.image_socket.recv(4)
                if not length_data:
                    break
                length = int.from_bytes(length_data, 'big')
                img_data = b''
                while len(img_data) < length:
                    chunk = self.image_socket.recv(length - len(img_data))
                    if not chunk:
                        break
                    img_data += chunk
                self.display_image(img_data, sender=f"Server ({self.server_ip})")
            except:
                break

    # 從本地資料夾選取要傳送的圖片
    def select_image(self):
        filepath = filedialog.askopenfilename(title="選擇圖片",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.gif *.bmp")])
        if filepath:
            with open(filepath, "rb") as f:
                self.selected_image = f.read()
            img = Image.open(io.BytesIO(self.selected_image))
            img.thumbnail((200, 200))
            photo = ImageTk.PhotoImage(img)
            self.img_label.config(image=photo)
            self.img_label.image = photo

    # 處理送出訊息(圖片/文字)
    def send_message(self):
        msg = self.input_text.get("1.0", tk.END).strip()
        sent_text = False
        sent_image = False
        
        if self.text_socket:
            if msg:
                full_msg = f"Client({self.local_ip}):{msg}\n"
                try:
                    encoded_msg = full_msg.encode()
                    self.text_socket.sendall((len(encoded_msg).to_bytes(4, 'big') + encoded_msg))
                    sent_text = True
                except:
                    self.log("[錯誤] 傳送失敗\n", tag="error")
                self.input_text.delete("1.0", tk.END)

        if self.image_socket and self.selected_image:
            try:
                self.image_socket.sendall(len(self.selected_image).to_bytes(4, 'big') + self.selected_image)
                sent_image = True
            except Exception as e:
                self.log(f"[錯誤] 圖片傳送失敗: {e}\n", tag="error")
                
        # 最後才來處理訊息框顯示，圖文任何一者成功就log+顯示
        if sent_text or sent_image:
            timestamp = datetime.now().strftime("[%H:%M:%S]")
            sender = f"{timestamp} Client({self.local_ip}):"
            self.log_text.insert(tk.END, sender + ("" + msg + "\n" if sent_text else "") + "")
            if sent_image:
                self.display_image(self.selected_image, sender="")
                self.log(f"[圖片已送出 - {self.local_ip} (Client)]\n", tag="system")
            self.log_text.see(tk.END)
        # 送出後重置已選擇圖片
        self.selected_image = None
        self.img_label.config(image='')
        self.img_label.image = None

    # 圖片顯示前處理
    def display_image(self, img_bytes, sender="Server"):
        if self.received_text:
            self.log(self.received_text)
            self.received_text = ""
            sender = None
        self.received_image_pending = False
        try:
            img = Image.open(io.BytesIO(img_bytes))
            img.thumbnail((200, 200))
            photo = ImageTk.PhotoImage(img)
            self.log_image(sender, photo, img_bytes)
        except Exception as e:
            self.log(f"[錯誤] 圖片顯示失敗: {e}\n", tag="error")

    # 在訊息框內顯示圖片
    def log_image(self, sender, photo, original_bytes):
        # 紀錄時間
        now = datetime.now().strftime("[%H:%M:%S]")
        if sender == "":
            sender = None
            self.log_text.insert(tk.END, f"\n")
        if sender:
            self.log_text.insert(tk.END, f"{now} {sender}:\n")
        # self.log_text.insert(tk.END, f"{now} {sender}:\n")
        img_widget = tk.Label(self.log_text, image=photo, cursor="hand2")
        img_widget.image = photo
        img_widget.bind("<Button-1>", lambda e: self.show_full_image(original_bytes))
        self.log_text.window_create(tk.END, window=img_widget)
        self.log_text.insert(tk.END, "\n")
        self.image_refs.append(photo)
        self.log_text.see(tk.END)

    # 點擊訊息框內的圖片可放大檢視
    def show_full_image(self, img_bytes):
        try:
            img = Image.open(io.BytesIO(img_bytes))
            top = Toplevel(self.window)
            top.title("圖片預覽")
            width, height = img.size
            top.geometry(f"{width}x{height}")

            photo = ImageTk.PhotoImage(img)
            canvas = Canvas(top, width=width, height=height)
            canvas.pack()
            canvas.create_image(0, 0, anchor=tk.NW, image=photo)
            canvas.image = photo
        except:
            messagebox.showerror("錯誤", "無法開啟圖片")

    # 於聊天框內顯示訊息，透過tag區分顏色
    def log(self, msg, tag=None):
        # 紀錄時間
        now = datetime.now().strftime("[%H:%M:%S]")
        msg = f"{now} {msg}"
        if tag and tag not in self.log_text.tag_names():
            if tag == "error":
                self.log_text.tag_configure(tag, foreground="red")
            elif tag == "info":
                self.log_text.tag_configure(tag, foreground="blue")
            elif tag == "system":
                self.log_text.tag_configure(tag, foreground="gray")
            else:
                self.log_text.tag_configure(tag, foreground="black")

        if tag:
            self.log_text.insert(tk.END, msg, tag)
        else:
            self.log_text.insert(tk.END, msg)
        self.log_text.see(tk.END)

    # 中斷連線按鈕對應操作(中斷目前client對server連線)
    def disconnect(self):
        if self.text_socket:
            try: self.text_socket.close()
            except: pass
            self.text_socket = None
        if self.image_socket:
            try: self.image_socket.close()
            except: pass
            self.image_socket = None
        self.connect_button.config(state="normal")
    
    def run(self):
        self.window.mainloop()

if __name__ == '__main__':
    ChatClient().run()