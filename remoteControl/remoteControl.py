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
dir_path = os.path.dirname(os.path.realpath(__file__))

from waterfallWindow import WaterfallWindow

# U MON 1 <- Monitor

HOST = "192.168.152.12"
# HOST = "192.168.152.2"
PORT = 4532
DUMMY_PORT = 4534
ANTENNA_SWITCH_PORT = 5000
ANTENNA_1_NAME = 'Hexbeam'
ANTENNA_1_CMD = '1'
ANTENNA_2_NAME = 'Dipole'
ANTENNA_2_CMD = '2'
TCP_TIMEOUT = 0.1
POLL_MS = 500
SLOWER_POLL_MS = 2000
MAX_RETRY_CNT = 3
FREQ_STEP_SLOW = 100
FREQ_STEP_FAST = 2500
TX_OFF_DELAY = 300
PTT_KEY = 'ctrl_r'
FST_KEY_MOD = 'shift'
FST_KEY = 'w'

BUTTON_COLOR = "#FFDF85"
NOT_ACTIVE_COLOR = "lightgray"
ACTIVE_COLOR = "lightgreen"

REC1_PATH = dir_path + '/recs/sp9pho_en.wav'
REC2_PATH = dir_path + '/recs/cq_sp9pho.wav'

SWR_METER = 1
ALC_METER = 2
PO_METER  = 3
DEFAULT_TX_METER = SWR_METER

RADIO_WIDTH_NARROW = 1800
RADIO_WIDTH_NORMAL = 2400
RADIO_WIDTH_WIDE   = 3000

cyclicRefreshParams = ['AG0', 'SQ0', 'RM0', 'RM1', 'RM4', 'RM5', 'RM6', 'PS', 'FA', 'FB', 'PC', 'AC', 'TX', 'RA0', 'PA0', 'VS', 'NB0', 'MD0', 'ML0', 'SH0', 'IS0', 'BP00']

radioModesRx = ['', 'LSB', 'USB', 'CW', 'FM', 'AM', 'DATA-L', 'CW-R', 'USER-L', 'DATA-U']
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
                # print(cmd)
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
        self.dial.setRange(0, 255)
        self.dial.setNotchesVisible(True)
        self.dial.setWrapping(False)
        self.dial.setFixedSize(size, size)   # <<< używamy parametru size
        self.dial.setSingleStep(1)
        self.dial.setPageStep(1)

        self.dial.sliderPressed.connect(self._on_pressed)
        self.dial.sliderReleased.connect(self._on_released)

        self.value_label = QtWidgets.QLabel("—")
        self.value_label.setAlignment(QtCore.Qt.AlignCenter)
        self.value_label.setFont(QtGui.QFont("Monospace", 10))

        self.title_label = QtWidgets.QLabel(self.title)
        self.title_label.setAlignment(QtCore.Qt.AlignCenter)
        self.title_label.setStyleSheet("letter-spacing: 1px; font-weight: 600;")

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.dial, alignment=QtCore.Qt.AlignCenter)
        if value_label_visible:
            layout.addWidget(self.value_label)
        layout.addWidget(self.title_label)

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
    result = QtCore.pyqtSignal(str, object)  # key, value
    status = QtCore.pyqtSignal(str)

    def __init__(self, host: str, port: int, poll_ms: int = POLL_MS):
        super().__init__()
        self.client = RigctlClient(host, port, timeout=TCP_TIMEOUT)
        self.poll_ms = poll_ms
        self._timer = None
        self.retry_cnt = 0

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

    def poll_all(self):
        if not self.client.connected:
            try:
                self.client = RigctlClient(HOST, PORT, timeout=TCP_TIMEOUT)
            except:
                pass
            return
        # resp = self.client.send("wAG0;SQ0;SM0;")
        cmd = "w"
        for req in cyclicRefreshParams:
            cmd += req + ';'
        # print(cmd)
        resp = self.client.send(cmd)

        if not resp:
            self.status.emit(f"No answer from {HOST}:{PORT}")
            if self.retry_cnt > MAX_RETRY_CNT:
                self._timer.setInterval(SLOWER_POLL_MS)
            else:
                self.retry_cnt += 1
            return
        elif "-" in resp and not 'IS0' in resp:
            # print("-20")
            if self.retry_cnt > MAX_RETRY_CNT:
                self._timer.setInterval(9999999)
                self.status.emit(f"Polling stopped")
            else:
                self.retry_cnt += 1
        else:
            self.retry_cnt = 0
            if self._timer.interval() != self.poll_ms:
                self._timer.setInterval(self.poll_ms)  # wróć do normalnego

        resps = resp.replace('\x00', '').replace('\n', '').split(";")
        # print(resps)
        ok_any = False

        # Parsing response
        if len(resps) > 2:
            for req in cyclicRefreshParams: 
                try:
                    val = int(next((s for s in resps if req in s), None).replace(req, ''))
                    # print(req + ' = ' + str(val))
                    self.result.emit(req, val)
                    ok_any = True
                except:
                    pass
        else:
            self.status.emit(f"No answer from {HOST}:{PORT}")
            self.result.emit("PS", 0)
            return

        if ok_any:
            self.status.emit(f"Connected with {HOST}:{PORT}")
            pass

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

class MainWindow(QtWidgets.QMainWindow):
    send_tx_signal = QtCore.pyqtSignal(int)
    send_fst_signal = QtCore.pyqtSignal(int)
    pause_polling = QtCore.pyqtSignal(int)
    resume_polling = QtCore.pyqtSignal()
    sound_finished = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Remote Control - FT‑450D")
        self.windowWidth = 600
        self.windowHeight = 550
        self.setFixedSize(self.windowWidth, self.windowHeight) 
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
        self.setWindowIcon(QIcon("logo.ico"))

        self.ignore_next_data_switch = False
        self.ignore_next_data_cnt = 2

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        self.tx_active = 0
        self.tx_sent = 0
        self.tx_meter = DEFAULT_TX_METER

        self.radio_width = RADIO_WIDTH_NORMAL

        # ---- top: power indicator + freq display
        self.power_indicator = QtWidgets.QLabel()
        self.power_indicator.setFixedSize(28, 28)
        self.power_indicator.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; border: 1px solid black; border-radius: 14px;")
        self.power_indicator.setToolTip("Radio OFF")

        self.active_vfo_label = QtWidgets.QLabel()
        self.active_vfo_label.setFixedSize(64, 28)
        self.active_vfo_label.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border: 1px solid black; border-radius: 4px;")
        self.active_vfo_label.setAlignment(QtCore.Qt.AlignCenter)
        self.active_vfo_label.setFont(QtGui.QFont("Monospace", 10, QtGui.QFont.Bold))
        self.active_vfo_label.setText("VFO A")
        self.active_vfo = 0

        # mode
        self.mode_label = QtWidgets.QLabel()
        self.mode_label.setFixedSize(64, 28)
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
        self.att_btn.setFixedSize(64, 28)
        self.att_btn.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px;")
        self.att_btn.setText("ATT")
        self.att_btn.clicked.connect(self.att_btn_clicked)

        self.ipo_btn = QtWidgets.QPushButton()
        self.ipo_btn.setFixedSize(64, 28)
        self.ipo_btn.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px;")
        self.ipo_btn.setText("IPO")
        self.ipo_btn.clicked.connect(self.ipo_btn_clicked)

        self.tx_power_btn = QtWidgets.QPushButton()
        self.tx_power_btn.setFixedSize(64, 28)
        self.tx_power_btn.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
        self.tx_power_btn.setText("-W")

        # główna częstotliwość
        self.freq_display = QtWidgets.QLabel("--- MHz")
        self.freq_display.setFont(QtGui.QFont("Monospace", 16, QtGui.QFont.Bold))
        self.freq_display.setAlignment(QtCore.Qt.AlignCenter)

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
        right_grid.setSpacing(4)
        right_grid.setContentsMargins(0, 0, 0, 0)
        right_container.setLayout(right_grid)

        # pierwsza (istniejąca) linia przycisków
        right_grid.addWidget(self.att_btn,       0, 0)
        right_grid.addWidget(self.ipo_btn,       0, 1)
        right_grid.addWidget(self.tx_power_btn,  0, 3)

        # druga linia — na razie tylko NB pod pierwszym przyciskiem
        self.nb_btn = QtWidgets.QPushButton("NB")
        self.nb_btn.setFixedSize(64, 28)
        self.nb_btn.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
        self.nb_btn.clicked.connect(self.nb_btn_clicked)
        self.nb_active = 0

        self.tuner_status = DoubleClickButton()
        self.tuner_status.setFixedSize(64, 28)
        self.tuner_status.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px;")
        self.tuner_status.setText("TUNER")
        self.tuner_status_val = 0

        self.monitor_btn = QtWidgets.QPushButton("NB")
        self.monitor_btn.setFixedSize(64, 28)
        self.monitor_btn.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
        self.monitor_btn.setText("MONITOR")
        self.monitor_btn.clicked.connect(self.monitor_btn_clicked)
        self.monitor_active = 0

        right_grid.addWidget(self.nb_btn, 1, 0)
        right_grid.addWidget(self.tuner_status, 1, 1)
        right_grid.addWidget(self.monitor_btn, 1, 3)

        # Add waterfall button to your existing button layout
        self.waterfall_btn = QtWidgets.QPushButton("Waterfall")
        self.waterfall_btn.setFixedSize(64, 28)
        self.waterfall_btn.setStyleSheet("background-color: lightblue; text-align: center; border-radius: 4px; border: 1px solid black;")
        self.waterfall_btn.clicked.connect(self.show_waterfall)

        # Add to your right_grid layout (adjust position as needed)
        # right_grid.addWidget(self.waterfall_btn, 1, 5)  # Adjust row/column as needed

        # Initialize waterfall window
        self.waterfall_window = None

        # wstawienie do top_row: freq_widget zachowuje stretch, prawy kontener jest "przyklejony" z prawej
        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(self.power_indicator)
        top_row.addSpacing(2)
        top_row.addWidget(left_widget)
        top_row.addSpacing(1)
        top_row.addWidget(freq_widget, stretch=1)   # zajmuje środek
        top_row.addSpacing(6)
        top_row.addWidget(right_container)

        # ---- middle: knobs (FREQ big, then SQUELCH + VOLUME)
        self.knob_fast_freq = BigKnob("Fast", size=80, value_label_visible=False)
        self.knob_fast_freq.dial.setWrapping(True)
        self.knob_fast_freq.dial.setNotchesVisible(False)  # bo to ma być ciągłe
        self.knob_fast_freq.dial.setRange(0, 10)          # 0–100 kroków w kółko
        self.knob_fast_freq.dial.valueChanged.connect(self.fast_freq_step)
        self.last_fast_freq_pos = 0

        self.knob_freq = BigKnob("Dial", size=80, value_label_visible=False)
        self.knob_freq.dial.setWrapping(True)
        self.knob_freq.dial.setNotchesVisible(False)  # bo to ma być ciągłe
        self.knob_freq.dial.setRange(0, 10)          # 0–100 kroków w kółko
        self.knob_freq.dial.valueChanged.connect(self.freq_step)
        self.last_freq_pos = 0
        self.current_freq = 14074000  # Hz (odczyt z rigctld)

        self.knob_squelch = BigKnob("Squelch", size=60)
        self.knob_squelch.dial.setNotchTarget(20.0)
        self.knob_squelch.dial.valueChanged.connect(self.squelch_change)
        self.last_squelch_pos = 0
        
        self.knob_volume = BigKnob("Volume", size=60)
        self.knob_volume.dial.setNotchTarget(20.0)
        self.knob_volume.dial.valueChanged.connect(self.volume_change)
        self.last_volume_pos = 0

        knobs_row = QtWidgets.QHBoxLayout()
        knobs_row.addWidget(self.knob_fast_freq, stretch=1)
        knobs_row.addWidget(self.knob_freq, stretch=1)
        knobs_row.addWidget(self.knob_squelch, stretch=1, alignment=QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom)
        knobs_row.addWidget(self.knob_volume, stretch=1, alignment=QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom)

        # ---- bottom buttons: teraz w 2 rzędach
        btns_layout = QtWidgets.QVBoxLayout()
        btns_layout.setSpacing(6)
        self.buttons = []

        # pierwszy rząd
        btn_row1 = QtWidgets.QHBoxLayout()
        btn_row1.setSpacing(48)

        self.power_btn = QtWidgets.QPushButton("PWR")
        self.power_btn.setFixedSize(48, 48) 
        self.power_btn.setStyleSheet("border-radius: 24px; background-color: lightgray; border: 1px solid black;")
        self.power_btn.setText("ON")
        self.power_indicator.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; border-radius: 14px; border: 1px solid black;")
        self.power_indicator.setToolTip("Radio OFF")
        btn_row1.addWidget(self.power_btn)
        self.buttons.append(self.power_btn)

        self.band_down_btn = QtWidgets.QPushButton("BAND\n↓")
        self.band_down_btn.setFixedSize(48, 48)
        self.band_down_btn.setStyleSheet("border-radius: 24px; background-color: lightgray; border: 1px solid black;")
        btn_row1.addWidget(self.band_down_btn)
        self.buttons.append(self.band_down_btn)
        self.band_down_btn.clicked.connect(self.band_down_btn_clicked)

        self.band_up_btn = QtWidgets.QPushButton("BAND\n↑")
        self.band_up_btn.setFixedSize(48, 48)
        self.band_up_btn.setStyleSheet("border-radius: 24px; background-color: lightgray; border: 1px solid black;")
        btn_row1.addWidget(self.band_up_btn)
        self.buttons.append(self.band_up_btn)
        self.band_up_btn.clicked.connect(self.band_up_btn_clicked)

        self.a_eq_b_btn = QtWidgets.QPushButton("A = B")
        self.a_eq_b_btn.setFixedSize(48, 48)
        self.a_eq_b_btn.setStyleSheet("border-radius: 24px; background-color: lightgray; border: 1px solid black;")
        btn_row1.addWidget(self.a_eq_b_btn)
        self.buttons.append(self.a_eq_b_btn)
        self.a_eq_b_btn.clicked.connect(self.a_eq_b_btn_clicked)

        self.vfo_switch_btn = QtWidgets.QPushButton("A / B")
        self.vfo_switch_btn.setFixedSize(48, 48)
        self.vfo_switch_btn.setStyleSheet("border-radius: 24px; background-color: lightgray; border: 1px solid black;")
        btn_row1.addWidget(self.vfo_switch_btn)
        self.buttons.append(self.vfo_switch_btn)
        self.vfo_switch_btn.clicked.connect(self.vfo_switch_btn_clicked)

        btns_layout.addLayout(btn_row1)
        btns_layout.addSpacing(1)

        # drugi rząd
        btn_row2 = QtWidgets.QHBoxLayout()
        btn_row2.setSpacing(1)

        self.ipo_att_btn = QtWidgets.QPushButton("IPO\n/ATT")
        self.ipo_att_btn.setFixedSize(48, 48)
        self.ipo_att_btn.setStyleSheet("border-radius: 24px; background-color: lightgray; border: 1px solid black;")
        btn_row2.addWidget(self.ipo_att_btn)
        self.buttons.append(self.ipo_att_btn)
        self.ipo_att_btn.clicked.connect(self.ipo_att_btn_clicked)

        self.split_btn = QtWidgets.QPushButton("SPLIT")
        self.split_btn.setFixedSize(48, 48)
        self.split_btn.setStyleSheet("border-radius: 24px; background-color: lightgray; border: 1px solid black;")
        btn_row2.addWidget(self.split_btn)
        self.buttons.append(self.split_btn)
        self.split_btn.clicked.connect(self.split_btn_clicked)
        self.split_active = 0

        # MODE ↓
        self.mode_down_btn = QtWidgets.QPushButton("MODE\n↓")
        self.mode_down_btn.setFixedSize(48, 48)
        self.mode_down_btn.setStyleSheet("border-radius: 24px; background-color: lightgray; border: 1px solid black;")
        btn_row2.addWidget(self.mode_down_btn)
        self.buttons.append(self.mode_down_btn)
        self.mode_down_btn.clicked.connect(self.mode_down_btn_clicked)

        # MODE ↑
        self.mode_up_btn = QtWidgets.QPushButton("MODE\n↑")
        self.mode_up_btn.setFixedSize(48, 48)
        self.mode_up_btn.setStyleSheet("border-radius: 24px; background-color: lightgray; border: 1px solid black;")
        btn_row2.addWidget(self.mode_up_btn)
        self.buttons.append(self.mode_up_btn)
        self.mode_up_btn.clicked.connect(self.mode_up_btn_clicked)

        btns_layout.addLayout(btn_row2)

        METERS_FONT_SIZE = 9
        METERS_FONT = QtGui.QFont("Courier New", METERS_FONT_SIZE, QtGui.QFont.Bold)
        METERS_HEIGHT = 16
        METERS_SPACING = 4
        METERS_WIDTH = self.windowWidth - 30

        # ---- S-meter
        self.s_meter = QtWidgets.QProgressBar()
        self.s_meter.setRange(0, 255)
        self.s_meter.setFixedHeight(METERS_HEIGHT)
        self.s_meter.setFixedWidth(METERS_WIDTH)
        self.s_meter.setFont(METERS_FONT)
        self.s_meter.setValue(0)
        self.s_meter.setFormat(f"S: {'-':>7}")

        # ---- ALC-meter
        self.alc_meter = QtWidgets.QProgressBar()
        self.alc_meter.setRange(0, 255)
        self.alc_meter.setFixedHeight(METERS_HEIGHT)
        self.alc_meter.setFixedWidth(METERS_WIDTH)
        self.alc_meter.setFont(METERS_FONT)
        self.alc_meter.setValue(0)
        self.alc_meter.setFormat(f"ALC: {'-':>5}")

        # ---- PO-meter
        self.po_meter = QtWidgets.QProgressBar()
        self.po_meter.setRange(0, 255)
        self.po_meter.setFixedHeight(METERS_HEIGHT)
        self.po_meter.setFixedWidth(METERS_WIDTH)
        self.po_meter.setFont(METERS_FONT)
        self.po_meter.setValue(0)
        self.po_meter.setFormat(f"PO: {'-':>6}")

        # ---- SWR-meter
        self.swr_meter = QtWidgets.QProgressBar()
        self.swr_meter.setRange(0, 255)
        self.swr_meter.setFixedHeight(METERS_HEIGHT)
        self.swr_meter.setFixedWidth(METERS_WIDTH)
        self.swr_meter.setFont(METERS_FONT)
        self.swr_meter.setValue(0)
        self.swr_meter.setFormat(f"SWR: {'-':>5}")

        self.tx_meter_label = QtWidgets.QLabel("TX meter:")
        self.cmb_smeter = QtWidgets.QComboBox()
        self.cmb_smeter.addItem('SWR')
        self.cmb_smeter.addItem('ALC')
        self.cmb_smeter.addItem('PWR')
        self.cmb_smeter.activated.connect(self.cmb_smeter_change)
        self.cmb_smeter.setFixedWidth(64)

        self.swr_btn = QtWidgets.QPushButton("Check SWR")
        self.swr_btn.setFixedSize(78, 28)
        self.swr_btn.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
        self.swr_btn.pressed.connect(self.swr_btn_pressed)
        self.swr_btn.released.connect(self.swr_btn_released)

        # Layout poziomy
        radio_width = QtWidgets.QHBoxLayout()

        # Radio buttons
        self.radio_width_label = QtWidgets.QLabel("")
        self.radio_narrow = QtWidgets.QRadioButton("NAR")
        self.radio_normal = QtWidgets.QRadioButton("NOR")
        self.radio_wide = QtWidgets.QRadioButton("WID")

        # Domyślne zaznaczenie (opcjonalnie)
        self.radio_normal.setChecked(True)

        # Dodajemy do layoutu
        radio_width.addWidget(self.radio_narrow)
        radio_width.addWidget(self.radio_normal)
        radio_width.addWidget(self.radio_wide)

        # Grupa przycisków (jednokrotny wybór)
        self.group = QtWidgets.QButtonGroup(self)
        self.group.addButton(self.radio_narrow)
        self.group.addButton(self.radio_normal)
        self.group.addButton(self.radio_wide)

        # Po zmianie wyboru wywołaj funkcję
        self.group.buttonClicked.connect(self.radio_width_changed)

        # Layout poziomy
        antenna_switch = QtWidgets.QHBoxLayout()

        # Radio buttons
        self.antenna_switch_label = QtWidgets.QLabel("")
        self.antenna_1 = QtWidgets.QRadioButton(ANTENNA_1_NAME)
        self.antenna_2 = QtWidgets.QRadioButton(ANTENNA_2_NAME)

        # Domyślne zaznaczenie (opcjonalnie)
        self.antenna_1.setChecked(True)

        # Dodajemy do layoutu
        antenna_switch.addWidget(self.antenna_1)
        antenna_switch.addWidget(self.antenna_2)

        # Grupa przycisków (jednokrotny wybór)
        self.antenna_switch_group = QtWidgets.QButtonGroup(self)
        self.antenna_switch_group.addButton(self.antenna_1)
        self.antenna_switch_group.addButton(self.antenna_2)

        # Po zmianie wyboru wywołaj funkcję
        self.antenna_switch_group.buttonClicked.connect(self.antenna_switch_changed)

        bottom_row = QtWidgets.QHBoxLayout()
        # bottom_row.addStretch()
        bottom_row.addWidget(self.swr_btn)
        bottom_row.addSpacing(12)
        bottom_row.addWidget(self.radio_width_label)
        bottom_row.addLayout(radio_width)
        bottom_row.addSpacing(12)
        bottom_row.addLayout(antenna_switch)
        bottom_row.addStretch()
        bottom_row.addWidget(self.tx_meter_label)
        bottom_row.addWidget(self.cmb_smeter)

        # --- slider
        self.shift_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.shift_slider.setFixedWidth(100)
        self.shift_slider.setMinimum(-1000)
        self.shift_slider.setMaximum(1000)
        self.shift_slider.setSingleStep(101)
        self.shift_slider.setPageStep(101)
        self.shift_slider.setTickInterval(250)
        self.shift_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.shift_slider.setValue(0)

        # "sticky point" w środku
        self.shift_slider.valueChanged.connect(self.shift_slider_move)

        # --- groupbox dla slidera
        shift_group = QtWidgets.QGroupBox("Shift")
        shift_group.setFixedWidth(self.shift_slider.width() + 24)
        shift_layout = QtWidgets.QHBoxLayout(shift_group)
        shift_layout.addWidget(self.shift_slider)
        # shift_layout.addStretch()

        # --- slider
        self.notch_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.notch_slider.setFixedWidth(150)
        self.notch_slider.setMinimum(0)
        self.notch_slider.setMaximum(4000)
        self.notch_slider.setSingleStep(200)
        self.notch_slider.setPageStep(200)
        self.notch_slider.setTickInterval(250)
        self.notch_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.notch_slider.setValue(2000)
        self.notch_slider.valueChanged.connect(self.notch_slider_move)

        # --- groupbox dla slidera
        self.notch_group = QtWidgets.QGroupBox("Notch")
        self.notch_group.setCheckable(True)
        self.notch_group.setChecked(False)
        self.notch_group.setFixedWidth(self.notch_slider.width() + 24)
        self.notch_group.clicked.connect(self.notch_checked)
        notch_layout = QtWidgets.QHBoxLayout(self.notch_group)
        notch_layout.addWidget(self.notch_slider)

        # przycisk odtwarzania
        self.play1_btn = QtWidgets.QPushButton('▶️ ' + REC1_PATH.split('/')[-1].replace('.wav', ''))
        self.play1_btn.setFixedSize(78, 28)
        self.play1_btn.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
        self.play1_btn.pressed.connect(self.play1_btn_pressed)

        self.play2_btn = QtWidgets.QPushButton('▶️ ' + REC2_PATH.split('/')[-1].replace('.wav', ''))
        self.play2_btn.setFixedSize(78, 28)
        self.play2_btn.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
        self.play2_btn.pressed.connect(self.play2_btn_pressed)

        # --- groupbox for player
        self.player_group = QtWidgets.QGroupBox("Player")
        player_layout = QtWidgets.QHBoxLayout(self.player_group)
        player_layout.addWidget(self.play1_btn)
        player_layout.addWidget(self.play2_btn)

        # --- dodanie do bottom_row_2
        bottom_row_2 = QtWidgets.QHBoxLayout()
        bottom_row_2.addWidget(shift_group)
        bottom_row_2.addWidget(self.notch_group)
        bottom_row_2.addWidget(self.player_group)
        bottom_row_2.addStretch()

        # ---- root layout
        self.root = QtWidgets.QVBoxLayout(central)
        self.root.addLayout(top_row)
        self.root.addLayout(knobs_row)
        self.root.addSpacing(8)
        self.root.addLayout(btns_layout)
        self.root.addSpacing(16)
        self.root.addWidget(self.s_meter)
        self.root.addSpacing(8)
        self.root.addLayout(bottom_row)
        self.root.addSpacing(8)
        self.root.addLayout(bottom_row_2)
        # self.root.addWidget(self.swr_btn)
        # root.addSpacing(METERS_SPACING)
        # root.addWidget(self.alc_meter)
        # root.addSpacing(METERS_SPACING)
        # root.addWidget(self.po_meter)
        # root.addSpacing(METERS_SPACING)
        # root.addWidget(self.swr_meter)
        self.root.addStretch(0)

        self.status = self.statusBar()

        # Wątek odczytu
        self.thread = QtCore.QThread()
        self.worker = PollWorker(HOST, PORT, POLL_MS)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.start)
        self.worker.result.connect(self.update_value)
        self.worker.status.connect(self.status.showMessage)
        self.pause_polling.connect(self.worker.pause)
        self.resume_polling.connect(self.worker.resume)
        self.thread.start()

        # Obsługa wysyłania zmian do radia
        self.power_btn.clicked.connect(self.power_btn_clicked)
        self.tuner_status.singleClicked.connect(self.set_tuner)
        self.tuner_status.doubleClicked.connect(self.tuning_start)
        self.send_tx_signal.connect(self.tx_action)
        self.send_fst_signal.connect(self.fst_action)
        self.tx_power_btn.clicked.connect(self.set_tx_power)
        self.sound_finished.connect(self._on_sound_finished)

        self.client = RigctlClient(HOST, PORT, timeout=TCP_TIMEOUT)

    @QtCore.pyqtSlot(str, object)
    def update_value(self, key, val):
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
                    self.active_vfo_label.setText("VFO A")
                else:
                    self.set_frequency_label(self.freq_display_sub, val)
        elif key == "FB":
            if val is not None:
                self.vfob_freq = val
                if self.active_vfo:
                    self.set_frequency_label(self.freq_display, val)
                    self.current_freq = self.vfob_freq
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
                    self.power_btn.setStyleSheet("border-radius: 24px; background-color: #fa6060; border: 1px solid black;")
                    self.power_indicator.setStyleSheet("background-color: " + ACTIVE_COLOR + "; border-radius: 14px; border: 1px solid black;")
                    self.power_indicator.setToolTip("Radio ON")
                else:
                    # TODO: all values can be zeroed
                    self.power_btn.setText("ON")
                    self.power_btn.setStyleSheet("border-radius: 24px; background-color: #60fa60; border: 1px solid black;")
                    self.power_indicator.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; border-radius: 14px; border: 1px solid black;")
                    self.power_indicator.setToolTip("Radio OFF")
                    # self.worker.pause(SLOWER_POLL_MS)
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
                    self.radio_width = RADIO_WIDTH_NARROW
                    self.radio_narrow.setChecked(True)
                elif val > 10 and val <= 21:
                    self.radio_width = RADIO_WIDTH_NORMAL
                    self.radio_normal.setChecked(True)
                elif val > 21 and val <= 31:
                    self.radio_width = RADIO_WIDTH_WIDE
                    self.radio_wide.setChecked(True)
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

    def notch_slider_move(self, value):
        cmd = f"L NOTCHF " + str(value)
        self.client.send(cmd)

    def notch_checked(self, value):
        if value:
            cmd = f"U MN 1"
        else:
            cmd = f"U MN 0"
        self.ignore_next_data()
        self.client.send(cmd)

    def show_waterfall(self):
        """Show waterfall window"""
        if self.waterfall_window is None:
            self.waterfall_window = WaterfallWindow(self)
        
        self.waterfall_window.show()
        self.waterfall_window.raise_()

    def set_frequency_label(self, label, freq):
        # label.setText(str(float(freq/1000000)).ljust(8, '0').zfill(8) + " MHz")
        label.setText(f"{freq/1000000:02.5f}MHz")

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
            self.pause_polling.emit(3000)
        self.client.send(cmd)

    def att_btn_clicked(self):
        if self.att_val:
            cmd = f"wRA00;"
        else:
            cmd = f"wRA01;"
        self.client.send(cmd)

    def ipo_btn_clicked(self):
        if not self.ipo_val:
            cmd = f"L PREAMP 10"
        else:
            cmd = f"L PREAMP 0"
        self.client.send(cmd)

    def ipo_att_btn_clicked(self):
        if self.att_val:
            cmd = f"wRA00;"
        else:
            cmd = f"wRA01;"
        self.client.send(cmd)

    def band_down_btn_clicked(self):
        cmd = f"G BAND_DOWN"
        self.client.send(cmd)

    def band_up_btn_clicked(self):
        cmd = f"G BAND_UP"
        self.client.send(cmd)

    def a_eq_b_btn_clicked(self):
        cmd = f"G CPY"
        self.client.send(cmd)

    def vfo_switch_btn_clicked(self):
        cmd = f"G XCHG"
        self.client.send(cmd)

    def nb_btn_clicked(self):
        if self.nb_active:
            cmd = f"U NB 0"
        else:
            cmd = f"U NB 1"
        self.client.send(cmd)

    def monitor_btn_clicked(self):
        if self.monitor_active:
            cmd = f"U MON 0"
        else:
            cmd = f"U MON 1"
        self.client.send(cmd)

    def split_btn_clicked(self):
        if not self.split_active:
            cmd = f"S 1 VFOB"
            self.split_active = 1
            self.split_btn.setStyleSheet("border-radius: 24px; background-color: lightgreen; border: 1px solid black;")
        else:
            cmd = f"S 0 VFOA"
            self.split_active = 0
            self.split_btn.setStyleSheet("border-radius: 24px; background-color: lightgray; border: 1px solid black;")
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

    def freq_step(self, new_pos: int):
        delta = new_pos - self.last_freq_pos
        self.last_freq_pos = new_pos

        if delta > 5:   # wrap forward
            delta -= 100
        elif delta < -5:  # wrap backward
            delta += 100

        if delta >= 0:
            delta = 1
            self.current_freq -= self.current_freq%FREQ_STEP_SLOW
            self.current_freq += delta * FREQ_STEP_SLOW
        else:
            delta = -1
            # print(self.current_freq%FREQ_STEP_SLOW)
            if self.current_freq%FREQ_STEP_SLOW:
                self.current_freq -= self.current_freq%FREQ_STEP_SLOW
            else:
                self.current_freq += delta * FREQ_STEP_SLOW

        cmd = f"F {self.current_freq}\n"
        self.set_frequency_label(self.freq_display, self.current_freq)
        self.ignore_next_data()
        self.client.send(cmd)
    
    def fast_freq_step(self, new_pos: int):
        delta = new_pos - self.last_fast_freq_pos
        self.last_fast_freq_pos = new_pos

        if delta > 5:   # wrap forward
            delta -= 100
        elif delta < -5:  # wrap backward
            delta += 100

        if delta >= 0:
            delta = 1
            self.current_freq -= self.current_freq%FREQ_STEP_FAST
            self.current_freq += delta * FREQ_STEP_FAST
        else:
            delta = -1
            # print(self.current_freq%FREQ_STEP_FAST)
            if self.current_freq%FREQ_STEP_FAST:
                self.current_freq -= self.current_freq%FREQ_STEP_FAST
            else:
                self.current_freq += delta * FREQ_STEP_FAST

        cmd = f"F {self.current_freq}\n"
        self.set_frequency_label(self.freq_display, self.current_freq)
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
            cmd = f"L AF {self.current_vol/255:0.3f}"
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
            cmd = f"L SQL {self.current_sql/255:0.3f}"
            self.client.send(cmd)

    def set_tuner(self):
        if self.tuner_status_val:
            cmd = f"U TUNER 0"
        else:
            cmd = f"U TUNER 1"
        # print(cmd)
        self.client.send(cmd)

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
            self.root.replaceWidget(self.s_meter, new_meter)
            self.s_meter.hide()
            new_meter.show()
        else:
            self.root.replaceWidget(new_meter, self.s_meter)
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
            self.tx_sent = 0

    @QtCore.pyqtSlot(int)
    def fst_action(self, val: int):
        # print('elo')
        if val:
            self.swr_btn_pressed()
        else:
            self.swr_btn_released()

    def radio_width_changed(self):
        if self.radio_narrow.isChecked():
            self.radio_width = RADIO_WIDTH_NARROW
        elif self.radio_normal.isChecked():
            self.radio_width = RADIO_WIDTH_NORMAL
        elif self.radio_wide.isChecked():
            self.radio_width = RADIO_WIDTH_WIDE

        cmd = f"M " + self.mode_label.text() + " " + str(self.radio_width)
        self.ignore_next_data()
        self.client.send(cmd)

    def antenna_switch_changed(self):
        if not self.tx_active:
            if self.antenna_1.isChecked():
                self.switch_antenna('1')
            elif self.antenna_2.isChecked():
                self.switch_antenna('2')
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
