#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Aplikacja PyQt5 imitująca front Yaesu FT‑450D:
- Dwie gałki: SQUELCH i VOLUME
- Odczyt S‑metra (jako pasek)
- Odczyt w osobnym wątku (QThread)
- Polling zagregowany: wAG0;SQ0;SM0; -> trzy wartości naraz
- Podczas kręcenia gałką nie synchronizuje się z radiem; po puszczeniu wysyła komendę ustawiającą
"""

import sys
import socket
import re
import time
import threading
from soundPlayer import playSound, stopSound
from pynput import keyboard
from PyQt5.QtCore import QTimer
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtGui import QIcon
import os 

import numpy as np
import websocket
import json

dir_path = os.path.dirname(os.path.realpath(__file__))

### --- Configuration --- ###
# Connection
HOST = "192.168.152.12"
PORT = 4532
TCP_TIMEOUT = 0.1
POLL_MS = 500
SLOWER_POLL_MS = 2000
MAX_RETRY_CNT = 3

# Functional
PLAYER_ACTIVE = False
FREQ_STEP_SLOW = 100
FREQ_STEP_FAST = 2500
TX_OFF_DELAY = 100
PTT_KEY = 'ctrl_r'
FST_KEY_MOD = 'shift'
FST_KEY = 'w'

# Graphics
WINDOW_WIDTH_PERCENTAGE  = 80
WINDOW_HEIGHT_PERCENTAGE = 35
BUTTON_COLOR = "#FFDF85"
NOT_ACTIVE_COLOR = "lightgray"
ACTIVE_COLOR = "lightgreen"

ROUND_BUTTON_SIZE = 40

SMALL_BTN_WIDTH  = 56
SMALL_BTN_HEIGHT = 28

BIG_KNOB_SIZE   = 50
SMALL_KNOB_SIZE = 40
KNOB_FONT_SIZE  = 10

# Radio width
FILTER_WIDTH_USB_NARROW = 1800
FILTER_WIDTH_USB_NORMAL = 2400
FILTER_WIDTH_USB_WIDE   = 3000

FILTER_WIDTH_LSB_NARROW = 1800
FILTER_WIDTH_LSB_NORMAL = 2400
FILTER_WIDTH_LSB_WIDE   = 3000

FILTER_WIDTH_AM_NARROW  = 3000
FILTER_WIDTH_AM_NORMAL  = 6000
FILTER_WIDTH_AM_WIDE    = 9000

FILTER_WIDTH_FM_NARROW  = 2500
FILTER_WIDTH_FM_NORMAL  = 5000
FILTER_WIDTH_FM_WIDE    = 5000

FILTER_WIDTH_CW_NARROW  = 300
FILTER_WIDTH_CW_NORMAL  = 500
FILTER_WIDTH_CW_WIDE    = 2400

FILTER_WIDTH_CWR_NARROW  = 300
FILTER_WIDTH_CWR_NORMAL  = 500
FILTER_WIDTH_CWR_WIDE    = 2400

# Misc
SWR_METER = 1
ALC_METER = 2
PO_METER  = 3
DEFAULT_TX_METER = SWR_METER

DEFAULT_NOISE_REDUCTION = 5

REC1_PATH = dir_path + '/recs/sp9pho_en.wav'
REC2_PATH = dir_path + '/recs/cq_sp9pho.wav'

# Antenna switch
ANTENNA_SWITCH_ENABLED = True
ANTENNA_SWITCH_PORT = 5000
ANTENNA_1_NAME = 'Hex'
ANTENNA_1_CMD = '1'
ANTENNA_2_NAME = 'Dpl'
ANTENNA_2_CMD = '2'
ANTENNA_3_NAME = 'End'
ANTENNA_3_CMD = '3'

# Waterfall
WS_URL = "ws://" + HOST + ":8073/ws/"
DEFAULT_FFT_SIZE = 2048

INITIAL_ZOOM = 0.25
WATERFALL_MIN_DB_DEFAULT = -90
WATERFALL_DYNAMIC_RANGE = 25

MOUSE_WHEEL_FREQ_STEP = 100

WATERFALL_MARGIN   = 32
MAJOR_THICK_HEIGHT = 12
MINOR_TICK_HEIGHT  = 6
MINOR_TICKS_PER_MAJOR = 10  # ile ticków pomiędzy głównymi (0 = brak)

HAM_BANDS = [
    ("160m", 1_800_000, 2_000_000),
    ("80m", 3_500_000, 4_000_000),
    ("60m", 5_250_000, 5_450_000),
    ("40m", 7_000_000, 7_300_000),
    ("30m", 10_100_000, 10_150_000),
    ("20m", 14_000_000, 14_350_000),
    ("17m", 18_068_000, 18_168_000),
    ("15m", 21_000_000, 21_450_000),
    ("12m", 24_890_000, 24_990_000),
    ("10m", 28_000_000, 29_700_000),
    ("6m", 50_000_000, 54_000_000),
]

WF_THEME = [
    0x000020, 0x000030, 0x000050, 0x000091, 0x1E90FF, 0xFFFFFF, 0xFFFF00,
    0xFE6D16, 0xFF0000, 0xC60000, 0x9F0000, 0x750000, 0x4A0000
]
### --- End of configuration --- ###

cyclicRefreshParams = ['AG0', 'SQ0', 'RM0', 'RM1', 'RM4', 'RM5', 'RM6', 'PS', 'FA', 'FB', 'PC', 'AC', 'TX', 'RA0', 'PA0', 'VS', 'NB0', 'MD0', 'ML0', 'SH0', 'IS0', 'BP00']

cyclicRefreshParams = [
    {'cmd': 'l AF', 'respLines': 1, 'parser': 'parse_af_gain'},
    {'cmd': 'l SQL', 'respLines': 1, 'parser': 'parse_sql_lvl'},
    {'cmd': 'l STRENGTH', 'respLines': 1, 'parser': 'parse_strength'},
    {'cmd': 'l RFPOWER_METER', 'respLines': 1, 'parser': 'parse_rf_power_meter'},
    {'cmd': 'l ALC', 'respLines': 1, 'parser': 'parse_alc'},
    {'cmd': 'l SWR', 'respLines': 1, 'parser': 'parse_swr'},
    {'cmd': '\\get_powerstat', 'respLines': 1, 'parser': 'parse_powerstat'},
    {'cmd': 'f', 'respLines': 1, 'parser': 'parse_freq'},
    {'cmd': '\\get_vfo_info VFOA', 'respLines': 5, 'parser': 'parse_vfoa'},
    {'cmd': '\\get_vfo_info VFOB', 'respLines': 5, 'parser': 'parse_vfob'},
    {'cmd': 'l RFPOWER', 'respLines': 1, 'parser': 'parse_rf_power'},
    {'cmd': 'u TUNER', 'respLines': 1, 'parser': 'parse_tuner', 'oneTime': True},
    {'cmd': 't', 'respLines': 1, 'parser': 'parse_tx'},
    {'cmd': 'l PREAMP', 'respLines': 1, 'parser': 'parse_preamp', 'oneTime': True},
    {'cmd': 'v', 'respLines': 1, 'parser': 'parse_vfo'},
    {'cmd': 'u NB', 'respLines': 1, 'parser': 'parse_nb', 'oneTime': True},
    {'cmd': 'u MON', 'respLines': 1, 'parser': 'parse_mon', 'oneTime': True},
    {'cmd': 'l IF', 'respLines': 1, 'parser': 'parse_if', 'oneTime': True},
    {'cmd': 'u MN', 'respLines': 1, 'parser': 'parse_mn', 'oneTime': True},
    {'cmd': 'l NOTCHF', 'respLines': 1, 'parser': 'parse_notchf', 'oneTime': True},
    {'cmd': 'u NR', 'respLines': 1, 'parser': 'parse_u_nr', 'oneTime': True},
    {'cmd': 'l NR', 'respLines': 1, 'parser': 'parse_l_nr', 'oneTime': True},
    {'cmd': 'l ATT', 'respLines': 1, 'parser': 'parse_att', 'oneTime': True},
    # {'cmd': 'wRA0;', 'respLines': 1, 'parser': 'parse_att'},
    # {'cmd': 'wRA0;', 'respLines': 1, 'parser': 'parse_att'},
]

radioModesRx = ['', 'LSB', 'USB', 'CW', 'FM', 'AM', 'DATA-L', 'CWR', 'USER-L', 'DATA-U']
radioModesTx = ['', 'LSB', 'USB', 'CW', 'FM', 'AM', 'CWR']

def findIndexOfString(element, matrix):
    for i in range(len(matrix)):
        if matrix[i] == element:
            return i

class RigctlClient:
    def __init__(self, host: str, port: int, timeout: float = TCP_TIMEOUT):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.trx_power_status = 0
        try:
            self.s = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self.connected = 1
        except:
            self.connected = 0

    def send(self, cmd: str):
        if not cmd.endswith("\n"):
            cmd = cmd + "\n"
        try:
            if hasattr(self, 's') :#and self.retry_cnt < MAX_RETRY_CNT:
                self.s.settimeout(self.timeout)
                self.s.sendall(cmd.encode("ascii", errors="ignore"))
                chunks = []
                while True:
                    try:
                        data = self.s.recv(1024)
                        if not data:
                            break
                        chunks.append(data)
                        if b"\n" in data or b"\0" in data:
                            break
                    except socket.timeout:
                        # print('timeout')
                        break
                resp = b"".join(chunks).decode("utf-8", errors="ignore").strip()
                # print(resp)
            else:
                resp = None
            return resp or None
        except (OSError, ConnectionError):
            return None


def parse_level_from_response(resp):
    if resp is None:
        return None
    m = re.search(r"(-?\d+)", resp)
    if not m:
        return None
    try:
        val = int(m.group(1))
        val = max(0, min(255, val))
        return val
    except ValueError:
        return None


class BigKnob(QtWidgets.QWidget):
    released = QtCore.pyqtSignal(int)

    def __init__(self, title: str, parent=None, size: int = 100, value_label_visible=True):
        super().__init__(parent)
        self.title = title
        self.user_active = False

        self.dial = QtWidgets.QDial()
        self.dial.setRange(0, 100)
        self.dial.setNotchesVisible(True)
        self.dial.setWrapping(False)
        self.dial.setFixedSize(size, size)   # <<< używamy parametru size
        self.dial.setSingleStep(1)
        self.dial.setPageStep(1)

        self.dial.sliderPressed.connect(self._on_pressed)
        self.dial.sliderReleased.connect(self._on_released)

        self.value_label = QtWidgets.QLabel("—")
        self.value_label.setAlignment(QtCore.Qt.AlignCenter)
        self.value_label.setFont(QtGui.QFont("Monospace", KNOB_FONT_SIZE))

        self.title_label = QtWidgets.QLabel(self.title)
        self.title_label.setAlignment(QtCore.Qt.AlignCenter)
        self.title_label.setFont(QtGui.QFont("Monospace", KNOB_FONT_SIZE))
        self.title_label.setStyleSheet("letter-spacing: 0px; font-weight: 600;")

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.title_label)
        layout.addWidget(self.dial, alignment=QtCore.Qt.AlignCenter)
        layout.addStretch(1)
        if value_label_visible:
            layout.addWidget(self.value_label)

        self.dial.installEventFilter(self)

        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_idle_after_move)

    def _on_pressed(self):
        self.user_active = True
        # print('pressed')

    def _on_released(self):
        self.user_active = False

    def set_value(self, v):
        if v is None:
            self.value_label.setText("—")
            return
        self.dial.blockSignals(True)
        self.dial.setValue(v)
        self.dial.blockSignals(False)
        self.value_label.setText(f"{v:3d}")

    def eventFilter(self, obj, event):
        if obj is self.dial and event.type() == QtCore.QEvent.Wheel:
            delta = event.angleDelta().y()
            if delta > 0:
                if self.dial.value() < self.dial.maximum():
                    # self.released.emit(self.dial.value() + 1)
                    self.value_label.setText(f"{self.dial.value() + self.dial.pageStep():3d}")
            else:
                if self.dial.value() > self.dial.minimum():
                    # self.released.emit(self.dial.value() - 1)
                    self.value_label.setText(f"{self.dial.value() - self.dial.pageStep():3d}")

            # restartujemy timer na 500 ms
            self._timer.start(500)
            self.user_active = True
        return super().eventFilter(obj, event)
    
    def _on_idle_after_move(self):
        """to wywoła się dopiero 500 ms po ostatnim ruchu"""
        # print(f"BigKnob: zatrzymałeś się na {self.dial.value()}")
        self.user_active = False

class SliderDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, value=5):
        super().__init__(parent)
        self.setWindowTitle("Set value")

        # Slider od 5 do 100
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(5, 100)
        self.slider.setValue(value)

        # Etykieta pokazująca aktualną wartość
        self.label = QtWidgets.QLabel(str(self.slider.value()))
        self.slider.valueChanged.connect(lambda v: self.label.setText(str(v)))

        # Przycisk 'Ustaw'
        self.button = QtWidgets.QPushButton("Set")
        self.button.clicked.connect(self.accept)  # zamyka dialog

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.label)
        layout.addWidget(self.slider)
        layout.addWidget(self.button)
        self.setLayout(layout)

    def get_value(self):
        return self.slider.value()
    
class ListDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose action")
        self.setGeometry(400, 400, 250, 120)

        layout = QtWidgets.QVBoxLayout()

        self.combo = QtWidgets.QComboBox(self)
        self.combo.addItems(["SWR", "VM1TX", "VM2TX"])
        layout.addWidget(self.combo)

        self.label = QtWidgets.QLabel("Choose from the list...", self)
        layout.addWidget(self.label)

        self.combo.currentIndexChanged.connect(self.update_label)

        self.setLayout(layout)

    def update_label(self):
        self.label.setText(f"Action set: {self.combo.currentText()}")

class PollWorker(QtCore.QObject):
    result = QtCore.pyqtSignal(object)  # key, value
    status = QtCore.pyqtSignal(str)
    reset_one_time = QtCore.pyqtSignal(str)   # argument: cmd

    def __init__(self, host: str, port: int, poll_ms: int = POLL_MS):
        super().__init__()
        self.client = RigctlClient(host, port, timeout=TCP_TIMEOUT)
        self.poll_ms = poll_ms
        self._timer = None
        self.retry_cnt = 0
        self.tx_active = 0
        self.one_time_done = set()
        self.reset_one_time.connect(self.on_reset_one_time)

    @QtCore.pyqtSlot()
    def start(self):
        self._timer = QtCore.QTimer()
        self._timer.setInterval(self.poll_ms)
        self._timer.timeout.connect(self.poll_all)
        self._timer.start()
        self.poll_all()  # pierwszy odczyt

    @QtCore.pyqtSlot(int)
    def pause(self, ms: int):
        """Zatrzymuje polling na podany czas (ms)."""
        if self._timer and self._timer.isActive():
            self._timer.stop()
            # print('pause')
            QtCore.QTimer.singleShot(ms, self.resume)

    @QtCore.pyqtSlot()
    def resume(self):
        """Wznawia polling."""
        self.retry_cnt = 0
        self._timer.setInterval(self.poll_ms)
        # print(self.poll_ms)
        if self._timer and not self._timer.isActive():
            self._timer.start()

    @QtCore.pyqtSlot(int)
    def tx_action(self, val: int):
        if val:
            self.tx_active = 1
        else:
            self.tx_active = 0

    @QtCore.pyqtSlot(str)
    def on_reset_one_time(self, cmd: str):
        """Pozwala ponownie wykonać pojedynczy odczyt polecenia oneTime."""
        if cmd in self.one_time_done:
            print(f"[oneTime] Reset: {cmd}")
            self.one_time_done.remove(cmd)


    def poll_all(self):
        if not self.client.connected:
            try:
                self.client = RigctlClient(HOST, PORT, timeout=TCP_TIMEOUT)
            except:
                pass
            return
        
        cmd = ''

        for param in cyclicRefreshParams:
            command = param['cmd']
            is_one_time = param.get('oneTime', False)

            # pomijamy oneTime, jeśli już wykonane
            if is_one_time and command in self.one_time_done:
                continue

            # pomijamy przy TX (opcjonalnie)
            if getattr(self, "tx_active", 0) == 1 and is_one_time:
                continue

            # dodajemy komendę do zestawu
            cmd += '+' + command + ' '

        cmd += '\n'
        print(cmd)

        resp = self.client.send(cmd)
        # print(resp)

        if not resp:
            self.status.emit(f"No answer from {HOST}:{PORT}")
            if self.retry_cnt > MAX_RETRY_CNT:
                self._timer.setInterval(POLL_MS)
            else:
                self.retry_cnt += 1
            return

        parts = re.split(r'(RPRT [+-]?\d+)', resp)

        respArray = []
        tmp = ""

        for part in parts:
            if re.match(r'RPRT [+-]?\d+', part):
                # to jest końcowy znacznik -> dodaj do aktualnego bloku i zamknij blok
                tmp += part + "\n"
                respArray.append(tmp)
                tmp = ""
            else:
                # część danych
                tmp += part

        # usuwamy puste elementy
        respArray =  [b for b in respArray if b.strip()]

        print(respArray)

        self.result.emit(respArray)

        # oznaczamy oneTime jako wykonane
        for param in cyclicRefreshParams:
            if param.get('oneTime', False):
                cmd = param['cmd']
                if cmd not in self.one_time_done:
                    self.one_time_done.add(cmd)

        return 

class DoubleClickButton(QtWidgets.QPushButton):
    singleClicked = QtCore.pyqtSignal()
    doubleClicked = QtCore.pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._click_timer = QtCore.QTimer()
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._emit_single)

    def mousePressEvent(self, event):
        if self._click_timer.isActive():
            # znaczy, że drugi klik nastąpił zanim timer się wyzerował -> double click
            self._click_timer.stop()
            self.doubleClicked.emit()
        else:
            # odpalamy timer i czekamy czy nadejdzie drugi klik
            self._click_timer.start(QtWidgets.QApplication.doubleClickInterval())
        super().mousePressEvent(event)

    def _emit_single(self):
        self.singleClicked.emit()


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
        self.height_px = int(height/2)
        self.setMinimumSize(400, int(height/2))

        # QImage jako bufor tylko do wyświetlania; trzymamy też _buffer (numpy) żeby bezpiecznie modyfikować
        self._image = QtGui.QImage(self.width_px, self.height_px, QtGui.QImage.Format_RGB888)
        self._image.fill(QtGui.QColor('black'))
        self._buffer = np.zeros((self.height_px, self.width_px, 3), dtype=np.uint8)
        self.setMouseTracking(True)

        self._lock = threading.Lock()
        self.min_db = WATERFALL_MIN_DB_DEFAULT
        self.max_db = self.min_db + WATERFALL_DYNAMIC_RANGE
        self.fft_avg = 0

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
        self.filter_width = FILTER_WIDTH_USB_NORMAL
        self.mode = 'USB'

        self.waterfall_config_received = False
        self.initial_zoom_set = False

    def set_min_db(self, value):
        self.min_db = int(value)

    def set_max_db(self, value):
        self.max_db = int(value)

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
            self.samp_rate = int(cfg['samp_rate'])
        if 'center_freq' in cfg:
            if self.center_freq != int(cfg['center_freq']):
                self.initial_zoom_set = False
            self.center_freq = int(cfg['center_freq'])
            if not self.waterfall_config_received:
                self.waterfall_config_received = True
        # redraw labels
        self.update()

    @QtCore.pyqtSlot(int, int, str)
    def update_selected_freq(self, freq, width, mode):
        self.selected_freq = freq
        self.filter_width = width
        self.mode = mode

        if not self.initial_zoom_set and self.waterfall_config_received and self.fft_avg != 0:
            # modyfikacja zoomu
            self.zoom_factor = INITIAL_ZOOM
            # ograniczenia zoomu
            self.zoom_factor = max(0.05, min(1.0, self.zoom_factor))
            # zmiana środka widoku, aby utrzymać tę samą częstotliwość pod kursorem
            if hasattr(self, "samp_rate") and self.samp_rate > 0:
                full_bw = self.samp_rate
                start_freq = self.center_freq - self.samp_rate/2
                self.center_pos = (freq - start_freq)/(full_bw) # np.clip(self.center_pos + delta_norm, 0.0, 1.0)

            # waterfall levels adjustment
            self.min_db = self.fft_avg - WATERFALL_DYNAMIC_RANGE * 0.3
            self.max_db = self.min_db + WATERFALL_DYNAMIC_RANGE

            self.initial_zoom_set = True
            self.update()

    def resizeEvent(self, event):
        new_size = event.size()
        self.width_px = new_size.width()
        self.height_px = new_size.height()

        # utwórz nowy QImage i bufor numpy dopasowany do nowego rozmiaru
        self._image = QtGui.QImage(self.width_px, self.height_px, QtGui.QImage.Format_RGB888)
        self._image.fill(QtGui.QColor('black'))

        with self._lock:
            self._buffer = np.zeros((self.height_px, self.width_px, 3), dtype=np.uint8)

        # możesz opcjonalnie odświeżyć widok
        self.update()

        # wywołaj oryginalne zachowanie (dobre praktyki)
        super().resizeEvent(event)

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
        self.fft_avg = sum(fft_row) / n
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

            # --- rysowanie zielonych pasów dla pasm amatorskich
            for name, f_start, f_end in HAM_BANDS:
                # jeśli pasmo w ogóle widoczne na aktualnym zakresie
                if f_end < vis_start or f_start > vis_end:
                    continue

                # oblicz widoczny fragment
                start_clamped = max(f_start, vis_start)
                end_clamped = min(f_end, vis_end)

                # przelicz na piksele
                x1 = int((start_clamped - vis_start) / bw * (self.width_px - 1))
                x2 = int((end_clamped - vis_start) / bw * (self.width_px - 1))

                # szerokość (min. 2px żeby było widać nawet przy zoomie)
                w = max(2, x2 - x1)

                # półprzezroczysty zielony pasek
                painter.fillRect(x1, WATERFALL_MARGIN - 10, w, 10, QtGui.QColor(0, 200, 0, 90))

                # etykieta pasma (jeśli się mieści)
                text = name
                tw = metrics.horizontalAdvance(text)
                if w > tw + 4:
                    painter.setPen(QtGui.QPen(QtGui.QColor(150, 255, 150), 1))
                    painter.drawText(x1 + (w - tw) // 2, WATERFALL_MARGIN - 2, text)

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
                    # filter width
                    x_width = x_sel
                    width = int((self.selected_freq + self.filter_width - vis_start) / bw * (self.width_px - 1))
                    if self.mode == 'USB':
                        width = int((self.selected_freq + self.filter_width - vis_start) / bw * (self.width_px - 1))
                    elif self.mode == 'LSB':
                        width = int((self.selected_freq - self.filter_width - vis_start) / bw * (self.width_px - 1))
                    elif self.mode == 'CW':
                        width = int((self.selected_freq - self.filter_width - vis_start) / bw * (self.width_px - 1))
                    elif self.mode == 'AM' or self.mode == 'FM':
                        width = int((self.selected_freq + self.filter_width/2 - vis_start) / bw * (self.width_px - 1))
                        x_width = int((self.selected_freq - self.filter_width/2 - vis_start) / bw * (self.width_px - 1))

                    painter.fillRect(x_width, 0, width - x_width, self.height_px, QtGui.QColor(205,205,100,50))
                    # draw frequency label
                    # painter.fillRect(x_sel, x_sel + 100, self.height_px - 2, self.height_px + 12, QtGui.QColor(60,60,60,150))
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

    def __init__(self, ws_url, fft_size=DEFAULT_FFT_SIZE):
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

    def send_set_frequency(self, frequency):
        low_freq = self.center_freq - self.samp_rate / 2
        high_freq = self.center_freq + self.samp_rate / 2
        # Change SDR frequency when current frequency is outside bandwith
        if frequency > high_freq or frequency < low_freq:
            print('Changing SDR frequency...')
            try:
                if self._ws and hasattr(self._ws, "send"):
                    cmd = '{"type":"setfrequency","params":{"frequency":' + str(int(frequency + self.samp_rate / 6)) + '}}' # Add offset to not tune exactly on desired freq
                    self._ws.send(cmd)
                else:
                    print("WsReceiver: no active ws to send setfrequency")
            except Exception as e:
                print("WsReceiver: failed to send setfrequency:", e)

    def run(self):
        HEADER_SIZE = 6
        COMPRESS_FFT_PAD_N = 14

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
                        self.fft_size = 2048
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
            if len(data) < COMPRESS_FFT_PAD_N:
                return
            frame_type = data[0]
            if frame_type == 1:
                # if len(payload) == self.fft_size:
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

class MainWindow(QtWidgets.QMainWindow):
    send_tx_signal = QtCore.pyqtSignal(int)
    send_fst_signal = QtCore.pyqtSignal(int)
    pause_polling = QtCore.pyqtSignal(int)
    resume_polling = QtCore.pyqtSignal()
    sound_finished = QtCore.pyqtSignal(object)
    waterfall_freq_update = QtCore.pyqtSignal(int, int, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Remote Control - FT‑450D")

        sizeObject = QtWidgets.QDesktopWidget().availableGeometry(-1)
        windowWidth = int(WINDOW_WIDTH_PERCENTAGE / 100 * sizeObject.width())
        windowHeight = int(WINDOW_HEIGHT_PERCENTAGE / 100 * sizeObject.height())
        windowHeight = 400
        self.setGeometry(int((sizeObject.width() - windowWidth) / 2), sizeObject.height() - windowHeight, windowWidth, windowHeight)

        # self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
        self.setWindowIcon(QIcon("logo.ico"))

        # self.setWindowOpacity(0.8)

        self.ignore_next_data_switch = False
        self.ignore_next_data_cnt = 2

        self.tx_active = 0
        self.tx_sent = 0
        self.tx_meter = DEFAULT_TX_METER

        self.filter_width = FILTER_WIDTH_USB_NORMAL

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        # active vfo
        self.active_vfo_label = QtWidgets.QLabel()
        self.active_vfo_label.setFixedSize(SMALL_BTN_WIDTH, SMALL_BTN_HEIGHT)
        self.active_vfo_label.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border: 1px solid black; border-radius: 4px;")
        self.active_vfo_label.setAlignment(QtCore.Qt.AlignCenter)
        self.active_vfo_label.setFont(QtGui.QFont("Monospace", 10, QtGui.QFont.Bold))
        self.active_vfo_label.setText("VFO A")
        self.active_vfo = 0

        # mode
        self.mode_label = QtWidgets.QLabel()
        self.mode_label.setFixedSize(SMALL_BTN_WIDTH, SMALL_BTN_HEIGHT)
        self.mode_label.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border: 1px solid black; border-radius: 4px;")
        self.mode_label.setAlignment(QtCore.Qt.AlignCenter)
        self.mode_label.setFont(QtGui.QFont("Monospace", 10, QtGui.QFont.Bold))
        self.mode_label.setText("USB")

        # pionowy układ dla obu
        left_layout = QtWidgets.QVBoxLayout()
        left_layout.setSpacing(2)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.active_vfo_label)
        left_layout.addWidget(self.mode_label)

        left_widget = QtWidgets.QWidget()
        left_widget.setLayout(left_layout)

        self.att_btn = QtWidgets.QPushButton()
        self.att_btn.setFixedSize(SMALL_BTN_WIDTH, SMALL_BTN_HEIGHT)
        self.att_btn.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px;")
        self.att_btn.setText("ATT")
        self.att_btn.clicked.connect(self.att_btn_clicked)

        self.ipo_btn = QtWidgets.QPushButton()
        self.ipo_btn.setFixedSize(SMALL_BTN_WIDTH, SMALL_BTN_HEIGHT)
        self.ipo_btn.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px;")
        self.ipo_btn.setText("IPO")
        self.ipo_btn.clicked.connect(self.ipo_btn_clicked)

        self.tx_power_btn = QtWidgets.QPushButton()
        self.tx_power_btn.setFixedSize(SMALL_BTN_WIDTH, SMALL_BTN_HEIGHT)
        self.tx_power_btn.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
        self.tx_power_btn.setText("-W")

        # główna częstotliwość
        self.freq_display = QtWidgets.QLabel("--- MHz")
        self.freq_display.setFont(QtGui.QFont("Monospace", 12, QtGui.QFont.Bold))
        self.freq_display.setAlignment(QtCore.Qt.AlignCenter)
        self.set_frequency_label(self.freq_display, 0)

        # druga, mniejsza częstotliwość
        self.freq_display_sub = QtWidgets.QLabel("--- kHz")
        self.freq_display_sub.setFont(QtGui.QFont("Monospace", 10))
        self.freq_display_sub.setAlignment(QtCore.Qt.AlignCenter)

        # pionowy układ dla obu częstotliwości
        freq_layout = QtWidgets.QVBoxLayout()
        freq_layout.addWidget(self.freq_display)
        freq_layout.addWidget(self.freq_display_sub)

        # żeby się ładnie trzymały razem w środku
        freq_widget = QtWidgets.QWidget()
        freq_widget.setLayout(freq_layout)
        freq_widget.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; border-radius: 8px;")

        right_container = QtWidgets.QWidget()
        right_grid = QtWidgets.QGridLayout()
        right_grid.setHorizontalSpacing(6)
        right_grid.setVerticalSpacing(4)
        right_grid.setContentsMargins(0, 0, 0, 0)
        right_container.setLayout(right_grid)

        # pierwsza (istniejąca) linia przycisków
        right_grid.addWidget(self.att_btn,       0, 0)
        right_grid.addWidget(self.ipo_btn,       0, 1)
        right_grid.addWidget(self.tx_power_btn,  0, 2)

        # druga linia — na razie tylko NB pod pierwszym przyciskiem
        self.nb_btn = QtWidgets.QPushButton("NB")
        self.nb_btn.setFixedSize(SMALL_BTN_WIDTH, SMALL_BTN_HEIGHT)
        self.nb_btn.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
        # self.nb_btn.setFont(QtGui.QFont("Monospace", 7))
        self.nb_btn.clicked.connect(self.nb_btn_clicked)
        self.nb_active = 0

        self.tuner_status = DoubleClickButton()
        self.tuner_status.setFixedSize(SMALL_BTN_WIDTH, SMALL_BTN_HEIGHT)
        self.tuner_status.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px;")
        self.tuner_status.setText("TUNER")
        self.tuner_status_val = 0

        self.monitor_btn = QtWidgets.QPushButton("MONITOR")
        self.monitor_btn.setFixedSize(SMALL_BTN_WIDTH, SMALL_BTN_HEIGHT)
        self.monitor_btn.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
        self.monitor_btn.setText("MONITOR")
        # self.monitor_btn.setFont(QtGui.QFont("Monospace", 7))
        self.monitor_btn.clicked.connect(self.monitor_btn_clicked)
        self.monitor_active = 0

        right_grid.addWidget(self.nb_btn, 1, 0)
        right_grid.addWidget(self.tuner_status, 1, 1)
        right_grid.addWidget(self.monitor_btn, 1, 2)

        self.swr_btn = QtWidgets.QPushButton("SWR")
        self.swr_btn.setFixedSize(SMALL_BTN_WIDTH, SMALL_BTN_HEIGHT)
        self.swr_btn.setStyleSheet("background-color: " + "#e1a100" + "; text-align: center; border-radius: 4px; border: 1px solid black;")
        self.swr_btn.pressed.connect(self.swr_btn_pressed)
        self.swr_btn.released.connect(self.swr_btn_released)

        right_grid.addWidget(self.swr_btn, 2, 0)

        # --- GRUPA Z PRZYCISKAMI FREQ CTRL ---
        self.group_freq_ctrl = QtWidgets.QGroupBox("Freq Ctrl")
        self.group_freq_ctrl.setObjectName("groupFreqCtrl")

        # jeśli chcesz, żeby ramka miała stały rozmiar (opcjonalne)
        # self.group_freq_ctrl.setFixedSize(80, 80)
        self.group_freq_ctrl.setContentsMargins(12,0,12,0)

        # przyciski (jak masz już zdefiniowane, po prostu użyj tych obiektów)
        self.btn_freq_plus_slow = QtWidgets.QPushButton("+")
        self.btn_freq_plus_fast = QtWidgets.QPushButton("+\n+")
        self.btn_freq_minus_slow = QtWidgets.QPushButton("-")
        self.btn_freq_minus_fast = QtWidgets.QPushButton("-\n-")

        # ustaw rozmiary i politykę rozciągania (ważne)
        for btn in [self.btn_freq_plus_slow, self.btn_freq_plus_fast,
                    self.btn_freq_minus_slow, self.btn_freq_minus_fast]:
            btn.setFixedSize(32, 32)
            btn.setFont(QtGui.QFont("Monospace", 8, QtGui.QFont.Bold))
            btn.setStyleSheet(
                "background-color: " + NOT_ACTIVE_COLOR +
                "; text-align: center; border-radius: 8px; border: 1px solid black; margin: 0px; padding: 0px;"
            )
            btn.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

        # podłączenia
        self.btn_freq_plus_slow.clicked.connect(lambda: self.frequency_step(+1, FREQ_STEP_SLOW))
        self.btn_freq_plus_fast.clicked.connect(lambda: self.frequency_step(+1, FREQ_STEP_FAST))
        self.btn_freq_minus_slow.clicked.connect(lambda: self.frequency_step(-1, FREQ_STEP_SLOW))
        self.btn_freq_minus_fast.clicked.connect(lambda: self.frequency_step(-1, FREQ_STEP_FAST))

        # siatka 2x2 dla przycisków
        freq_grid = QtWidgets.QGridLayout()
        freq_grid.setVerticalSpacing(8)    # pionowy odstęp między wierszami (zbliż je)
        freq_grid.setHorizontalSpacing(8)  # odstęp między kolumnami
        freq_grid.setContentsMargins(0, 0, 0, 0)

        freq_grid.addWidget(self.btn_freq_plus_slow, 0, 0, QtCore.Qt.AlignCenter)
        freq_grid.addWidget(self.btn_freq_plus_fast, 0, 1, QtCore.Qt.AlignCenter)
        freq_grid.addWidget(self.btn_freq_minus_slow, 1, 0, QtCore.Qt.AlignCenter)
        freq_grid.addWidget(self.btn_freq_minus_fast, 1, 1, QtCore.Qt.AlignCenter)

        # główny layout grupy: użyj stretchów żeby wycentrować grid pionowo
        group_layout = QtWidgets.QVBoxLayout()
        group_layout.setContentsMargins(4, 20, 4, 8)
        group_layout.setSpacing(0)
        group_layout.addStretch(1)                  # zajmuje miejsce nad siatką
        group_layout.addLayout(freq_grid)          # siatka przycisków -> będzie wyśrodkowana
        group_layout.addStretch(1)                  # zajmuje miejsce pod siatką

        self.group_freq_ctrl.setLayout(group_layout)

        # dodaj grupę do głównego layoutu (tam gdzie chcesz)
        # main_layout.addWidget(self.group_freq_ctrl)



        self.current_freq = 14074000  # Hz (odczyt z rigctld)
        self.vfoa_freq = self.current_freq
        self.vfob_freq = self.current_freq

        self.knob_squelch = BigKnob("Squelch", size=SMALL_KNOB_SIZE)
        self.knob_squelch.dial.setNotchTarget(20.0)
        self.knob_squelch.dial.valueChanged.connect(self.squelch_change)
        self.last_squelch_pos = 0
        
        self.knob_volume = BigKnob("Volume", size=SMALL_KNOB_SIZE)
        self.knob_volume.dial.setNotchTarget(20.0)
        self.knob_volume.dial.valueChanged.connect(self.volume_change)
        self.last_volume_pos = 0

        knobs_row = QtWidgets.QHBoxLayout()
        # knobs_row.addWidget(self.knob_fast_freq, alignment=QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom)
        # knobs_row.addWidget(self.knob_freq, alignment=QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom)

        knobs_row.addWidget(self.knob_squelch, alignment=QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom)
        knobs_row.addWidget(self.knob_volume, alignment=QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom)


        # ---- bottom buttons: teraz w 2 rzędach
        btns_layout = QtWidgets.QVBoxLayout()
        self.buttons = []

        # pierwszy rząd
        btn_row1 = QtWidgets.QHBoxLayout()

        # drugi rząd
        btn_row2 = QtWidgets.QHBoxLayout()

        self.power_btn = QtWidgets.QPushButton("PWR")
        self.power_btn.setFixedSize(ROUND_BUTTON_SIZE, ROUND_BUTTON_SIZE) 
        self.power_btn.setStyleSheet("border-radius: 14px; background-color: lightgray; border: 1px solid black;")
        self.power_btn.setText("ON")
        btn_row1.addWidget(self.power_btn)
        self.buttons.append(self.power_btn)

        self.split_btn = QtWidgets.QPushButton("SPLIT")
        self.split_btn.setFixedSize(ROUND_BUTTON_SIZE, ROUND_BUTTON_SIZE)
        self.split_btn.setStyleSheet("border-radius: 14px; background-color: lightgray; border: 1px solid black;")
        btn_row2.addWidget(self.split_btn)
        self.buttons.append(self.split_btn)
        self.split_btn.clicked.connect(self.split_btn_clicked)
        self.split_active = 0

        self.band_up_btn = QtWidgets.QPushButton("BAND\n↑")
        self.band_up_btn.setFixedSize(ROUND_BUTTON_SIZE, ROUND_BUTTON_SIZE)
        self.band_up_btn.setStyleSheet("border-radius: 14px; background-color: lightgray; border: 1px solid black;")
        btn_row1.addWidget(self.band_up_btn)
        self.buttons.append(self.band_up_btn)
        self.band_up_btn.clicked.connect(self.band_up_btn_clicked)

        self.band_down_btn = QtWidgets.QPushButton("BAND\n↓")
        self.band_down_btn.setFixedSize(ROUND_BUTTON_SIZE, ROUND_BUTTON_SIZE)
        self.band_down_btn.setStyleSheet("border-radius: 14px; background-color: lightgray; border: 1px solid black;")
        btn_row2.addWidget(self.band_down_btn)
        self.buttons.append(self.band_down_btn)
        self.band_down_btn.clicked.connect(self.band_down_btn_clicked)

        self.a_eq_b_btn = QtWidgets.QPushButton("A = B")
        self.a_eq_b_btn.setFixedSize(ROUND_BUTTON_SIZE, ROUND_BUTTON_SIZE)
        self.a_eq_b_btn.setStyleSheet("border-radius: 14px; background-color: lightgray; border: 1px solid black;")
        btn_row1.addWidget(self.a_eq_b_btn)
        self.buttons.append(self.a_eq_b_btn)
        self.a_eq_b_btn.clicked.connect(self.a_eq_b_btn_clicked)

        self.vfo_switch_btn = QtWidgets.QPushButton("A / B")
        self.vfo_switch_btn.setFixedSize(ROUND_BUTTON_SIZE, ROUND_BUTTON_SIZE)
        self.vfo_switch_btn.setStyleSheet("border-radius: 14px; background-color: lightgray; border: 1px solid black;")
        btn_row2.addWidget(self.vfo_switch_btn)
        self.buttons.append(self.vfo_switch_btn)
        self.vfo_switch_btn.clicked.connect(self.vfo_switch_btn_clicked)

        self.ipo_att_btn = QtWidgets.QPushButton("IPO\n/ATT")
        self.ipo_att_btn.setFixedSize(ROUND_BUTTON_SIZE, ROUND_BUTTON_SIZE)
        self.ipo_att_btn.setStyleSheet("border-radius: 14px; background-color: lightgray; border: 1px solid black;")
        # btn_row1.addWidget(self.ipo_att_btn)
        self.buttons.append(self.ipo_att_btn)
        self.ipo_att_btn.clicked.connect(self.ipo_att_btn_clicked)

        # MODE ↑
        self.mode_up_btn = QtWidgets.QPushButton("MODE\n↑")
        self.mode_up_btn.setFixedSize(ROUND_BUTTON_SIZE, ROUND_BUTTON_SIZE)
        self.mode_up_btn.setStyleSheet("border-radius: 14px; background-color: lightgray; border: 1px solid black;")
        btn_row1.addWidget(self.mode_up_btn)
        self.buttons.append(self.mode_up_btn)
        self.mode_up_btn.clicked.connect(self.mode_up_btn_clicked)

        # MODE ↓
        self.mode_down_btn = QtWidgets.QPushButton("MODE\n↓")
        self.mode_down_btn.setFixedSize(ROUND_BUTTON_SIZE, ROUND_BUTTON_SIZE)
        self.mode_down_btn.setStyleSheet("border-radius: 14px; background-color: lightgray; border: 1px solid black;")
        btn_row2.addWidget(self.mode_down_btn)
        self.buttons.append(self.mode_down_btn)
        self.mode_down_btn.clicked.connect(self.mode_down_btn_clicked)

        btns_layout.addLayout(btn_row1)
        btns_layout.addLayout(btn_row2)

        self.ptt_btn = QtWidgets.QPushButton("PTT\n(" + PTT_KEY + ")")
        self.ptt_btn.setFixedSize(SMALL_BTN_WIDTH * 1, SMALL_BTN_HEIGHT * 3)
        self.ptt_btn.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 20px; border: 1px solid black;")
        self.ptt_btn.pressed.connect(self.ptt_btn_pressed)
        self.ptt_btn.released.connect(self.ptt_btn_released)

        METERS_FONT_SIZE = 9
        METERS_FONT = QtGui.QFont("Courier New", METERS_FONT_SIZE, QtGui.QFont.Bold)
        METERS_HEIGHT = 16
        METERS_WIDTH = self.width() - 30

        # ---- S-meter
        self.s_meter = QtWidgets.QProgressBar()
        self.s_meter.setRange(0, 255)
        self.s_meter.setFixedHeight(METERS_HEIGHT)
        # self.s_meter.setFixedWidth(METERS_WIDTH)
        self.s_meter.setFont(METERS_FONT)
        self.s_meter.setValue(0)
        self.s_meter.setFormat(f"S: {'-':>7}")

        # ---- ALC-meter
        self.alc_meter = QtWidgets.QProgressBar()
        self.alc_meter.setRange(0, 255)
        self.alc_meter.setFixedHeight(METERS_HEIGHT)
        # self.alc_meter.setFixedWidth(METERS_WIDTH)
        self.alc_meter.setFont(METERS_FONT)
        self.alc_meter.setValue(0)
        self.alc_meter.setFormat(f"ALC: {'-':>5}")

        # ---- PO-meter
        self.po_meter = QtWidgets.QProgressBar()
        self.po_meter.setRange(0, 255)
        self.po_meter.setFixedHeight(METERS_HEIGHT)
        # self.po_meter.setFixedWidth(METERS_WIDTH)
        self.po_meter.setFont(METERS_FONT)
        self.po_meter.setValue(0)
        self.po_meter.setFormat(f"PO: {'-':>6}")

        # ---- SWR-meter
        self.swr_meter = QtWidgets.QProgressBar()
        self.swr_meter.setRange(0, 255)
        self.swr_meter.setFixedHeight(METERS_HEIGHT)
        # self.swr_meter.setFixedWidth(METERS_WIDTH)
        self.swr_meter.setFont(METERS_FONT)
        self.swr_meter.setValue(0)
        self.swr_meter.setFormat(f"SWR: {'-':>5}")

        self.tx_meter_label = QtWidgets.QLabel("on TX:")
        self.cmb_smeter = QtWidgets.QComboBox()
        self.cmb_smeter.addItem('SWR')
        self.cmb_smeter.addItem('ALC')
        self.cmb_smeter.addItem('PWR')
        self.cmb_smeter.activated.connect(self.cmb_smeter_change)
        self.cmb_smeter.setFixedWidth(64)

        self.layout_tx_meter = QtWidgets.QHBoxLayout()
        self.layout_tx_meter.addWidget(self.tx_meter_label)
        self.layout_tx_meter.addWidget(self.cmb_smeter)

        # Filter width
        self.filter_width_group = QtWidgets.QGroupBox("Filter")
        filter_width_layout = QtWidgets.QVBoxLayout()

        # Radio buttons
        self.filter_narrow = QtWidgets.QRadioButton("NAR")
        self.filter_normal = QtWidgets.QRadioButton("NOR")
        self.filter_wide = QtWidgets.QRadioButton("WID")
        self.filter_normal.setChecked(True)

        filter_width_layout.addWidget(self.filter_narrow)
        filter_width_layout.addWidget(self.filter_normal)
        filter_width_layout.addWidget(self.filter_wide)

        self.filter_width_group.setLayout(filter_width_layout)

        self.group = QtWidgets.QButtonGroup(self)
        self.group.addButton(self.filter_narrow)
        self.group.addButton(self.filter_normal)
        self.group.addButton(self.filter_wide)

        self.group.buttonClicked.connect(self.filter_width_changed)

        # --- GroupBox: Antenna ---
        antenna_group = QtWidgets.QGroupBox("Antenna")

        # Układ pionowy wewnątrz ramki
        antenna_layout = QtWidgets.QVBoxLayout(antenna_group)

        # Radio buttons
        self.antenna_1 = QtWidgets.QRadioButton(ANTENNA_1_NAME)
        self.antenna_2 = QtWidgets.QRadioButton(ANTENNA_2_NAME)
        self.antenna_3 = QtWidgets.QRadioButton(ANTENNA_3_NAME)

        # Domyślne zaznaczenie
        self.antenna_1.setChecked(True)

        # Dodajemy przyciski do layoutu pionowego
        antenna_layout.addWidget(self.antenna_1)
        antenna_layout.addWidget(self.antenna_2)
        antenna_layout.addWidget(self.antenna_3)

        # Grupa przycisków (jednokrotny wybór)
        self.antenna_switch_group = QtWidgets.QButtonGroup(self)
        self.antenna_switch_group.addButton(self.antenna_1)
        self.antenna_switch_group.addButton(self.antenna_2)
        self.antenna_switch_group.addButton(self.antenna_3)

        # Po zmianie wyboru wywołaj funkcję
        self.antenna_switch_group.buttonClicked.connect(self.antenna_switch_changed)

        bottom_row = QtWidgets.QHBoxLayout()
        bottom_row.addStretch()
        bottom_row.addWidget(self.filter_width_group)
        bottom_row.addStretch()
        if ANTENNA_SWITCH_ENABLED:
            bottom_row.addWidget(antenna_group)
        bottom_row.addStretch()

        DSP_SLIDER_HEIGHT = 80  # lub dowolna wysokość w px, np. 60 / 100 / 120

        # --- Layout poziomy dla trzech pionowych suwaków
        dsp_layout = QtWidgets.QHBoxLayout()

        # --- Shift slider (pionowy)
        self.shift_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Vertical)
        self.shift_slider.setFixedHeight(DSP_SLIDER_HEIGHT)
        self.shift_slider.setMinimum(-1000)
        self.shift_slider.setMaximum(1000)
        self.shift_slider.setSingleStep(101)
        self.shift_slider.setPageStep(201)
        self.shift_slider.setTickInterval(200)
        self.shift_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.shift_slider.setValue(0)
        self.shift_slider.valueChanged.connect(self.shift_slider_move)

        shift_group = QtWidgets.QGroupBox("Shift")
        shift_layout = QtWidgets.QVBoxLayout(shift_group)
        shift_layout.addWidget(self.shift_slider)

        # --- Notch slider (pionowy)
        self.notch_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Vertical)
        self.notch_slider.setFixedHeight(DSP_SLIDER_HEIGHT)
        self.notch_slider.setMinimum(0)
        self.notch_slider.setMaximum(4000)
        self.notch_slider.setSingleStep(100)
        self.notch_slider.setPageStep(100)
        self.notch_slider.setTickInterval(400)
        self.notch_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.notch_slider.setValue(2000)
        self.notch_slider.valueChanged.connect(self.notch_slider_move)

        self.notch_group = QtWidgets.QGroupBox("Notch")
        self.notch_group.setCheckable(True)
        self.notch_group.setChecked(False)
        self.notch_group.clicked.connect(self.notch_checked)
        notch_layout = QtWidgets.QVBoxLayout(self.notch_group)
        notch_layout.addWidget(self.notch_slider)

        # --- Noise Reduction slider (pionowy)
        self.nr_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Vertical)
        self.nr_slider.setFixedHeight(DSP_SLIDER_HEIGHT)
        self.nr_slider.setMinimum(1)
        self.nr_slider.setMaximum(11)
        self.nr_slider.setSingleStep(1)
        self.nr_slider.setPageStep(1)
        self.nr_slider.setTickInterval(1)
        self.nr_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.nr_slider.setValue(DEFAULT_NOISE_REDUCTION)
        self.nr_slider.valueChanged.connect(self.nr_slider_move)

        self.nr_group = QtWidgets.QGroupBox("NR")
        self.nr_group.setCheckable(True)
        self.nr_group.setChecked(False)
        self.nr_group.clicked.connect(self.nr_checked)
        nr_layout = QtWidgets.QVBoxLayout(self.nr_group)
        nr_layout.addWidget(self.nr_slider)

        # --- dodaj wszystkie podgrupy do poziomego układu
        dsp_layout.addWidget(shift_group)
        dsp_layout.addWidget(self.notch_group)
        dsp_layout.addWidget(self.nr_group)

        # przycisk odtwarzania
        self.play1_btn = QtWidgets.QPushButton('▶️ ' + REC1_PATH.split('/')[-1].replace('.wav', '')[0:5])
        self.play1_btn.setFixedSize(SMALL_BTN_WIDTH, SMALL_BTN_HEIGHT)
        self.play1_btn.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
        self.play1_btn.pressed.connect(self.play1_btn_pressed)

        self.play2_btn = QtWidgets.QPushButton('▶️ ' + REC2_PATH.split('/')[-1].replace('.wav', '')[0:5])
        self.play2_btn.setFixedSize(SMALL_BTN_WIDTH, SMALL_BTN_HEIGHT)
        self.play2_btn.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
        self.play2_btn.pressed.connect(self.play2_btn_pressed)

        # --- groupbox for player
        self.player_group = QtWidgets.QGroupBox("Player")
        player_layout = QtWidgets.QVBoxLayout(self.player_group)
        player_layout.addWidget(self.play1_btn)
        player_layout.addWidget(self.play2_btn)

        self.waterfall_widget = WaterfallWidget(width=int(self.width()), height=int(self.height()))

        # --- dodanie do bottom_row_2
        bottom_row_2 = QtWidgets.QHBoxLayout()
        bottom_row_2.addLayout(dsp_layout)

        # top row
        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(left_widget)
        top_row.addWidget(freq_widget)
        top_row.addWidget(right_container)
        top_row.addLayout(knobs_row)
        top_row.addStretch()
        top_row.addWidget(self.group_freq_ctrl)
        top_row.addStretch()
        top_row.addLayout(btns_layout)
        top_row.addStretch()
        top_row.addWidget(self.ptt_btn)
        top_row.addStretch()
        top_row.addLayout(bottom_row)
        top_row.addLayout(bottom_row_2)
        if PLAYER_ACTIVE:
            top_row.addWidget(self.player_group)
        top_row.addStretch()

        self.smeter_row = QtWidgets.QHBoxLayout()
        self.smeter_row.addWidget(self.s_meter)
        self.smeter_row.addSpacing(20)
        self.smeter_row.addWidget(self.alc_meter)
        self.smeter_row.addSpacing(20)
        self.smeter_row.addLayout(self.layout_tx_meter)

        # --- sterowanie ---
        controls = QtWidgets.QHBoxLayout()

        controls.addWidget(QtWidgets.QLabel("Min[dB]:"))
        self.min_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.min_slider.setRange(-160, -10)
        self.min_slider.setPageStep = 1
        self.min_slider.setSingleStep = 1
        self.min_slider.setValue(int(self.waterfall_widget.min_db))
        self.min_slider.valueChanged.connect(self.on_min_changed)
        controls.addWidget(self.min_slider)
        self.min_label = QtWidgets.QLabel(f"{int(self.waterfall_widget.min_db)}")
        controls.addWidget(self.min_label)

        controls.addSpacing(20)

        controls.addWidget(QtWidgets.QLabel("Range[dB]:"))
        self.range_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.range_slider.setRange(0, 40)
        self.range_slider.setPageStep = 1
        self.range_slider.setSingleStep = 1
        self.range_slider.setValue(WATERFALL_DYNAMIC_RANGE)
        self.range_slider.valueChanged.connect(self.on_range_changed)
        controls.addWidget(self.range_slider)
        self.range_label = QtWidgets.QLabel(f"{WATERFALL_DYNAMIC_RANGE}")
        controls.addWidget(self.range_label)

        # ---- root layout
        self.root = QtWidgets.QVBoxLayout(central)
        self.root.addLayout(top_row)
        self.root.addLayout(self.smeter_row)
        self.root.addWidget(self.waterfall_widget)
        self.root.addLayout(controls)
        self.root.addStretch(0)

        self.status = self.statusBar()

        # Wątek odczytu
        self.thread = QtCore.QThread()
        self.worker = PollWorker(HOST, PORT, POLL_MS)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.start)
        self.worker.result.connect(self.parse_hamlib_response)
        self.worker.status.connect(self.status.showMessage)
        self.pause_polling.connect(self.worker.pause)
        self.resume_polling.connect(self.worker.resume)
        self.thread.start()

        # Obsługa wysyłania zmian do radia
        self.power_btn.clicked.connect(self.power_btn_clicked)
        self.tuner_status.singleClicked.connect(self.set_tuner)
        self.tuner_status.doubleClicked.connect(self.tuning_start)
        self.send_tx_signal.connect(self.tx_action)
        self.send_tx_signal.connect(self.worker.tx_action)
        self.send_fst_signal.connect(self.fst_action)
        self.tx_power_btn.clicked.connect(self.set_tx_power)
        self.sound_finished.connect(self._on_sound_finished)

        # Waterfall
        self.ws_thread = WsReceiver(WS_URL, fft_size=DEFAULT_FFT_SIZE)
        self.ws_thread.push_row_signal.connect(self.waterfall_widget.push_row)
        self.ws_thread.config_signal.connect(self.waterfall_widget.update_config)
        self.waterfall_widget.samp_rate = self.ws_thread.samp_rate
        self.waterfall_widget.center_freq = self.ws_thread.center_freq
        self.waterfall_widget.freq_clicked.connect(self.on_freq_clicked)
        self.waterfall_freq_update.connect(self.waterfall_widget.update_selected_freq)
        self.waterfall_freq_update.connect(self.ws_thread.send_set_frequency)
        self.ws_thread.start()

        self.client = RigctlClient(HOST, PORT, timeout=TCP_TIMEOUT)

    def parse_af_gain(self, val):
        if val is not None:
            if not self.knob_volume.user_active:
                val = float(val)
                vol = int(val/1 * 100)
                self.current_vol = vol
                self.knob_volume.set_value(vol)

    def parse_sql_lvl(self, val):
            if val is not None:
                if not self.knob_squelch.user_active:
                    val = float(val)
                    sql = int(val/1 * 100)
                    self.current_sql = sql
                    self.knob_squelch.set_value(sql)

    def parse_strength(self, val):
        """
        Surowy odczyt poziomu sygnału (0–255) → dB → 0..100% → etykieta S.
        Prosta interpolacja na podstawie FT450_STR_CAL.
        """

        # --- zabezpieczenie ---
        try:
            raw = float(val)
        except:
            raw = 0.0

        # --- kalibracja FT450 (raw → dB) ---
        # FT450_STR_CAL { {10,-60}, {125,0}, {240,60} }
        cal = [(10, -60), (125, 0), (240, 60)]

        # jeżeli poniżej pierwszego punktu
        if raw <= cal[0][0]:
            db = cal[0][1]

        # pomiędzy punktami
        elif raw <= cal[1][0]:
            # interpolacja 10 → 125  ;  -60 → 0
            r1, d1 = cal[0]
            r2, d2 = cal[1]
            frac = (raw - r1) / (r2 - r1)
            db = d1 + frac * (d2 - d1)

        elif raw <= cal[2][0]:
            # interpolacja 125 → 240 ;  0 → +60
            r1, d1 = cal[1]
            r2, d2 = cal[2]
            frac = (raw - r1) / (r2 - r1)
            db = d1 + frac * (d2 - d1)

        # powyżej 240
        else:
            db = cal[2][1]

        db = int(val)

        # --- procent do widgetu 0..100 ---
        # -60 dB → 0, +60 dB → 100
        pct = int((db + 60) / 120 * 100)
        pct = max(0, min(100, pct))



        # --- etykieta S ---
        # S9 = 0 dB
        # 6 dB = 1 S-unit
        if db < -54:      # poniżej S1
            label = "S0"
        elif db < 0:      # S1..S9
            s = int(9 + db / 6)
            s = max(0, min(9, s))
            label = f"S{s}"
        else:
            # nad S9 → +10, +20, +40...
            extra = int((db + 5) // 10 * 10)   # zaokrąglanie do 10 dB
            label = f"+{extra}"

        if not self.tx_active:
            self.s_meter.setRange(0, 100)
            self.s_meter.setValue(pct)
            self.s_meter.setFormat(f"S: {label:>5}")

        # (opcjonalnie) zwróć wartości do debug
        return {"raw": raw, "db": db, "pct": pct, "label": label}


    def parse_rf_power_meter(self, val):
        if val is not None:
            self.po_meter.setRange(0, 100)
            val = float(val)
            rf_power = int(val / 1 * 100)
            self.po_meter.setValue(rf_power)
            po_label = rf_power
            self.po_meter.setFormat(f"PO: {po_label:>6}")

    def parse_alc(self, val):
        if val is not None:
            self.alc_meter.setRange(0, 100)
            val = float(val)
            alc = int(val / 1 * 100)
            self.alc_meter.setValue(alc)
            alc_label = alc
            self.alc_meter.setFormat(f"ALC: {alc_label:>5}")

    def parse_swr(self, val):
        if val is not None:
            self.swr_meter.setRange(0, 100)
            val = float(val)
            swr = int((val-1) / 5 * 100) # TODO: change magic number (5 as max)
            
            self.swr_meter.setValue(swr)
            swr = f"{val:1.1f}"
            self.swr_meter.setFormat(f"SWR: {swr:>3}")

    def parse_powerstat(self, val):
        if val is not None:
            val = val.split('get_powerstat:\nPower Status: ')[1].split('\n')[0]
            val = int(val)
            self.client.trx_power_status = val
            if val:
                self.power_btn.setText("OFF")
                self.power_btn.setStyleSheet("border-radius: 14px; background-color: #fa6060; border: 1px solid black;")
            else:
                # TODO: all values can be zeroed
                self.power_btn.setText("ON")
                self.power_btn.setStyleSheet("border-radius: 14px; background-color: #60fa60; border: 1px solid black;")

    def parse_freq(self, val):
        pass

    def parse_rf_power(self, val):
        if val is not None:
            val = float(val)
            power = int(val / 1 * 100) # TODO: magic number
            self.tx_power_btn.setText(str(power) + "W")

    def parse_tuner(self, val):
        if val is not None:
            val = int(val)
            if val:
                self.tuner_status.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
                self.tuner_status_val = 1
            else:
                self.tuner_status.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
                self.tuner_status_val = 0

    def parse_tx(self, val):
        if val is not None:
            ptt = val.split('get_ptt:\nPTT: ')[1].split('\n')[0]
            val = int(ptt)
            if val:
                self.tx_active = 1
                self.centralWidget().setStyleSheet("background-color: red;")
                temp = self.windowTitle()
                if not "[TX]" in temp:
                    self.setWindowTitle("[TX] " + temp)
                self.replace_s_meter_when_tx(1)
            else:
                self.tx_active = 0
                self.setWindowTitle(self.windowTitle().replace('[TX] ', ''))
                self.centralWidget().setStyleSheet("")
                self.replace_s_meter_when_tx(0)
    
    def parse_preamp(self, val):
        if val is not None:
            if val == '10': # TODO: magic number
                self.ipo_btn.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
                self.ipo_val = 1
            else:
                self.ipo_btn.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
                self.ipo_val = 0

    def parse_vfo(self, val):
        if val is not None:
            vfo = val.split('get_vfo:\nVFO: ')[1].split('\n')[0]
            if vfo == 'VFOA':
                self.active_vfo = 0
            elif vfo == 'VFOB':
                self.active_vfo = 1

    def parse_nb(self, val):
        if val is not None:
            val = int(val)
            if val:
                self.nb_btn.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
                self.nb_active = 1
            else:
                self.nb_btn.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
                self.nb_active = 0

    def parse_mon(self, val):
        if val is not None:
            val = int(val)
            if val == 0:
                self.monitor_active = 0
                self.monitor_btn.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
            elif val == 1:
                self.monitor_active = 1
                self.monitor_btn.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")

    def parse_if(self, val):
        pass

    def parse_mn(self, val):
        pass

    def parse_notchf(self, val):
        pass

    def parse_u_nr(self, val):
        pass

    def parse_l_nr(self, val):
        pass

    def parse_att(self, val):
        if val is not None:
            val = int(val)
            if val:
                self.att_btn.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
                self.att_val = 1
            else:
                self.att_btn.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
                self.att_val = 0

    def parse_raw(self, val):
        param = val.split('send_cmd: ')[1].split(';')[0]
        param_value = val.split('Reply: ' + param)[1].split(';')[0]

        parser_name = self.find_parser_for_raw(param)
        if parser_name is None:
            print(f"No parser available for raw({param})")
            return

        # pobierz funkcję metody z self
        parser_fn = getattr(self, parser_name, None)
        if parser_fn is None:
            print(f"Parser function {parser_name} not found!")
            return

        # wywołaj dedykowany parser
        parser_fn(param_value)

    def find_parser_for_raw(self, param):
        for item in cyclicRefreshParams:
            if item['cmd'].startswith('w') and param in item['cmd'].split('w')[1]:
                return item['parser']
        return None
    
    def find_parser_for_get_level(self, param):
        for item in cyclicRefreshParams:
            if item['cmd'].startswith('l ') and item['cmd'].split(' ')[1] == param:
                return item['parser']
        return None
    
    def find_parser_for_get_func(self, param):
        for item in cyclicRefreshParams:
            if item['cmd'].startswith('u ') and item['cmd'].split(' ')[1] == param:
                return item['parser']
        return None

    def parse_get_level(self, val):
        param = val.split(': ')[1].split('\n')[0]
        param_value = val.split(param + '\n')[1].split('\n')[0]

        parser_name = self.find_parser_for_get_level(param)
        if parser_name is None:
            print(f"No parser available for get_level({param})")
            return

        # pobierz funkcję metody z self
        parser_fn = getattr(self, parser_name, None)
        if parser_fn is None:
            print(f"Parser function {parser_name} not found!")
            return

        # wywołaj dedykowany parser
        parser_fn(param_value)

    def parse_get_func(self, val):
        param = val.split(': ')[1].split('\n')[0]
        param_value = val.split(param + '\n')[1].split('\n')[0]

        parser_name = self.find_parser_for_get_func(param)
        if parser_name is None:
            print(f"No parser available for get_func({param})")
            return

        # pobierz funkcję metody z self
        parser_fn = getattr(self, parser_name, None)
        if parser_fn is None:
            print(f"Parser function {parser_name} not found!")
            return

        # wywołaj dedykowany parser
        # print(param + '=' + param_value)
        parser_fn(param_value)

    def parse_get_vfo_info(self, val):
        vfo = val.split('get_vfo_info: ')[1].split('\n')[0]
        freq = int(val.split('Freq: ')[1].split('\n')[0])

        # ??? Some Hamlib error
        if freq < 0:
            return

        mode = val.split('Mode: ')[1].split('\n')[0]
        width = int(val.split('Width: ')[1].split('\n')[0])
        split = val.split('Split: ')[1].split('\n')[0]
        satmode = val.split('SatMode: ')[1].split('\n')[0]

        self.mode = mode
        self.filter_width = width

        if vfo == 'VFOA':
            self.vfoa_freq = freq
        elif vfo == 'VFOB':
            self.vfob_freq = freq

        if self.active_vfo == 0:
            self.current_freq = self.vfoa_freq
            self.set_frequency_label(self.freq_display, self.vfoa_freq)
            self.waterfall_freq_update.emit(self.current_freq, self.filter_width, self.mode_label.text())
            self.active_vfo_label.setText("VFO A")
            self.set_frequency_label(self.freq_display_sub, self.vfob_freq)
        elif self.active_vfo == 1:
            self.current_freq = self.vfob_freq
            self.set_frequency_label(self.freq_display, self.vfob_freq)
            self.waterfall_freq_update.emit(self.current_freq, self.filter_width, self.mode_label.text())
            self.active_vfo_label.setText("VFO B")
            self.set_frequency_label(self.freq_display_sub, self.vfoa_freq)

    @QtCore.pyqtSlot(object)
    def parse_hamlib_response(self, val):

        # print(key)
        # print(val)

        if self.ignore_next_data_switch:
            if self.ignore_next_data_cnt:
                self.ignore_next_data_cnt = self.ignore_next_data_cnt - 1
                return
            else:
                self.ignore_next_data_switch = False

        for resp in val:
            if 'RPRT 0' in resp:
                if 'get_level' in resp:
                    self.parse_get_level(resp)
                elif 'get_func' in resp:
                    self.parse_get_func(resp)
                elif 'get_vfo_info' in resp:
                    self.parse_get_vfo_info(resp)
                elif 'get_vfo' in resp:
                    self.parse_vfo(resp)
                elif 'get_ptt' in resp:
                    self.parse_tx(resp)
                elif 'send_cmd' in resp:
                    self.parse_raw(resp)
                elif 'get_powerstat' in resp:
                    self.parse_powerstat(resp)
            else:
                print('Error in response: RPRT ' + resp.split('RPRT ')[0])

        return

        if self.ignore_next_data_switch:
            if self.ignore_next_data_cnt:
                # Do it only for one time
                if key == "SQ0":
                    self.ignore_next_data_cnt = self.ignore_next_data_cnt - 1
                # print('dupa')
                return
            else:
                self.ignore_next_data_switch = False

        if key == "SQ0":
            if val is not None:
                if not self.knob_squelch.user_active:
                    self.current_sql = val
                    self.knob_squelch.set_value(val)
        elif key == "AG0":
            if val is not None:
                if not self.knob_volume.user_active:
                    self.current_vol = val
                    self.knob_volume.set_value(val)
        elif key == "RM1":
            if val is not None:
                self.s_meter.setRange(0, 255)
                self.s_meter.setValue(val)
                s_label = self.s_meter_label(val)
                self.s_meter.setFormat(f"S: {s_label:>7}")
        elif key == "RM4":
            if val is not None:
                self.alc_meter.setRange(0, 255)
                self.alc_meter.setValue(val)
                alc_label = int(val / 255 * 100)
                self.alc_meter.setFormat(f"ALC: {alc_label:>5}")
        elif key == "RM5":
            if val is not None:
                self.po_meter.setRange(0, 255)
                self.po_meter.setValue(val)
                po_label = int(val / 255 * 100)
                self.po_meter.setFormat(f"PO: {po_label:>6}")
        elif key == "RM6":
            if val is not None:
                self.swr_meter.setRange(0, 255)
                self.swr_meter.setValue(val)
                swr_label = self.swr_label(val)
                self.swr_meter.setFormat(f"SWR: {swr_label:>5}")
        elif key == "FA":
            if val is not None:
                self.vfoa_freq = val
                if not self.active_vfo:
                    self.set_frequency_label(self.freq_display, val)
                    self.current_freq = self.vfoa_freq
                    self.waterfall_freq_update.emit(self.current_freq, self.filter_width, self.mode_label.text())
                    self.active_vfo_label.setText("VFO A")
                else:
                    self.set_frequency_label(self.freq_display_sub, val)
        elif key == "FB":
            if val is not None:
                self.vfob_freq = val
                if self.active_vfo:
                    self.set_frequency_label(self.freq_display, val)
                    self.current_freq = self.vfob_freq
                    self.waterfall_freq_update.emit(self.current_freq, self.filter_width, self.mode_label.text())
                    self.active_vfo_label.setText("VFO B")
                else:
                    self.set_frequency_label(self.freq_display_sub, val)
        elif key == "PC":
            if val is not None:
                self.tx_power_btn.setText(str(val) + "W")
        elif key == "VS":
            if val is not None:
                self.active_vfo = val
        elif key == "RA0":
            if val is not None:
                if val:
                    self.att_btn.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
                    self.att_val = 1
                else:
                    self.att_btn.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
                    self.att_val = 0
        elif key == "PA0":
            if val is not None:
                if val:
                    self.ipo_btn.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
                    self.ipo_val = 1
                else:
                    self.ipo_btn.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
                    self.ipo_val = 0
        elif key == "AC":
            if val is not None:
                if val:
                    self.tuner_status.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
                    self.tuner_status_val = 1
                else:
                    self.tuner_status.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
                    self.tuner_status_val = 0
        elif key == "TX":
            if val is not None:
                if val:
                    self.tx_active = 1
                    self.centralWidget().setStyleSheet("background-color: red;")
                    temp = self.windowTitle()
                    if not "[TX]" in temp:
                        self.setWindowTitle("[TX] " + temp)
                    self.replace_s_meter_when_tx(1)
                else:
                    self.tx_active = 0
                    self.setWindowTitle(self.windowTitle().replace('[TX] ', ''))
                    self.centralWidget().setStyleSheet("")
                    self.replace_s_meter_when_tx(0)
        elif key == "NB0":
            if val is not None:
                if val:
                    self.nb_btn.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
                    self.nb_active = 1
                else:
                    self.nb_btn.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
                    self.nb_active = 0
        elif key == "PS":
            if val is not None:
                self.client.trx_power_status = val
                if val:
                    self.power_btn.setText("OFF")
                    self.power_btn.setStyleSheet("border-radius: 14px; background-color: #fa6060; border: 1px solid black;")
                else:
                    # TODO: all values can be zeroed
                    self.power_btn.setText("ON")
                    self.power_btn.setStyleSheet("border-radius: 14px; background-color: #60fa60; border: 1px solid black;")
        elif key == "MD0":
            if val is not None:
                self.mode_label.setText(radioModesRx[val])
        elif key == "ML0":
            if val is not None:
                if val == 0:
                    self.monitor_active = 0
                    self.monitor_btn.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
                elif val == 1:
                    self.monitor_active = 1
                    self.monitor_btn.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
        elif key == "SH0":
            if val is not None:
                if val <= 10:
                    self.filter_width = globals()['FILTER_WIDTH_' + self.mode_label.text() + '_NARROW']

                    self.filter_narrow.setChecked(True)
                elif val > 10 and val <= 21:
                    self.filter_width = globals()['FILTER_WIDTH_' + self.mode_label.text() + '_NORMAL']

                    self.filter_normal.setChecked(True)
                elif val > 21 and val <= 31:
                    self.filter_width = globals()['FILTER_WIDTH_' + self.mode_label.text() + '_WIDE']

                    self.filter_wide.setChecked(True)
        elif key == "IS0":
            if val is not None:
                # self.shift_slider.setValue(val)
                pass

        elif key == "BP00":
            if val is not None:
                if val:
                    self.notch_group.setChecked(True)
                else:
                    self.notch_group.setChecked(False)

    def on_min_changed(self, val):
        self.waterfall_widget.set_min_db(val)
        self.waterfall_widget.set_max_db(val + self.range_slider.value())
        self.min_label.setText(f"{val}")

    def on_range_changed(self, val):
        WATERFALL_DYNAMIC_RANGE = val
        self.waterfall_widget.set_min_db(self.waterfall_widget.min_db)
        self.waterfall_widget.set_max_db(self.waterfall_widget.min_db + val)
        self.range_label.setText(f"{val}")

    def on_freq_clicked(self, freq: int):
        freq = int(freq - freq%100)
        self.frequency_change(freq)

        try:
            if hasattr(self, "ws_thread") and self.ws_thread is not None:
                self.ws_thread.send_set_frequency(freq)
        except Exception as e:
            print("Failed to request setfrequency:", e)

    def ignore_next_data(self, cnt=2):
        self.ignore_next_data_switch = True
        self.ignore_next_data_cnt = cnt

    def shift_slider_move(self, value):
        center = 0
        tolerance = 200  # zakres "magnesu"
        if abs(value - center) <= tolerance:
            self.shift_slider.setValue(center)

        cmd = f"L IF " + str(value)
        self.client.send(cmd)
        self.worker.reset_one_time.emit("l IF")

    def notch_slider_move(self, value):
        cmd = f"L NOTCHF " + str(value)
        self.client.send(cmd)
        self.worker.reset_one_time.emit("l NOTCHF")

    def notch_checked(self, value):
        if value:
            cmd = f"U MN 1"
        else:
            cmd = f"U MN 0"
        self.ignore_next_data()
        self.client.send(cmd)
        self.worker.reset_one_time.emit("u MN")

    def nr_slider_move(self, value):
        cmd = f"L NR " + str(value / 10)
        self.client.send(cmd)

    def nr_checked(self, value):
        if value:
            cmd = f"U NR 1"
            self.client.send(cmd)
            cmd = f"L NR " + str(self.nr_slider.value() / 10)
        else:
            cmd = f"U NR 0"
        self.ignore_next_data()
        self.client.send(cmd)
        self.worker.reset_one_time.emit("u NR")

    def set_frequency_label(self, label, freq):
        try:
            mhz = float(freq) / 1_000_000.0
        except Exception:
            label.setText("??.?????MHz")
            return

        int_part = int(mhz)
        frac_part = abs(mhz - int_part)

        frac_str = f"{frac_part:.5f}"
        frac_str = frac_str[1:]

        int_str = str(int_part).zfill(2)

        label.setText(f"{int_str}{frac_str}MHz")


    def s_meter_label(self, val: int) -> str:
        """
        Mapowanie wartości RM0 (0–255) na skalę S-metra.
        Używa tabeli kalibracyjnej z interpolacją liniową.
        """
        # tabela: surowa_wartość : etykieta
        cal_table = [
            (0, "S0"),
            (20, "S1"),
            (40, "S3"),
            (53, "S4"),
            (75, "S5"),
            (88, "S6"),
            (110, "S7"),
            (155, "S9"),
            (165, "+10"),
            (190, "+20"),
            (220, "+40"),
            (255, "+60"),
        ]

        # jeśli dokładne trafienie
        for raw, label in cal_table:
            if val == raw:
                return label

        # interpolacja: znajdź przedział
        for i in range(len(cal_table)-1):
            raw1, lab1 = cal_table[i]
            raw2, lab2 = cal_table[i+1]
            if raw1 <= val <= raw2:
                return lab1  # dla uproszczenia zwracamy niższy próg
                # można też dorobić interpolację np. "S6"
        return "S?"

    def swr_label(self, val: int) -> str:
        """
        Mapowanie wartości 0–255 na SWR.
        Zakładamy: 
        0   -> 1.0
        127 -> 3.0
        255 -> ~99.9 (praktycznie ∞)
        """
        if val < 0:
            val = 0
        if val > 255:
            val = 255

        if val <= 127:
            # interpolacja 0–127 -> SWR 1.0–3.0
            swr = 1.0 + (val / 127.0) * (3.0 - 1.0)
        else:
            # interpolacja 127–255 -> SWR 3.0–99.9
            swr = 3.0 + ((val - 127) / 128.0) * (99.9 - 3.0)

        return f"{swr:.1f}"

    def power_btn_clicked(self):
        if self.client.trx_power_status:
            cmd = f"\\set_powerstat 0"
        else:
            cmd = f"\\set_powerstat 1"
            self.pause_polling.emit(1000)
        self.client.send(cmd)

    def att_btn_clicked(self):
        if self.att_val:
            cmd = f"L ATT 0"
        else:
            cmd = f"L ATT 20"
        self.client.send(cmd)
        self.worker.reset_one_time.emit("l ATT")

    def ipo_btn_clicked(self):
        if not self.ipo_val:
            cmd = f"L PREAMP 10"
        else:
            cmd = f"L PREAMP 0"
        self.client.send(cmd)
        self.worker.reset_one_time.emit("l PREAMP")

    def ipo_att_btn_clicked(self):
        if self.att_val:
            cmd = f"wRA00;"
        else:
            cmd = f"wRA01;"
        self.client.send(cmd)

    def band_down_btn_clicked(self):
        cmd = f"G BAND_DOWN"
        self.client.send(cmd)
        self.waterfall_widget.initial_zoom_set = False
        self.ignore_next_data()

    def band_up_btn_clicked(self):
        cmd = f"G BAND_UP"
        self.client.send(cmd)
        self.ignore_next_data()
        self.waterfall_widget.initial_zoom_set = False

    def a_eq_b_btn_clicked(self):
        cmd = f"G CPY"
        self.client.send(cmd)

    def vfo_switch_btn_clicked(self):
        cmd = f"G XCHG"
        self.client.send(cmd)
        self.waterfall_widget.initial_zoom_set = False

    def nb_btn_clicked(self):
        if self.nb_active:
            cmd = f"U NB 0"
        else:
            cmd = f"U NB 1"
        self.client.send(cmd)
        self.worker.reset_one_time.emit("u NB")

    def monitor_btn_clicked(self):
        if self.monitor_active:
            cmd = f"U MON 0"
        else:
            cmd = f"U MON 1"
        self.client.send(cmd)
        self.worker.reset_one_time.emit("u MON")

    def split_btn_clicked(self):
        if not self.split_active:
            cmd = f"S 1 VFOB"
            self.split_active = 1
            self.split_btn.setStyleSheet("border-radius: 14px; background-color: lightgreen; border: 1px solid black;")
        else:
            cmd = f"S 0 VFOA"
            self.split_active = 0
            self.split_btn.setStyleSheet("border-radius: 14px; background-color: lightgray; border: 1px solid black;")
        self.client.send(cmd)

    def mode_down_btn_clicked(self):
        current_mode = findIndexOfString(self.mode_label.text(), radioModesRx)

        if current_mode <= 1:
            new_mode = len(radioModesTx) - 1
        else:
            new_mode = current_mode - 1

        cmd = f"M " + radioModesTx[new_mode] + " 0"
        self.client.send(cmd)

    def mode_up_btn_clicked(self):
        current_mode = findIndexOfString(self.mode_label.text(), radioModesRx)

        if current_mode >= len(radioModesTx):
            new_mode = 1
        else:
            new_mode = current_mode + 1

        cmd = f"M " + radioModesTx[new_mode] + " 0"
        self.client.send(cmd)

    def frequency_step(self, sign, step):
        if sign > 0:
            self.current_freq -= self.current_freq%step
            self.current_freq += step
        elif sign < 0:
            if self.current_freq%step:
                self.current_freq -= self.current_freq%step
            else:
                self.current_freq -= step
        self.frequency_change(self.current_freq)

    def freq_step(self, new_pos: int):
        delta = new_pos - self.last_freq_pos
        self.last_freq_pos = new_pos

        if delta > 5:   # wrap forward
            delta -= 100
        elif delta < -5:  # wrap backward
            delta += 100

        if delta >= 0:
            self.frequency_step(1, FREQ_STEP_SLOW)
        else:
            self.frequency_step(-1, FREQ_STEP_SLOW)
    
    def fast_freq_step(self, new_pos: int):
        delta = new_pos - self.last_fast_freq_pos
        self.last_fast_freq_pos = new_pos

        if delta > 5:   # wrap forward
            delta -= 100
        elif delta < -5:  # wrap backward
            delta += 100

        if delta >= 0:
            self.frequency_step(1, FREQ_STEP_FAST)
        else:
            self.frequency_step(-1, FREQ_STEP_FAST)

    def frequency_change(self, freq):
        cmd = f"F {freq}\n"
        self.set_frequency_label(self.freq_display, freq)
        self.waterfall_freq_update.emit(freq, self.filter_width, self.mode_label.text())
        self.ignore_next_data()
        self.client.send(cmd)

    def volume_change(self, new_pos: int):
        delta = new_pos - self.last_volume_pos
        if delta > 50:   # wrap forward
            delta -= 100
        elif delta < -50:  # wrap backward
            delta += 100
        self.last_volume_pos = new_pos
        if delta >= 0:
            delta = 1
        else:
            delta = -1

        if delta != 0:
            if not self.knob_volume.user_active:
                self.current_vol += delta * 1   # krok 1
            else:
                self.current_vol = self.knob_volume.dial.value()
            # print(self.current_vol)
            cmd = f"L AF {self.current_vol/100:0.3f}"
            # print(cmd)
            self.client.send(cmd)

    def squelch_change(self, new_pos: int):
        delta = new_pos - self.last_squelch_pos
        if delta > 50:   # wrap forward
            delta -= 100
        elif delta < -50:  # wrap backward
            delta += 100
        self.last_squelch_pos = new_pos
        if delta >= 0:
            delta = 1
        else:
            delta = -1

        if delta != 0:
            if not self.knob_squelch.user_active:
                self.current_sql += delta * 1   # krok 1
                # print('not user active')
            else:
                self.current_sql = self.knob_squelch.dial.value()
            cmd = f"L SQL {self.current_sql/100:0.3f}"
            self.client.send(cmd)

    def set_tuner(self):
        if self.tuner_status_val:
            cmd = f"U TUNER 0"
        else:
            cmd = f"U TUNER 1"
        # print(cmd)
        self.client.send(cmd)
        self.worker.reset_one_time.emit("u TUNER")

    def tuning_start(self):
        # cmd = f"wAC002;"
        cmd = f"U TUNER 2"
        # print(cmd)
        self.client.send(cmd)
        # self.worker.pause(1000)

    def disable_tx(self):
        cmd = f"T 0"
        self.client.send(cmd)

    def replace_s_meter_when_tx(self, tx_state):
        if self.tx_meter is SWR_METER:
            new_meter = self.swr_meter
        elif self.tx_meter is ALC_METER:
            new_meter = self.alc_meter
        elif self.tx_meter is PO_METER:
            new_meter = self.po_meter
        else:
            new_meter = self.swr_meter

        if tx_state:
            self.smeter_row.replaceWidget(self.s_meter, new_meter)
            self.s_meter.hide()
            new_meter.show()
        else:
            self.smeter_row.replaceWidget(new_meter, self.s_meter)
            self.s_meter.show()
            new_meter.hide()

    @QtCore.pyqtSlot(int)
    def tx_action(self, val: int):
        temp = self.windowTitle()

        if val:
            cmd = f"T 1"
            self.client.send(cmd)
            self.setWindowTitle("[TX] " + temp)
            self.centralWidget().setStyleSheet("background-color: orange;")
            self.worker.poll_all()
            self.tx_sent = 1
        else:
            self.setWindowTitle(self.windowTitle().replace('[TX] ', ''))
            # Send disable tx with delay because of delay in mumble
            QTimer.singleShot(TX_OFF_DELAY, self.disable_tx)
            self.disable_tx()
            self.tx_sent = 0

    @QtCore.pyqtSlot(int)
    def fst_action(self, val: int):
        # print('elo')
        if val:
            self.swr_btn_pressed()
        else:
            self.swr_btn_released()

    def filter_width_changed(self):
        if self.filter_narrow.isChecked():
            self.filter_width = globals()['FILTER_WIDTH_' + self.mode_label.text() + '_NARROW']
            # self.filter_width = FILTER_WIDTH_SSB_NARROW
        elif self.filter_normal.isChecked():
            self.filter_width = globals()['FILTER_WIDTH_' + self.mode_label.text() + '_NORMAL']
            # self.filter_width = FILTER_WIDTH_SSB_NORMAL
        elif self.filter_wide.isChecked():
            self.filter_width = globals()['FILTER_WIDTH_' + self.mode_label.text() + '_WIDE']
            # self.filter_width = FILTER_WIDTH_SSB_WIDE

        cmd = f"M " + self.mode_label.text() + " " + str(self.filter_width)
        self.ignore_next_data()
        self.client.send(cmd)

    def antenna_switch_changed(self):
        if not self.tx_active:
            if self.antenna_1.isChecked():
                self.switch_antenna('1')
            elif self.antenna_2.isChecked():
                self.switch_antenna('2')
            elif self.antenna_3.isChecked():
                self.switch_antenna('3')
        else:
            print("Cannot change antenna when TX")

    def set_tx_power(self):
        dialog = SliderDialog(self, value=int(self.tx_power_btn.text().replace('W', '')))
        if dialog.exec_():
            value = dialog.get_value()
            cmd = f"L RFPOWER {value/100:0.2f}"
            self.client.send(cmd)

    def cmb_smeter_change(self):
        if self.cmb_smeter.currentText() == 'ALC':
            self.tx_meter = ALC_METER
        elif self.cmb_smeter.currentText() == 'SWR':
            self.tx_meter = SWR_METER
        elif self.cmb_smeter.currentText() == 'PWR':
            self.tx_meter = PO_METER

    def ptt_btn_pressed(self):
        self.send_tx_signal.emit(1)
        self.ptt_btn.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border-radius: 20px; border: 1px solid black;")

    def ptt_btn_released(self):
        self.send_tx_signal.emit(0)
        self.ptt_btn.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 20px; border: 1px solid black;")

    def swr_btn_pressed(self):
        self.current_power = self.tx_power_btn.text().replace('W', '')
        self.current_mode = self.mode_label.text()
        cmd = f"M CW 0"
        self.client.send(cmd)

        cmd = f"L RFPOWER {10/100:0.2f}"
        self.client.send(cmd)
        
        self.send_tx_signal.emit(1)
        self.swr_btn.setStyleSheet("background-color: " + BUTTON_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")

    def swr_btn_released(self):
        if "SWR" in self.swr_meter.text():
            self.current_swr = float(self.swr_meter.text().replace("SWR", " ").replace(" ", "").replace(":", ""))
        else:
            self.current_swr = float(10)

        # self.swr_btn.setText(f"SWR: {self.current_swr:1.1f}")

        self.send_tx_signal.emit(0)
        self.swr_btn.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")

        QTimer.singleShot(TX_OFF_DELAY + 20, self.stop_swr_check)

    def stop_swr_check(self):
        cmd = f"M " + self.current_mode + " 0"
        self.client.send(cmd)

        cmd = f"L RFPOWER {int(self.current_power)/100:0.2f}"
        self.client.send(cmd)

    def play_sound(self, path, widget):
        if self.tx_active or self.tx_sent:
            self.send_tx_signal.emit(0)
            cmd = f"U MON 0"
            self.client.send(cmd)
            stopSound()
            widget.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
        else:
            cmd = f"U MON 1"
            self.client.send(cmd)
            self.send_tx_signal.emit(1)
            widget.setStyleSheet("background-color: " + BUTTON_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
        
            # callback wykona się po zakończeniu odtwarzania
            def on_finished():
                self.sound_finished.emit(widget)

            playSound(path, on_finished=on_finished)

    def _on_sound_finished(self, widget):
        self.send_tx_signal.emit(0)
        widget.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
        QTimer.singleShot(TX_OFF_DELAY + 20, self.disable_monitor)

    def disable_monitor(self):
        cmd = f"U MON 0"
        self.client.send(cmd)

    def play1_btn_pressed(self):
        self.play_sound(REC1_PATH, self.play1_btn)

    def play2_btn_pressed(self):
        self.play_sound(REC2_PATH, self.play2_btn)

    def closeEvent(self, event):
        self.thread.quit()
        self.thread.wait(1000)
        super().closeEvent(event)

    def switch_antenna(self, cmd, host=HOST, port=ANTENNA_SWITCH_PORT):
        """Wysyła komendę '1' lub '2' do serwera."""
        try:
            with socket.create_connection((host, port), timeout=1) as s:
                s.sendall(cmd.encode("ascii", errors="ignore"))
                response = s.recv(1024).decode('utf-8').strip()
                print("Server response:", response)
                self.status.showMessage(response)
        except Exception as e:
            print("Connection error:", e)

def start_keyboard_listener(main_window):
    pressed_keys = set()
    tx_pressed = False
    fst_pressed = False

    def on_press(key):
        nonlocal tx_pressed, fst_pressed

        try:
            key_name = key.char.lower() if hasattr(key, 'char') and key.char else key.name
            pressed_keys.add(key_name)
            # print("Pressed:", pressed_keys)

            # TX (np. Alt)
            if PTT_KEY in pressed_keys and not tx_pressed:
                tx_pressed = True
                main_window.send_tx_signal.emit(1)

            # FST combo (np. Shift + Q)
            if FST_KEY_MOD in pressed_keys and FST_KEY in pressed_keys and not fst_pressed:
                fst_pressed = True
                main_window.send_fst_signal.emit(1)

        except AttributeError:
            pass

    def on_release(key):
        nonlocal tx_pressed, fst_pressed

        try:
            key_name = key.char.lower() if hasattr(key, 'char') and key.char else key.name
            if key_name in pressed_keys:
                pressed_keys.remove(key_name)

            # TX release
            if PTT_KEY == key_name and tx_pressed:
                tx_pressed = False
                main_window.send_tx_signal.emit(0)

            # FST combo release
            if fst_pressed and (FST_KEY_MOD not in pressed_keys or FST_KEY not in pressed_keys):
                fst_pressed = False
                main_window.send_fst_signal.emit(0)

        except AttributeError:
            pass

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    listener.join()

def main():
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    thread = threading.Thread(target=start_keyboard_listener, args=(w,), daemon=True)
    thread.start()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
