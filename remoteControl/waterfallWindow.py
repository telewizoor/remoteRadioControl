#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Klient wodospadu OpenWebRX+ w PyQt5.
Łączy się do WebSocket serwera OpenWebRX+, wysyła handshake, odbiera FFT i rysuje wodospad
z użyciem tej samej palety kolorów co w JS.
"""

import sys
import zlib
import threading
import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets
import websocket  # websocket-client

# Konfiguracja
WS_URL = "ws://192.168.152.12:8073/ws/"  # ustaw na prawidłowy websocket serwera
HEADER_SIZE = 1  # typ ramki w pierwszym bajcie (jak w JS)
FFT_SIZE = 2048  # liczba punktów FFT
MIN_DB = -120.0
MAX_DB = -30.0

# Paleta kolorów z JS (np. turbo)
WF_THEME = [
    0x000000, 0x0000FF, 0x00FFFF, 0x00FF00, 0xFFFF00, 0xFF0000, 0xFF00FF, 0xFFFFFF
]

def build_colormap(theme):
    n_steps = 256
    colors = np.array([[ (c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF] for c in theme ], dtype=np.float32)
    segments = len(colors) - 1
    steps_per_segment = n_steps // segments
    palette = np.zeros((n_steps, 3), dtype=np.uint8)
    idx = 0
    for s in range(segments):
        c0 = colors[s]
        c1 = colors[s+1]
        for i in range(steps_per_segment):
            t = i / steps_per_segment
            palette[idx] = (c0 + t*(c1 - c0)).astype(np.uint8)
            idx += 1
    while idx < n_steps:
        palette[idx] = colors[-1].astype(np.uint8)
        idx += 1
    return palette

PALETTE = build_colormap(WF_THEME)

def map_fft_to_colors(fft_values, min_db=MIN_DB, max_db=MAX_DB, palette=PALETTE):
    vals = np.clip((fft_values - min_db) / (max_db - min_db), 0, 1)
    idxs = (vals * (len(palette)-1)).astype(np.int32)
    return palette[idxs]

class WaterfallWidget(QtWidgets.QWidget):
    def __init__(self, width=FFT_SIZE, height=600, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OpenWebRX+ Waterfall")
        self.width_px = width
        self.height_px = height
        self.setMinimumSize(width, height)
        self._image = QtGui.QImage(self.width_px, self.height_px, QtGui.QImage.Format_RGB888)
        self._image.fill(QtGui.QColor('black'))
        self._lock = threading.Lock()

    @QtCore.pyqtSlot(np.ndarray)
    def push_row(self, row):
        if row.size != self.width_px:
            return
        rgb = map_fft_to_colors(row)
        with self._lock:
            ptr = self._image.bits()
            ptr.setsize(self._image.byteCount())
            arr = np.frombuffer(ptr, np.uint8).reshape((self.height_px, self.width_px, 3))
            arr[1:] = arr[:-1]
            arr[0] = rgb
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        with self._lock:
            painter.drawImage(self.rect(), self._image, self._image.rect())

class WsReceiver(threading.Thread, QtCore.QObject):
    push_row_signal = QtCore.pyqtSignal(object)

    def __init__(self, ws_url, fft_size=FFT_SIZE):
        threading.Thread.__init__(self, daemon=True)
        QtCore.QObject.__init__(self)
        self.ws_url = ws_url
        self.fft_size = fft_size
        self._stop_event = threading.Event()
        self._ws = None

    def stop(self):
        self._stop_event.set()
        try:
            if self._ws:
                self._ws.close()
        except Exception:
            pass

    def run(self):
        HEADER_SIZE = 6  # 6 bajtów nagłówka

        def on_message(ws, message):
            if isinstance(message, str):
                return
            data = message
            try:
                if len(data) > 2 and data[0] == 0x78:
                    data = zlib.decompress(data)
            except Exception:
                pass

            if len(data) < HEADER_SIZE:
                return

            frame_type = data[0]  # pierwszy bajt = typ
            # reszta nagłówka np. data[1:6] możesz zapisać, ale ignorujemy
            payload = data[HEADER_SIZE:]  # po 6 bajtach jest czysta tablica FFT uint8

            if frame_type == 1:  # FFT
                if len(payload) == FFT_SIZE:
                    # konwertuj uint8 do dB lub bezpośrednio mapuj
                    arr = np.frombuffer(payload, dtype=np.uint8).astype(np.float32)
                    # możesz np. skalować 0..255 na -120..-30 dB:
                    fft_f32 = MIN_DB + arr / 255.0 * (MAX_DB - MIN_DB)
                    self.push_row_signal.emit(fft_f32.copy())


        def on_error(ws, error):
            print("WS error:", error)

        def on_close(ws, close_status_code, close_msg):
            print("WS closed", close_status_code, close_msg)

        def on_open(ws):
            print("WS open:", self.ws_url)
            ws.send('SERVER DE CLIENT client=openwebrx.js type=receiver')

        while not self._stop_event.is_set():
            try:
                self._ws = websocket.WebSocketApp(self.ws_url,
                                                  on_message=on_message,
                                                  on_error=on_error,
                                                  on_close=on_close,
                                                  on_open=on_open)
                self._ws.run_forever(ping_interval=20, ping_timeout=5)
            except Exception as e:
                print("WsReceiver exception:", e)
            if not self._stop_event.is_set():
                import time
                time.sleep(1)

class WaterfallWindow(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Waterfall Display - OpenWebRX+")
        self.setGeometry(100, 100, 900, 600)
        layout = QtWidgets.QVBoxLayout(self)
        self.waterfall_widget = WaterfallWidget()
        layout.addWidget(self.waterfall_widget)
        self.ws_thread = WsReceiver(WS_URL, fft_size=FFT_SIZE)
        self.ws_thread.push_row_signal.connect(self.waterfall_widget.push_row)
        self.ws_thread.start()

    def closeEvent(self, event):
        self.ws_thread.stop()
        self.ws_thread.join(timeout=1)
        super().closeEvent(event)

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    waterfall_window = WaterfallWindow()
    waterfall_window.show()
    sys.exit(app.exec_())
