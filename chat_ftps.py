import socket
import threading
import tkinter as tk
from tkinter.scrolledtext import ScrolledText
from tkinter import messagebox, filedialog, Toplevel, Canvas
from PIL import Image, ImageTk
import io
import select
import queue
import subprocess
import os
from datetime import datetime


class ChatServer:
    def __init__(self, host='0.0.0.0', text_port=10000, image_port=10001):
        # 初始化chat server的設定
        self.HOST = host
        self.TEXT_PORT = text_port
        self.IMAGE_PORT = image_port
        self.text_conn: socket.socket = None # 文字傳輸的連線
        self.image_conn: socket.socket = None # 圖片傳輸的連線
        self.client_addr = None
        self.local_ip = self.get_local_ip()
        self.image_refs = [] # 保留紀錄圖片傳輸紀錄
        self.selected_image = None # 暫存目前選取要傳送的圖片

        self.waiting_clients = queue.Queue()
        self.waiting_addrs = [] # 紀錄等待連線中的client IP
        
        # 文字記錄保存相關參數，檔案名稱設定為目前時間
        LOG_DIR = "chat_logs"
        os.makedirs(LOG_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file_path = os.path.join(LOG_DIR, f"chat_log_{timestamp}.txt")
        
        self.setup_gui() # 初始化界面
        threading.Thread(target=self.start_text_server, daemon=True).start() # 初始化socket監聽
    
    # 自動抓取本地IP位址
    def get_local_ip(self):
        # 透過對內部網路建立一次連線來得到本地ip位址
        # socket會自動偵測本機的網路介面，並綁定適當的IP連接，透過這個原理可以不用設定本地IP就得到本地位址
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('10.255.255.255', 1))
            ip = s.getsockname()[0]
        except:
            ip = '127.0.0.1'
        finally:
            s.close()
        return ip

    # Server GUI畫面建立
    def setup_gui(self):
        self.window = tk.Tk()
        self.window.title("TCP Chat Server")
        self.window.geometry("600x600")

        self.window.grid_rowconfigure(2, weight=1)
        self.window.grid_columnconfigure(0, weight=1)

        # 最上方顯示waiting frame
        self.waiting_frame = tk.LabelFrame(self.window, text="等待中 Clients")
        self.waiting_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        self.waiting_label = tk.Label(self.waiting_frame, text="無等待中 client")
        self.waiting_label.pack(anchor="w", padx=10)

        # top_frame: 連線資訊與控制
        top_frame = tk.Frame(self.window)
        top_frame.grid(row=1, column=0, sticky="ew")

        for i in range(7):
            top_frame.grid_columnconfigure(i, weight=1)

        tk.Label(top_frame, text=f"本機 IP:{self.local_ip}", fg="green").grid(row=0, column=0, sticky="w", padx=5)
        tk.Label(top_frame, text=f"Text Port:{self.TEXT_PORT}").grid(row=0, column=1, sticky="w")
        tk.Label(top_frame, text=f"Image Port:{self.IMAGE_PORT}").grid(row=0, column=2, sticky="w")
        tk.Button(top_frame, text="結束程式", command=self.close_server).grid(row=0, column=6, sticky="e", padx=5)

        # middle_frame: 訊息框
        middle_frame = tk.Frame(self.window)
        middle_frame.grid(row=2, column=0, sticky="nsew")
        middle_frame.grid_rowconfigure(0, weight=1)
        middle_frame.grid_columnconfigure(0, weight=1)

        self.log_text = ScrolledText(middle_frame, width=50, height=20)
        self.log_text.grid(row=0, column=0, sticky="nsew")

        # bottom_frame: 傳送訊息
        bottom_frame = tk.Frame(self.window)
        bottom_frame.grid(row=3, column=0, sticky="ew", pady=5)
        bottom_frame.grid_columnconfigure(1, weight=1)

        tk.Button(bottom_frame, text="選擇圖片", command=self.select_image).grid(row=0, column=0, padx=5)
        self.input_text = tk.Text(bottom_frame, height=3)
        self.input_text.grid(row=0, column=1, sticky="ew")
        tk.Button(bottom_frame, text="傳送", command=self.send_message).grid(row=0, column=2, padx=5)

        self.img_label: tk.Label = tk.Label(self.window)
        self.img_label.grid(row=4, column=0, pady=5)
        
        # 開啟連天記錄存檔的資料夾
        tk.Button(self.window, text="📁 開啟紀錄", command=self.open_log_folder).grid(row=5, column=0, pady=(0, 10))

    # 更新server端顯示的client等待佇列    
    def update_waiting_label(self):
        if self.waiting_addrs:
            text = "\n".join(f"- {addr}" for addr in self.waiting_addrs)
        else:
            text = "無等待中 client"
        self.waiting_label.config(text=text)

    # 當client連入時，建立與client端的文字訊息傳輸連線
    def start_text_server(self):
        # 建立並等待與client的TCP連線
        # 分成兩個Thread來處理列隊等待中的client
        # 1. handle_client(): 處理當client嘗試連線時的排隊情況，並在client連入或排隊等到時進一步進到後續接收訊息階段
        # 2. queue_monitor(): 實際管理排隊並進一步放入client連線
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.bind((self.HOST, self.TEXT_PORT))
        server_socket.listen(5)
        self.log("等待 client 連線中...\n", tag="system")

        def handle_client(conn, addr):
            if self.text_conn is None:
                self.text_conn = conn
                self.client_addr = addr
                self.log_text.delete("0.0", tk.END) # 新連線清空聊天紀錄
                self.log(f"Client {addr} 已連線！\n", tag="info")
                self.text_conn.sendall(len("歡迎進入聊天室\n".encode()).to_bytes(4, 'big') + "歡迎進入聊天室\n".encode())
                threading.Thread(target=self.receive_text, daemon=True).start()
                threading.Thread(target=self.start_image_server, args=(addr,), daemon=True).start()
            else:
                identifier = f"{addr[0]}:{addr[1]}"
                self.waiting_clients.put((conn, addr))
                self.waiting_addrs.append(identifier)
                self.update_waiting_label()
                pos = self.waiting_clients.qsize()
                try:
                    msg = f"您是第 {pos} 位等待中，請稍候...\n".encode()
                    conn.sendall((len(msg).to_bytes(4, 'big') + msg))
                except:
                    conn.close()

                # monitor_queue_socket(): 監控client端是否在排隊時中斷連線
                # 原理是偵測與該client連線的socket通道是否有中斷，若中斷即代表離開等待連入server佇列
                import select
                def monitor_queue_socket():
                    try:
                        while True:
                            rlist, _, _ = select.select([conn], [], [], 0.5)
                            if rlist:
                                # 確保socket有資料可讀才來check
                                peek = conn.recv(1, socket.MSG_PEEK)
                                if not peek:
                                    break
                    except:
                        pass

                    # 一旦連線中斷就移除
                    if (conn, addr) in list(self.waiting_clients.queue):
                        with self.waiting_clients.mutex:
                            self.waiting_clients.queue.remove((conn, addr))
                        self.waiting_addrs.remove(identifier)
                        self.update_waiting_label()
                        self.log(f"({identifier} 離開等待隊列。)\n", tag="system")

                threading.Thread(target=monitor_queue_socket, daemon=True).start()

        def queue_monitor():
            import time
            while True:
                if self.text_conn is None and not self.waiting_clients.empty():
                    try:
                        #self.log_text.delete("0.0", tk.END) # 新連線清空聊天紀錄
                        conn, addr = self.waiting_clients.get(timeout=0.1)
                        identifier = f"{addr[0]}:{addr[1]}"
                        if identifier in self.waiting_addrs:
                            self.waiting_addrs.remove(identifier)
                        self.window.after(0, self.update_waiting_label)
                        self.window.after(0, lambda: handle_client(conn, addr))
                    except queue.Empty:
                        pass
                time.sleep(0.2) 

        threading.Thread(target=queue_monitor, daemon=True).start()
        while True:
            conn, addr = server_socket.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
    
    # 當client連入時，建立與client端的圖片訊息傳輸連線
    def start_image_server(self, addr):
        # 建立與client的img socket連線
        img_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        img_server.bind((self.HOST, self.IMAGE_PORT))
        img_server.listen(1)
        self.log(f"等待 {addr} 的圖片連線中...\n", tag="system")
        conn, _ = img_server.accept()
        self.image_conn = conn
        self.log(f"{addr} 圖片 socket 已連接\n", tag="info")

        def handle_image_receive(sock):
            while True:
                try:
                    length_data = sock.recv(4)
                    if not length_data:
                        break
                    length = int.from_bytes(length_data, 'big')
                    img_data = b''
                    while len(img_data) < length:
                        chunk = sock.recv(length - len(img_data))
                        if not chunk:
                            break
                        img_data += chunk
                    self.display_image(img_data, sender=f"Client ({addr[0]})")
                except:
                    break

        threading.Thread(target=handle_image_receive, args=(conn,), daemon=True).start()        

    # 文字訊息接收處理
    def receive_text(self):
        self.received_text = ""
        self.received_image_pending = False
        while True:
            # 流程:
            # 1. 每段文字訊息都會先傳送第一段內容表示接下來訊息的長度
            # 2. 持續接收訊息直到超過長度
            # 不論多長的訊息都能進行傳輸
            try:
                length_data = self.text_conn.recv(4)
                if not length_data:
                    break
                length = int.from_bytes(length_data, 'big')
                data = b''
                while len(data) < length:
                    chunk = self.text_conn.recv(length-len(data))
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
            except:
                break
        self.log("(目前連線之Client已離線)\n", tag="system")
        self.text_conn = None
        self.image_conn = None

    # 圖片訊息接收處理
    def receive_image(self):
        while True:
            try:
                length_data = self.image_conn.recv(4)
                if not length_data:
                    break
                length = int.from_bytes(length_data, 'big')
                img_data = b''
                while len(img_data) < length:
                    chunk = self.image_conn.recv(length - len(img_data))
                    if not chunk:
                        break
                    img_data += chunk
                self.display_image(img_data, sender=f"Client({self.client_addr[0]})")
            except:
                break
    
    # 從本地資料夾選取要傳送的圖片
    def select_image(self):
        filepath = filedialog.askopenfilename(title="選擇圖片",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.gif *.bmp")])
        if filepath:
            with open(filepath, "rb") as f:
                self.selected_image = f.read()
            img = Image.open(io.BytesIO(self.selected_image)) # 透過BytesIO將讀入的圖片轉成pillow可處理的形式
            img.thumbnail((200, 200))
            photo = ImageTk.PhotoImage(img)
            self.img_label.config(image=photo)
            self.img_label.image = photo
    
    # 處理送出訊息(圖片/文字)
    def send_message(self):
        msg = self.input_text.get("1.0", tk.END).strip()
        sent_text = False
        sent_image = False
        
        # 根據目前狀況(是否有文字輸入/圖片選擇)送出訊息
        if self.text_conn:
            if msg:
                full_msg = f"Server({self.local_ip}):{msg}\n"
                try:
                    encoded_msg = full_msg.encode()
                    self.text_conn.sendall((len(encoded_msg).to_bytes(4, 'big') + encoded_msg))
                    sent_text = True
                except:
                    self.log("[錯誤] 傳送失敗\n", tag="error")
                self.input_text.delete("1.0", tk.END)
        # 處理圖片傳送
        if self.image_conn and self.selected_image:
            try:
                self.image_conn.sendall(len(self.selected_image).to_bytes(4, 'big') \
                                        + self.selected_image) # 送出圖片大小byte+實際圖片byte的TCP封包
                sent_image = True
            except Exception as e:
                self.log(f"[錯誤] 圖片傳送失敗: {e}\n", tag="error")
            
        # 最後才來處理訊息框顯示，圖文任何一者成功就log+顯示
        if sent_text or sent_image:
            timestamp = datetime.now().strftime("[%H:%M:%S]")
            sender = f"{timestamp} Server({self.local_ip}):"
            self.log_text.insert(tk.END, sender + ("" + msg + "\n" if sent_text else "") + "")
            if sent_image:
                self.display_image(self.selected_image, sender="")
                self.log(f"[圖片已送出 - {self.local_ip} (Server)]\n", tag="system")
            self.log_text.see(tk.END)
        # 送出後重置已選擇圖片
        self.selected_image = None
        self.img_label.config(image='')
        self.img_label.image = None    
    
    # 圖片顯示前處理
    def display_image(self, img_bytes, sender="Client"):
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

            # 使用canvas+toplevel模塊來額外彈出視窗顯示原圖片
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
        
        
        # server會保存文字聊天紀錄
        try:
            with open(self.log_file_path, "a", encoding="utf-8") as f:
                f.write(msg)
        except Exception as e:
            print(f"[log 寫入失敗]: {e}")
        
    # 開啟聊天紀錄檔案資料夾
    def open_log_folder(self):
        log_path = os.path.abspath("chat_logs")
        try:
            # 根據作業系統選擇開啟檔案資料夾的執行指令
            if os.name == 'nt':  # Windows
                subprocess.Popen(f'explorer "{log_path}"')
            elif os.name == 'posix': # macOS / Linux
                subprocess.Popen(['xdg-open', log_path])
        except Exception as e:
            self.log(f"[錯誤] 無法開啟資料夾: {e}", tag="error")

    # 結束程式按鈕對應操作(關閉所有連線並關閉程式)
    def close_server(self):
        if self.text_conn:
            try: self.text_conn.close()
            except: pass
        if self.image_conn:
            try: self.image_conn.close()
            except: pass
        self.log("\n伺服器已關閉。\n")
        self.window.destroy()

    def run(self):
        self.window.mainloop()

if __name__ == '__main__':
    ChatServer().run()
