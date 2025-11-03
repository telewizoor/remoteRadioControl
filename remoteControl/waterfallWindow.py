#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Klient wodospadu OpenWebRX+ w PyQt5.
Zaktualizowana wersja: zoom (wheel), pan (drag), skala częstotliwości oraz etykiety min/max dB.
"""

import sys
import json
import threading
import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtGui import QIcon
import websocket  # websocket-client

# Konfiguracja
WS_URL = "ws://192.168.152.12:8073/ws/"
FFT_SIZE = 2048

MOUSE_WHEEL_FREQ_STEP = 100

WATERFALL_MARGIN   = 32
MAJOR_THICK_HEIGHT = 12
MINOR_TICK_HEIGHT  = 6
MINOR_TICKS_PER_MAJOR = 10  # ile ticków pomiędzy głównymi (0 = brak)

WF_THEME = [
    0x000020, 0x000030, 0x000050, 0x000091, 0x1E90FF, 0xFFFFFF, 0xFFFF00,
    0xFE6D16, 0xFF0000, 0xC60000, 0x9F0000, 0x750000, 0x4A0000
]

def build_colormap(theme):
    n_steps = 256
    colors = np.array([[(c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF] for c in theme], dtype=np.float32)
    segments = len(colors) - 1
    steps_per_segment = n_steps // segments
    palette = np.zeros((n_steps, 3), dtype=np.uint8)
    idx = 0
    for s in range(segments):
        c0 = colors[s]
        c1 = colors[s+1]
        for i in range(steps_per_segment):
            t = i / steps_per_segment
            palette[idx] = (c0 + t * (c1 - c0)).astype(np.uint8)
            idx += 1
    while idx < n_steps:
        palette[idx] = colors[-1].astype(np.uint8)
        idx += 1
    return palette

PALETTE = build_colormap(WF_THEME)


# --- (ImaAdpcmCodec left as in your code; kept minimal for brevity) ---
class ImaAdpcmCodec:
    ima_index_table = [-1, -1, -1, -1, 2, 4, 6, 8,
                       -1, -1, -1, -1, 2, 4, 6, 8]
    ima_step_table = [7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,
                      50,55,60,66,73,80,88,97,107,118,130,143,157,173,190,209,230,253,279,307,
                      337,371,408,449,494,544,598,658,724,796,876,963,1060,1166,1282,1411,1552,1707,1878,2066,
                      2272,2499,2749,3024,3327,3660,4026,4428,4871,5358,5894,6484,7132,7845,8630,9493,10442,11487,12635,13899,
                      15289,16818,18500,20350,22385,24623,27086,29794,32767]
    def __init__(self):
        self.reset()
    def reset(self):
        self.step_index = 0
        self.predictor = 0
        self.step = 0
        self.synchronized = 0
        self.sync_word = b"SYNC"
        self.sync_counter = 0
        self.phase = 0
        self.sync_buffer = np.zeros(4, dtype=np.uint8)
        self.sync_buffer_index = 0
    def decode(self, data):
        output = np.zeros(len(data) * 2, dtype=np.int16)
        for i, byte in enumerate(data):
            output[i*2] = self.decode_nibble(byte & 0x0F)
            output[i*2+1] = self.decode_nibble((byte >> 4) & 0x0F)
        return output
    def decode_nibble(self, nibble):
        self.step_index += ImaAdpcmCodec.ima_index_table[nibble]
        self.step_index = max(0, min(self.step_index, 88))
        diff = self.step >> 3
        if nibble & 1: diff += self.step >> 2
        if nibble & 2: diff += self.step >> 1
        if nibble & 4: diff += self.step
        if nibble & 8: diff = -diff
        self.predictor += diff
        self.predictor = max(-32768, min(self.predictor, 32767))
        self.step = ImaAdpcmCodec.ima_step_table[self.step_index]
        return self.predictor


# --- pomocnicze widgety i funkcje ---
class LinePlotWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = np.array([], dtype=np.float32)
        self.margin = 0
        self.setMinimumHeight(80)
        self.pen = QtGui.QPen(QtGui.QColor("#00BFFF"), 2)
        self.refresh_tick = 0

    @QtCore.pyqtSlot(np.ndarray)
    def setData(self, values):
        if self.refresh_tick >= 2:
            self.data = np.array(values, dtype=np.float32)
            self.data = np.interp(np.linspace(0, len(self.data)-1, 800), np.arange(len(self.data)), self.data)
            self.update()
            self.refresh_tick = 0
        else:
            self.refresh_tick += 1

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor("black"))
        if self.data.size == 0:
            return
        w = self.width() - 2*self.margin
        h = self.height() - 2*self.margin
        x = np.linspace(self.margin, self.width() - self.margin, len(self.data))
        ymin, ymax = np.min(self.data), np.max(self.data)
        if ymax == ymin:
            ymax = ymin + 1e-6
        y = self.height() - self.margin - (self.data - ymin) / (ymax - ymin) * h
        painter.setPen(QtGui.QPen(QtGui.QColor("gray"), 1))
        painter.drawLine(self.margin, self.margin, self.margin, self.height() - self.margin)
        painter.drawLine(self.margin, self.height() - self.margin, self.width() - self.margin, self.height() - self.margin)
        path = QtGui.QPainterPath()
        path.moveTo(x[0], y[0])
        for i in range(1, len(x)):
            path.lineTo(x[i], y[i])
        painter.setPen(self.pen)
        painter.drawPath(path)


def draw_line(data: np.ndarray, palette: np.ndarray, min_db=-120.0, max_db=-30.0, offset=0.0) -> np.ndarray:
    data_offset = data + offset
    norm = np.clip((data_offset - min_db) / (max_db - min_db), 0.0, 1.0)
    indices = (norm * (len(palette) - 1)).astype(np.int32)
    rgb_row = palette[indices]
    return rgb_row


class WaterfallWidget(QtWidgets.QWidget):
    freq_clicked = QtCore.pyqtSignal(int)   # emitowane kiedy użytkownik kliknie/wybiera freq
    freq_hover = QtCore.pyqtSignal(int)     # emitowane kiedy porusza myszką (pozycja)
    freq_selected = QtCore.pyqtSignal(int)     # emitowane kiedy porusza myszką (pozycja)

    def __init__(self, width=800, height=200, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Waterfall view")
        self.width_px = width
        self.height_px = height
        self.setMinimumSize(width, height)

        # QImage jako bufor tylko do wyświetlania; trzymamy też _buffer (numpy) żeby bezpiecznie modyfikować
        self._image = QtGui.QImage(self.width_px, self.height_px, QtGui.QImage.Format_RGB888)
        self._image.fill(QtGui.QColor('black'))
        self._buffer = np.zeros((self.height_px, self.width_px, 3), dtype=np.uint8)
        self.setMouseTracking(True)

        self._lock = threading.Lock()
        self.min_db = -90.0
        self.max_db = -60.0

        # paleta
        self.palette = PALETTE.copy()

        # zoom/pan
        self.zoom_factor = 1.0  # 1.0 = full width (no zoom)
        self.center_pos = 0.5   # 0..1 position in full FFT
        self._dragging = False
        self._last_x = 0

        # selekcja / hover
        self.selected_freq = None
        self.hover_freq = 14250000
        self._press_x = None
        self._press_y = None

        # częstotliwości - będą aktualizowane z WsReceiver
        self.samp_rate = 1000000
        self.center_freq = 14250000
        self.selected_freq = self.center_freq

    def set_min_db(self, value):
        self.min_db = float(value)

    def set_max_db(self, value):
        self.max_db = float(value)

    def _x_to_freq(self, x):
        vis_start, vis_end = self._visible_freq_range()
        # ogranicz x do widocznego obszaru widgetu
        x = max(0, min(self.width_px - 1, x))
        frac = x / max(1.0, (self.width_px - 1))
        return int(vis_start + frac * (vis_end - vis_start))

    @QtCore.pyqtSlot(dict)
    def update_config(self, cfg):
        # oczekujemy kluczy: samp_rate, center_freq (opcjonalnie start_freq)
        if 'samp_rate' in cfg:
            self.samp_rate = float(cfg['samp_rate'])
        if 'center_freq' in cfg:
            self.center_freq = float(cfg['center_freq'])
        # redraw labels
        self.update()

    @QtCore.pyqtSlot(int)
    def update_selected_freq(self, freq):
        self.selected_freq = freq

    def wheelEvent(self, event):
        delta = event.angleDelta().y()

        if event.modifiers() & QtCore.Qt.ControlModifier or self._dragging:
            # pozycja kursora (x w pikselach)
            mouse_x = event.x()

            # częstotliwość pod kursorem PRZED zoomem
            freq_before = self._x_to_freq(mouse_x)

            # modyfikacja zoomu
            if delta > 0:
                self.zoom_factor *= 0.8
            else:
                self.zoom_factor *= 1.2

            # ograniczenia zoomu
            self.zoom_factor = max(0.05, min(1.0, self.zoom_factor))

            # częstotliwość pod kursorem PO zoomie
            freq_after = self._x_to_freq(mouse_x)

            # zmiana środka widoku, aby utrzymać tę samą częstotliwość pod kursorem
            if hasattr(self, "samp_rate") and self.samp_rate > 0:
                full_start = self.center_freq - (self.samp_rate / 2.0)
                full_bw = self.samp_rate
                # różnica między freq_before i freq_after w jednostkach [0..1]
                delta_norm = (freq_before - freq_after) / full_bw
                self.center_pos = np.clip(self.center_pos + delta_norm, 0.0, 1.0)

            self.update()
            event.accept()

        else:
            # przewijanie bez Ctrl — zmiana częstotliwości
            if delta > 0:
                delta = 1
            elif delta < 0:
                delta = -1

            self.selected_freq -= self.selected_freq % MOUSE_WHEEL_FREQ_STEP
            self.selected_freq += delta * MOUSE_WHEEL_FREQ_STEP
            self.freq_clicked.emit(self.selected_freq)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._dragging = True
            self._last_x = event.x()
            self._press_x = event.x()
            self._press_y = event.y()

    def mouseMoveEvent(self, event):
        # hover — zawsze aktualizujemy częstotliwość i odświeżamy natychmiast
        freq = int(self._x_to_freq(event.x()))
        if freq != self.hover_freq:
            self.hover_freq = freq
            self.freq_hover.emit(freq)
            self.update()

        # jeśli przeciągamy - zachowaj obecne panning
        if self._dragging:
            dx = event.x() - self._last_x
            self._last_x = event.x()
            move = -dx / max(1.0, self.width_px) * (1.0)
            self.center_pos = np.clip(self.center_pos + move * self.zoom_factor, 0.0, 1.0)
            self.update()

    def mouseReleaseEvent(self, event):
        # jeśli był to krótki klik (prawie bez ruchu) - traktujemy jako wybór częstotliwości
        self._dragging = False
        if self._press_x is not None:
            dx = abs(event.x() - self._press_x)
            dy = abs(event.y() - self._press_y)
            if dx < 4 and dy < 4:  # threshold dla kliknięcia
                freq = int(self._x_to_freq(event.x()))
                self.selected_freq = freq
                self.freq_clicked.emit(freq)
                self.update()
        self._press_x = None
        self._press_y = None

    def _visible_freq_range(self):
        """Zwraca (visible_start_freq, visible_end_freq) na podstawie samp_rate, center_freq, zoom_factor i center_pos."""
        full_start = self.center_freq - (self.samp_rate / 2.0)
        full_bw = self.samp_rate
        vis_bw = full_bw * self.zoom_factor
        # center_pos określa pozycję środka widoku względem pełnego pasma [0..1]
        center_abs = full_start + self.center_pos * full_bw
        vis_start = center_abs - vis_bw / 2.0
        vis_end = vis_start + vis_bw
        # zabezpieczenie granic: trzymamy w obrębie pełnego pasma
        if vis_start < full_start:
            vis_start = full_start
            vis_end = vis_start + vis_bw
        if vis_end > full_start + full_bw:
            vis_end = full_start + full_bw
            vis_start = vis_end - vis_bw
        return vis_start, vis_end

    @QtCore.pyqtSlot(np.ndarray)
    def push_row(self, fft_row):
        # zoom: wybieramy wycinek
        n = len(fft_row)
        visible_n = max(2, int(n * self.zoom_factor))
        center = int(self.center_pos * n)
        start = max(0, center - visible_n // 2)
        end = min(n, start + visible_n)
        if end - start < visible_n:
            start = max(0, end - visible_n)
        fft_visible = fft_row[start:end]

        # skaluj do szerokości widgetu
        if fft_visible.size != self.width_px:
            fft_visible = np.interp(np.linspace(0, len(fft_visible) - 1, self.width_px),
                                    np.arange(len(fft_visible)),
                                    fft_visible)

        rgb_row = draw_line(fft_visible, self.palette, self.min_db, self.max_db)

        with self._lock:
            # operuj na naszym bezpiecznym bufferze numpy
            self._buffer[1+WATERFALL_MARGIN:] = self._buffer[WATERFALL_MARGIN:-1]
            self._buffer[WATERFALL_MARGIN] = rgb_row

            # skopiuj do QImage (uwzględnia bytesPerLine)
            ptr = self._image.bits()
            ptr.setsize(self._image.byteCount())
            bytes_per_line = self._image.bytesPerLine()
            arr2d = np.frombuffer(ptr, dtype=np.uint8).reshape((self.height_px, bytes_per_line))
            # skopiuj tylko treść RGB (bez paddingu)
            rgb_view = arr2d[:, :self.width_px * 3].reshape((self.height_px, self.width_px, 3))
            rgb_view[:, :] = self._buffer[:, :]

        # poproś o ponowne narysowanie
        self.update()

    def _format_freq(self, hz):
        #  formatowanie częstotliwości  -> Hz, kHz, MHz
        if abs(hz) >= 1e6:
            return f"{hz/1e6:.2f} MHz"
        if abs(hz) >= 1e3:
            return f"{hz/1e3:.1f} kHz"
        return f"{int(hz)} Hz"

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        # narysuj obraz
        with self._lock:
            painter.drawImage(self.rect(), self._image, self._image.rect())

            # --- rysowanie skali częstotliwości (napisy co 0.1 MHz + ticki pośrednie)
            vis_start, vis_end = self._visible_freq_range()
            bw = vis_end - vis_start

            painter.setPen(QtGui.QPen(QtGui.QColor("#ffd000"), 1))
            font = painter.font()
            font.setPointSize(10)
            painter.setFont(font)
            metrics = painter.fontMetrics()

            # główne ticki co 0.1 MHz
            start_mhz = vis_start / 1e6
            end_mhz = vis_end / 1e6
            start_tick = np.floor(start_mhz * 10) / 10
            end_tick = np.ceil(end_mhz * 10) / 10

            tick = start_tick
            while tick <= end_tick + 1e-9:
                freq_hz = tick * 1e6
                if vis_start <= freq_hz <= vis_end:
                    x = int((freq_hz - vis_start) / bw * (self.width_px - 1))
                    # główny tick + napis
                    painter.drawLine(x, WATERFALL_MARGIN - MAJOR_THICK_HEIGHT, x, WATERFALL_MARGIN)
                    text = f"{tick:.2f}"
                    tw = metrics.horizontalAdvance(text)
                    tx = max(2, x - tw // 2)
                    painter.drawText(tx, 16, text)

                    # ticki pośrednie
                    if MINOR_TICKS_PER_MAJOR > 0:
                        step = 0.1 / MINOR_TICKS_PER_MAJOR
                        for i in range(1, MINOR_TICKS_PER_MAJOR):
                            sub_tick = tick + i * step
                            sub_freq_hz = sub_tick * 1e6
                            if sub_freq_hz >= vis_end:
                                break
                            x_sub = int((sub_freq_hz - vis_start) / bw * (self.width_px - 1))
                            painter.drawLine(x_sub, WATERFALL_MARGIN - MINOR_TICK_HEIGHT, x_sub, WATERFALL_MARGIN)
                tick += 0.05


            # narysuj ramkę i aktualne wartości min/max dB w rogu
            overlay_y = self.height_px - 92
            painter.setPen(QtGui.QPen(QtGui.QColor(180,180,180), 1))
            # painter.drawRect(0, 0, self.width_px-1, self.height_px-1)

            # min/max dB | hover freq overlay
            painter.fillRect(4, overlay_y + 22, 120, 52, QtGui.QColor(60,60,60,150))
            painter.setPen(QtGui.QPen(QtGui.QColor(255,255,255), 1))
            painter.drawText(8, overlay_y + 38, f"Min dB: {self.min_db:.0f}")
            painter.drawText(8, overlay_y + 54, f"Max dB: {self.max_db:.0f}")
            painter.drawText(8, overlay_y + 54 + 16, f"{self.hover_freq/1000000:.3f}")

            # --- rysowanie pionowych linii: selected (żółta) i hover (cyjan)
            # mapowanie freq -> x
            vis_start, vis_end = self._visible_freq_range()
            bw = max(1e-9, (vis_end - vis_start))
            if self.selected_freq is not None:
                if vis_start <= self.selected_freq <= vis_end:
                    x_sel = int((self.selected_freq - vis_start) / bw * (self.width_px - 1))
                    pen_sel = QtGui.QPen(QtGui.QColor(255, 255, 0, 220), 2)  # żółta
                    painter.setPen(pen_sel)
                    painter.drawLine(x_sel, 0, x_sel, self.height_px)
                    # draw frequency label
                    painter.fillRect(x_sel, x_sel + 100, self.height_px - 2, self.height_px + 12, QtGui.QColor(60,60,60,150))
                    painter.drawText(x_sel, self.height_px - 2, f"{self.selected_freq/1000000:.4f}")
            if self.hover_freq is not None:
                if vis_start <= self.hover_freq <= vis_end:
                    x_h = int((self.hover_freq - vis_start) / bw * (self.width_px - 1))
                    pen_h = QtGui.QPen(QtGui.QColor(0, 255, 255, 180), 1)   # cyjan
                    painter.setPen(pen_h)
                    painter.drawLine(x_h, 0, x_h, self.height_px)
                    painter.drawText(x_h, self.height_px - 12, f"{self.hover_freq/1000000:.4f}")

class WsReceiver(threading.Thread, QtCore.QObject):
    push_row_signal = QtCore.pyqtSignal(object)
    config_signal = QtCore.pyqtSignal(dict)

    def __init__(self, ws_url, fft_size=FFT_SIZE):
        threading.Thread.__init__(self, daemon=True)
        QtCore.QObject.__init__(self)
        self.ws_url = ws_url
        self.fft_size = fft_size
        self.fft_codec = ImaAdpcmCodec()
        self._stop_event = threading.Event()
        self._ws = None
        self.samp_rate = 1000000
        self.center_freq = 14250000

    def stop(self):
        self._stop_event.set()
        try:
            if self._ws:
                self._ws.close()
        except Exception:
            pass

    def send_set_frequency(self, frequency, key=""):
        """
        Wyślij do serwera żądanie ustawienia częstotliwości w formacie:
        {"type":"setfrequency", "params": {"frequency": f, "key": key}}
        Metoda jest bezpieczna (try/except) — jeśli ws nie jest połączone, wypisze błąd.
        """
        low_freq = self.center_freq - self.samp_rate / 2
        high_freq = self.center_freq + self.samp_rate / 2
        if frequency > high_freq or frequency < low_freq:
            print('Changing SDR frequency...')
            try:
                if self._ws and hasattr(self._ws, "send"):
                    # self._ws.send('{"type":"selectprofile","params":{"profile":"rtlsdr|779c5b11-073a-46ce-a24c-2b5582e2d1c5"}}')
                    # self._ws.send('{"type":"selectprofile","params":{"profile":"rtlsdr|fe3d216f-4ac8-4c3e-ae4b-6f498f616c7a"}}')

                    cmd = '{"type":"setfrequency","params":{"frequency":' + str(int(frequency)) + '}}'
                    print(cmd)
                    self._ws.send(cmd)
                else:
                    print("WsReceiver: no active ws to send setfrequency")
            except Exception as e:
                print("WsReceiver: failed to send setfrequency:", e)

    def run(self):
        HEADER_SIZE = 6
        COMPRESS_FFT_PAD_N = 10

        def on_message(ws, message):
            if isinstance(message, str):
                try:
                    json_msg = json.loads(message)
                except Exception:
                    return
                # jeśli to wiadomość config -> wyemituj
                if 'type' in json_msg and 'config' in json_msg['type']:
                    val = json_msg.get('value', {})
                    cfg = {}
                    if 'fft_size' in val:
                        self.fft_size = val['fft_size']
                        cfg['fft_size'] = self.fft_size
                    if 'samp_rate' in val:
                        self.samp_rate = val['samp_rate']
                        cfg['samp_rate'] = self.samp_rate
                    if 'center_freq' in val:
                        self.center_freq = val['center_freq']
                        # print(self.center_freq)
                        cfg['center_freq'] = self.center_freq
                    if cfg:
                        # emitujemy konfigurację do UI
                        self.config_signal.emit(cfg)
                return

            data = message
            if len(data) < HEADER_SIZE:
                return
            frame_type = data[0]
            payload = data[HEADER_SIZE:]
            if frame_type == 1:
                if len(payload) == FFT_SIZE:
                    # dekodowanie (przyjmujemy waterfall_i16 -> dB style)
                    self.fft_codec.reset()
                    waterfall_i16 = self.fft_codec.decode(data)
                    waterfall_f32 = []
                    for i in range(len(waterfall_i16) - COMPRESS_FFT_PAD_N):
                        waterfall_f32.append(waterfall_i16[i + COMPRESS_FFT_PAD_N] / 100.0)
                    self.push_row_signal.emit(np.array(waterfall_f32, dtype=np.float32))

        def on_error(ws, error):
            print("WS error:", error)

        def on_close(ws, code, msg):
            print("WS closed", code, msg)

        def on_open(ws):
            # print("WS open:", self.ws_url)
            ws.send('SERVER DE CLIENT client=openwebrx.js type=receiver')
            # TODO:
            # self._ws.send('{"type":"selectprofile","params":{"profile":"rtlsdr|779c5b11-073a-46ce-a24c-2b5582e2d1c5"}}')
            # self._ws.send('{"type":"selectprofile","params":{"profile":"rtlsdr|fe3d216f-4ac8-4c3e-ae4b-6f498f616c7a"}}')

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


class WaterfallWindow(QtWidgets.QMainWindow):
    freq_changed = QtCore.pyqtSignal(int)  # sygnał do głównego okna
    waterfall_freq_change = QtCore.pyqtSignal(int) # signal to waterfall widget

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Waterfall Display - OpenWebRX+")
        self.setWindowIcon(QIcon("logo.ico"))

        sizeObject = QtWidgets.QDesktopWidget().screenGeometry(-1)
        self.setGeometry(1, 35, sizeObject.width() - 32, 200)

        # --- central widget ---
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        # --- layout główny ---
        layout = QtWidgets.QVBoxLayout(central)

        # --- waterfall ---
        self.waterfall_widget = WaterfallWidget(width=self.width(), height=self.height())
        layout.addWidget(self.waterfall_widget)

        # --- sterowanie ---
        controls = QtWidgets.QHBoxLayout()

        controls.addWidget(QtWidgets.QLabel("Min dB:"))
        self.min_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.min_slider.setRange(-160, -10)
        self.min_slider.setValue(int(self.waterfall_widget.min_db))
        self.min_slider.valueChanged.connect(self.on_min_changed)
        controls.addWidget(self.min_slider)
        self.min_label = QtWidgets.QLabel(f"{int(self.waterfall_widget.min_db)} dB")
        controls.addWidget(self.min_label)

        controls.addSpacing(20)
        controls.addWidget(QtWidgets.QLabel("Max dB:"))
        self.max_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.max_slider.setRange(-160, 0)
        self.max_slider.setValue(int(self.waterfall_widget.max_db))
        self.max_slider.valueChanged.connect(self.on_max_changed)
        controls.addWidget(self.max_slider)
        self.max_label = QtWidgets.QLabel(f"{int(self.waterfall_widget.max_db)} dB")
        controls.addWidget(self.max_label)

        layout.addLayout(controls)

        # --- połączenia WebSocket, itd. ---
        self.ws_thread = WsReceiver(WS_URL, fft_size=FFT_SIZE)
        self.ws_thread.push_row_signal.connect(self.waterfall_widget.push_row)
        self.ws_thread.config_signal.connect(self.waterfall_widget.update_config)
        self.waterfall_freq_change.connect(self.waterfall_widget.update_selected_freq)
        self.waterfall_widget.samp_rate = self.ws_thread.samp_rate
        self.waterfall_widget.center_freq = self.ws_thread.center_freq
        self.waterfall_widget.freq_clicked.connect(self.on_freq_clicked)
        self.waterfall_widget.freq_hover.connect(self.on_freq_hover)
        self.ws_thread.start()


    def on_min_changed(self, val):
        self.waterfall_widget.set_min_db(val)
        self.min_label.setText(f"{val} dB")

    def on_max_changed(self, val):
        self.waterfall_widget.set_max_db(val)
        self.max_label.setText(f"{val} dB")

    def on_freq_clicked(self, freq: int):
        freq = int(freq - freq%100)
        # print(f"User clicked freq: {freq}")
        self.freq_changed.emit(freq)  # wysyłamy sygnał do rodzica

        # wysyłamy do WsReceiver (metoda wysyłająca została dodana)
        try:
            if hasattr(self, "ws_thread") and self.ws_thread is not None:
                self.ws_thread.send_set_frequency(freq, key="")
        except Exception as e:
            print("Failed to request setfrequency:", e)

    def on_freq_update(self, freq):
        # print(f"WaterfallWindow otrzymał częstotliwość: {freq}")
        self.waterfall_freq_change.emit(freq)
        try:
            if hasattr(self, "ws_thread") and self.ws_thread is not None:
                self.ws_thread.send_set_frequency(freq, key="")
        except Exception as e:
            print("Failed to request setfrequency:", e)

    def on_freq_hover(self, freq):
        # aktualnie nic konkretnego nie robimy — widget narysuje pionową kreskę sam
        # ale możemy np. wyświetlić w stanie okna lub statusbar (tu tylko print)
        # print(f"hover freq: {freq}")
        pass

    def closeEvent(self, event):
        # zatrzymanie wątku (jeśli masz)
        if hasattr(self, "ws_thread") and self.ws_thread.is_alive():
            self.ws_thread.stop()
            self.ws_thread.join(timeout=1)

        # poinformuj główne okno, że okno zostało zamknięte
        if hasattr(self, "main_ref"):
            self.main_ref.waterfall_window = None

        super().closeEvent(event)

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    w = WaterfallWindow()
    w.show()
    sys.exit(app.exec_())
