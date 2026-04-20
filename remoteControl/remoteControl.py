#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import socket
import re
import threading
import asyncio
import os 
import numpy as np
import websocket
import json

from soundPlayer import playSound, stopSound
from audioClient import run as audioClientRun
from pynput import keyboard
from PyQt5.QtCore import QTimer
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtGui import QIcon

dir_path = os.path.dirname(os.path.realpath(__file__))

### --- Configuration Class --- ###
class Config:
    """Class managing application configuration"""
    
    BASE_CONFIG_FILE = 'config.json'
    
    def __init__(self, config_file='config.json'):
        # If config_file is a full path, use it directly
        if os.path.isabs(config_file):
            self.config_file = config_file
        else:
            # Otherwise use dir_path
            self.config_file = os.path.join(dir_path, config_file)
        self.defaults = self._get_defaults()
        self.settings = self.defaults.copy()
        self.load()
    
    def _get_defaults(self):
        """Returns default settings"""
        return {
            # Connection
            'host': "192.168.152.12",
            'port': 4532,
            'poll_ms': 500,
            
            # Radio Settings
            'freq_step_slow': 100,
            'freq_step_fast': 2500,
            'mouse_wheel_freq_step': 100,
            'mouse_wheel_fast_freq_step': 1000,
            'tx_off_delay': 100,
            'default_noise_reduction': 5,
            
            # Keyboard
            'ptt_key': 'ctrl_r',
            
            # Antenna Switch
            'antenna_switch_enabled': True,
            'antenna_switch_port': 5000,
            'antenna_1_name': 'Hex',
            'antenna_2_name': 'Dpl',
            'antenna_3_name': 'End',
            
            # Waterfall
            'waterfall_enabled': True,
            'waterfall_initial_zoom': 0.25,
            'waterfall_dynamic_range': 25,
            'waterfall_min_db_default': -90,
            
            # DX Cluster
            'dx_cluster_enabled': False,
            'dx_cluster_callsign': 'N0CALL',
            'dx_cluster_server': 'dxc.ve7cc.net',
            'dx_cluster_port': 23,
            'dx_cluster_backup_servers': 'dxfun.com:8000,dx.k3lr.com:7300,dxc.ai9t.com:7300,w3lpl.net:7373',
            
            # Filter Widths
            'filter_width_usb_narrow': 1800,
            'filter_width_usb_normal': 2400,
            'filter_width_usb_wide': 3000,
            'filter_width_lsb_narrow': 1800,
            'filter_width_lsb_normal': 2400,
            'filter_width_lsb_wide': 3000,
            'filter_width_am_narrow': 3000,
            'filter_width_am_normal': 6000,
            'filter_width_am_wide': 9000,
            'filter_width_fm_narrow': 2500,
            'filter_width_fm_normal': 5000,
            'filter_width_fm_wide': 5000,
            'filter_width_cw_narrow': 300,
            'filter_width_cw_normal': 500,
            'filter_width_cw_wide': 2400,
            'filter_width_cwr_narrow': 300,
            'filter_width_cwr_normal': 500,
            'filter_width_cwr_wide': 2400,
            
            # Interface
            'stay_on_top': False,

            # Audio
            'audio_input_device': None,
            'audio_output_device': None,
        }
    
    def load(self):
        """Loads configuration from JSON file"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    # Strip meta key - not a setting
                    loaded.pop('active_config', None)
                    # Merges loaded settings with defaults
                    self.settings.update(loaded)
                print(f"Configuration loaded from {self.config_file}")
            else:
                print(f"Config file not found, using defaults")
                self.save()  # Save default configuration
        except Exception as e:
            print(f"Error loading config: {e}, using defaults")
            self.settings = self.defaults.copy()
    
    def save(self):
        """Saves configuration to JSON file"""
        try:
            data_to_save = self.settings.copy()
            base_config_path = os.path.join(dir_path, self.BASE_CONFIG_FILE)
            # If saving to base config.json, preserve the active_config meta field
            if os.path.normcase(self.config_file) == os.path.normcase(base_config_path):
                try:
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        existing = json.load(f)
                    if 'active_config' in existing:
                        data_to_save['active_config'] = existing['active_config']
                except Exception:
                    pass
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, indent=4, ensure_ascii=False)
            print(f"Configuration saved to {self.config_file}")
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False
    
    def get(self, key, default=None):
        """Gets setting value"""
        return self.settings.get(key, default)
    
    def set(self, key, value):
        """Sets setting value"""
        self.settings[key] = value
    
    def reset_to_defaults(self):
        """Resets settings to default values"""
        self.settings = self.defaults.copy()
    
    def save_active_config_name(self):
        """Saves active config file path into base config.json"""
        try:
            base_config_path = os.path.join(dir_path, self.BASE_CONFIG_FILE)
            base_data = {}
            if os.path.exists(base_config_path):
                try:
                    with open(base_config_path, 'r', encoding='utf-8') as f:
                        base_data = json.load(f)
                except Exception:
                    pass
            if os.path.normcase(self.config_file) == os.path.normcase(base_config_path):
                # Active config IS config.json - remove the key (no need to store it)
                base_data.pop('active_config', None)
            else:
                base_data['active_config'] = self.config_file
            with open(base_config_path, 'w', encoding='utf-8') as f:
                json.dump(base_data, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving active config name: {e}")
            return False
    
    @staticmethod
    def get_active_config_name():
        """Reads active config file name from base config.json"""
        try:
            base_config_path = os.path.join(dir_path, Config.BASE_CONFIG_FILE)
            if os.path.exists(base_config_path):
                with open(base_config_path, 'r', encoding='utf-8') as f:
                    base_data = json.load(f)
                    active = base_data.get('active_config')
                    if active and os.path.exists(active):
                        return active
        except Exception as e:
            print(f"Error reading active config name: {e}")
        # If reading failed, return default file
        return os.path.join(dir_path, Config.BASE_CONFIG_FILE)

# Global configuration instance
active_config_file = Config.get_active_config_name()
config = Config(active_config_file)

### --- Configuration (Legacy - for backward compatibility) --- ###
# Connection
HOST = config.get('host')
PORT = config.get('port')
TCP_TIMEOUT = 0.1
POLL_MS = config.get('poll_ms')
SLOWER_POLL_MS = 2000
MAX_RETRY_CNT = 3

# Functional
PLAYER_ACTIVE = False
FREQ_STEP_SLOW = config.get('freq_step_slow')
FREQ_STEP_FAST = config.get('freq_step_fast')
TX_OFF_DELAY = config.get('tx_off_delay')
PTT_KEY = config.get('ptt_key')
FST_KEY_MOD = 'shift'
FST_KEY = 'w'

# Graphics
WINDOW_WIDTH_PERCENTAGE  = 80
WINDOW_HEIGHT_PERCENTAGE = 35
BUTTON_COLOR = "#FFDF85"
NOT_ACTIVE_COLOR = "lightgray"
ACTIVE_COLOR = "lightgreen"

ACTIVE_STYLE = "background-color: #4CAF50; color: white; border-radius: 4px; padding-left: 2px; padding-right: 2px;"
INACTIVE_STYLE = "background-color: #333; color: #CCC; border-radius: 4px; padding-left: 2px; padding-right: 2px;"

ROUND_BUTTON_SIZE = 40

SMALL_BTN_WIDTH  = 56
SMALL_BTN_HEIGHT = 28

NORMAL_BTN_WIDTH  = 76
NORMAL_BTN_HEIGHT = 28

BIG_KNOB_SIZE   = 50
SMALL_KNOB_SIZE = 40
KNOB_FONT_SIZE  = 10

DSP_SLIDER_HEIGHT = 80

ACTIVE_VFO_FONT = QtGui.QFont("Monospace", 12, QtGui.QFont.Bold)
SECOND_VFO_FONT = QtGui.QFont("Monospace", 10)

# Radio width
FILTER_WIDTH_USB_NARROW = config.get('filter_width_usb_narrow')
FILTER_WIDTH_USB_NORMAL = config.get('filter_width_usb_normal')
FILTER_WIDTH_USB_WIDE   = config.get('filter_width_usb_wide')

FILTER_WIDTH_LSB_NARROW = config.get('filter_width_lsb_narrow')
FILTER_WIDTH_LSB_NORMAL = config.get('filter_width_lsb_normal')
FILTER_WIDTH_LSB_WIDE   = config.get('filter_width_lsb_wide')

FILTER_WIDTH_AM_NARROW  = config.get('filter_width_am_narrow')
FILTER_WIDTH_AM_NORMAL  = config.get('filter_width_am_normal')
FILTER_WIDTH_AM_WIDE    = config.get('filter_width_am_wide')

FILTER_WIDTH_FM_NARROW  = config.get('filter_width_fm_narrow')
FILTER_WIDTH_FM_NORMAL  = config.get('filter_width_fm_normal')
FILTER_WIDTH_FM_WIDE    = config.get('filter_width_fm_wide')

FILTER_WIDTH_CW_NARROW  = config.get('filter_width_cw_narrow')
FILTER_WIDTH_CW_NORMAL  = config.get('filter_width_cw_normal')
FILTER_WIDTH_CW_WIDE    = config.get('filter_width_cw_wide')

FILTER_WIDTH_CWR_NARROW  = config.get('filter_width_cwr_narrow')
FILTER_WIDTH_CWR_NORMAL  = config.get('filter_width_cwr_normal')
FILTER_WIDTH_CWR_WIDE    = config.get('filter_width_cwr_wide')

# Misc
SWR_METER = 1
ALC_METER = 2
PO_METER  = 3
DEFAULT_TX_METER = SWR_METER

DEFAULT_NOISE_REDUCTION = config.get('default_noise_reduction')

REC1_PATH = dir_path + '/recs/sp9pho_en.wav'
REC2_PATH = dir_path + '/recs/cq_sp9pho.wav'

EQ_OPTIONS = [
    "Flat",
    "_-- Lo - | Mid 0 | Hi 0",
    "-_- Lo 0 | Mid - | Hi 0",
    "--_ Lo 0 | Mid 0 | Hi -",
    "--^ Lo 0 | Mid 0 | Hi +",
    "-^- Lo 0 | Mid + | Hi 0",
    "^-- Lo + | Mid 0 | Hi 0",
    "^-_ Lo + | Mid 0 | Hi -",
    "_^- Lo - | Mid + | Hi 0",
    "_-^ Lo - | Mid 0 | Hi +",
]

# Antenna switch
ANTENNA_SWITCH_ENABLED = config.get('antenna_switch_enabled')
ANTENNA_SWITCH_PORT = config.get('antenna_switch_port')
ANTENNA_1_NAME = config.get('antenna_1_name')
ANTENNA_1_CMD = '1'
ANTENNA_2_NAME = config.get('antenna_2_name')
ANTENNA_2_CMD = '2'
ANTENNA_3_NAME = config.get('antenna_3_name')
ANTENNA_3_CMD = '3'
GET_ANTENNA_CMD = 'get'

# Waterfall
WATERFALL_ENABLED = config.get('waterfall_enabled')
WS_URL = "ws://" + HOST + ":8073/ws/"
DEFAULT_FFT_SIZE = 2048

INITIAL_ZOOM = config.get('waterfall_initial_zoom')
WATERFALL_MIN_DB_DEFAULT = config.get('waterfall_min_db_default')
WATERFALL_DYNAMIC_RANGE = config.get('waterfall_dynamic_range')

MOUSE_WHEEL_FREQ_STEP = config.get('mouse_wheel_freq_step')
MOUSE_WHEEL_FAST_FREQ_STEP = config.get('mouse_wheel_fast_freq_step')

# DX Cluster
DX_CLUSTER_ENABLED = config.get('dx_cluster_enabled')
DX_CLUSTER_CALLSIGN = config.get('dx_cluster_callsign')
DX_CLUSTER_SERVER = config.get('dx_cluster_server')
DX_CLUSTER_PORT = config.get('dx_cluster_port')
DX_CLUSTER_BACKUP_SERVERS = config.get('dx_cluster_backup_servers')

WATERFALL_MARGIN   = 32
MAJOR_THICK_HEIGHT = 12
MINOR_TICK_HEIGHT  = 6
MINOR_TICKS_PER_MAJOR = 10  # how many ticks between major ones (0 = none)

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

cyclicRefreshParams = [
    {'cmd': 'l AF', 'respLines': 1, 'parser': 'parse_af_gain'},
    {'cmd': 'l SQL', 'respLines': 1, 'parser': 'parse_sql_lvl'},
    {'cmd': 'l STRENGTH', 'respLines': 1, 'parser': 'parse_strength'},
    {'cmd': 'l RFPOWER_METER', 'respLines': 1, 'parser': 'parse_rf_power_meter'},
    {'cmd': 'l ALC', 'respLines': 1, 'parser': 'parse_alc'},
    {'cmd': 'l SWR', 'respLines': 1, 'parser': 'parse_swr'},
    {'cmd': '\\get_powerstat', 'respLines': 1, 'parser': 'parse_powerstat'},
    {'cmd': 'f', 'respLines': 1, 'parser': 'parse_freq'},
    {'cmd': 'm', 'respLines': 1, 'parser': 'parse_freq'},
    {'cmd': '\\get_vfo_info VFOA', 'expectedResp': 'get_vfo_info', 'parser': 'parse_vfoa', 'oneTime': True},
    {'cmd': '\\get_vfo_info VFOB', 'expectedResp': 'get_vfo_info', 'parser': 'parse_vfob', 'oneTime': True},
    {'cmd': 'l RFPOWER', 'respLines': 1, 'parser': 'parse_rf_power'},
    {'cmd': 'u TUNER', 'expectedResp': 'get_func', 'parser': 'parse_tuner', 'oneTime': True},
    {'cmd': 't', 'respLines': 1, 'parser': 'parse_tx'},
    {'cmd': 'l PREAMP', 'expectedResp': 'get_level', 'parser': 'parse_preamp', 'oneTime': True},
    {'cmd': 'v', 'respLines': 1, 'parser': 'parse_vfo'},
    {'cmd': 'u NB', 'expectedResp': 'get_func', 'parser': 'parse_nb', 'oneTime': True},
    {'cmd': 'u MON', 'expectedResp': 'get_func', 'parser': 'parse_mon', 'oneTime': True},
    {'cmd': 'l IF', 'expectedResp': 'get_level', 'parser': 'parse_if', 'oneTime': True},
    {'cmd': 'u MN', 'expectedResp': 'get_func', 'parser': 'parse_mn', 'oneTime': True},
    {'cmd': 'l NOTCHF', 'expectedResp': 'get_level', 'parser': 'parse_notchf', 'oneTime': True},
    {'cmd': 'u NR', 'expectedResp': 'get_func', 'parser': 'parse_u_nr', 'oneTime': True},
    {'cmd': 'l NR', 'expectedResp': 'get_level', 'parser': 'parse_l_nr', 'oneTime': True},
    {'cmd': 'l ATT', 'expectedResp': 'get_level', 'parser': 'parse_att', 'oneTime': True},
    # {'cmd': 'wRA0;', 'respLines': 1, 'parser': 'parse_att'},
    # {'cmd': 'wRA0;', 'respLines': 1, 'parser': 'parse_att'},
]

radioModesRx = ['', 'LSB', 'USB', 'CW', 'FM', 'AM', 'DATA-L', 'CWR', 'USER-L', 'DATA-U']
radioModes = ['LSB', 'USB', 'CW', 'FM', 'AM']

def findIndexOfString(element, matrix):
    for i in range(len(matrix)):
        if matrix[i] == element:
            return i
    return None

class RigctlClient:
    def __init__(self, host: str, port: int, timeout: float = TCP_TIMEOUT):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.trx_power_status = 0
        self.s = None
        try:
            self.s = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self.connected = 1
        except:
            self.connected = 0

    def send(self, cmd: str):
        if not cmd.endswith("\n"):
            cmd = cmd + "\n"
        try:
            if self.s is not None:
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
            self.connected = 0
            self.s = None
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

class EqDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, current_eq = 0):
        super().__init__(parent)
        self.setWindowTitle("Microphone EQ")
        self.selected_eq = None

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(QtWidgets.QLabel("Choose EQ preset:"))

        self.buttons = []

        # Creating radio buttons
        for i, label in enumerate(EQ_OPTIONS):
            rb = QtWidgets.QRadioButton(f"{i}: {label}")
            mono = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
            rb.setFont(mono)
            layout.addWidget(rb)
            self.buttons.append(rb)

        self.buttons[int(current_eq)].setChecked(True)

        # OK / Cancel
        btn_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self.setLayout(layout)

    def accept(self):
        # find selected preset
        for i, rb in enumerate(self.buttons):
            if rb.isChecked():
                self.selected_eq = i
                break
        super().accept()

class ClickableLabel(QtWidgets.QLabel):
    clicked = QtCore.pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

class SliderDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, value=5):
        super().__init__(parent)
        self.setWindowTitle("Set value")

        # Slider from 5 to 100
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(5, 100)
        self.slider.setValue(value)

        # Label showing current value
        self.label = QtWidgets.QLabel(str(self.slider.value()))
        self.slider.valueChanged.connect(lambda v: self.label.setText(str(v)))

        # 'Set' button
        self.button = QtWidgets.QPushButton("Set")
        self.button.clicked.connect(self.accept)  # closes dialog

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.label)
        layout.addWidget(self.slider)
        layout.addWidget(self.button)
        self.setLayout(layout)

    def get_value(self):
        return self.slider.value()
    
class FrequencyDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, value=0):
        super().__init__(parent)
        self.setWindowTitle("Set Frequency (Hz)")

        # Text field
        self.edit = QtWidgets.QLineEdit(str(value))

        # Description label
        label = QtWidgets.QLabel("Enter frequency (0 - 52 000 000 Hz):")

        # 'Set' button
        self.button = QtWidgets.QPushButton("Set")
        self.button.clicked.connect(self.on_accept)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(label)
        layout.addWidget(self.edit)
        layout.addWidget(self.button)
        self.setLayout(layout)

    def on_accept(self):
        text = self.edit.text().strip()

        # check if number
        if not text.isdigit():
            QtWidgets.QMessageBox.warning(self, "Error", "Please enter a valid integer number.")
            return

        value = int(text)

        # check range
        if not (0 <= value <= 52000000):
            QtWidgets.QMessageBox.warning(
                self, "Error", "Frequency must be between 0 and 52,000,000 Hz."
            )
            return

        self.accept()  # closes dialog if OK

    def get_value(self):
        return int(self.edit.text())


class BookmarksDialog(QtWidgets.QDialog):
    """Dialog for viewing, selecting, and deleting bookmarks."""

    def __init__(self, parent=None, bookmarks=None):
        super().__init__(parent)
        self.setWindowTitle("Bookmarks")
        self.setMinimumWidth(400)
        self.setMinimumHeight(350)
        self.bookmarks = list(bookmarks) if bookmarks else []
        self.selected_bookmark = None

        layout = QtWidgets.QVBoxLayout(self)

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.itemDoubleClicked.connect(self._on_double_click)
        self._populate_list()
        layout.addWidget(self.list_widget)

        btn_layout = QtWidgets.QHBoxLayout()
        self.tune_btn = QtWidgets.QPushButton("Tune")
        self.tune_btn.clicked.connect(self._on_tune)
        btn_layout.addWidget(self.tune_btn)

        self.delete_btn = QtWidgets.QPushButton("Delete")
        self.delete_btn.clicked.connect(self._on_delete)
        btn_layout.addWidget(self.delete_btn)

        self.edit_btn = QtWidgets.QPushButton("Edit")
        self.edit_btn.clicked.connect(self._on_edit)
        btn_layout.addWidget(self.edit_btn)

        self.close_btn = QtWidgets.QPushButton("Close")
        self.close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)

    def _populate_list(self):
        self.list_widget.clear()
        for bm in self.bookmarks:
            freq_mhz = bm['freq_hz'] / 1e6
            mode = bm.get('mode', '?')
            name = bm.get('name', '')
            text = f"{freq_mhz:.4f} MHz  [{mode}]  {name}"
            self.list_widget.addItem(text)

    def _on_tune(self):
        row = self.list_widget.currentRow()
        if 0 <= row < len(self.bookmarks):
            self.selected_bookmark = self.bookmarks[row]
            self.accept()

    def _on_double_click(self, item):
        self._on_tune()

    def _on_delete(self):
        row = self.list_widget.currentRow()
        if 0 <= row < len(self.bookmarks):
            name = self.bookmarks[row].get('name', '')
            reply = QtWidgets.QMessageBox.question(
                self, "Delete Bookmark",
                f"Delete bookmark '{name}'?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            )
            if reply == QtWidgets.QMessageBox.Yes:
                self.bookmarks.pop(row)
                self._populate_list()

    def _on_edit(self):
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(self.bookmarks):
            return
        bm = self.bookmarks[row]
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Edit Bookmark")
        form = QtWidgets.QFormLayout(dlg)

        name_edit = QtWidgets.QLineEdit(bm.get('name', ''))
        form.addRow("Name:", name_edit)

        freq_edit = QtWidgets.QDoubleSpinBox()
        freq_edit.setDecimals(4)
        freq_edit.setRange(0.0, 500.0)
        freq_edit.setSuffix(" MHz")
        freq_edit.setValue(bm['freq_hz'] / 1e6)
        form.addRow("Frequency:", freq_edit)

        mode_edit = QtWidgets.QComboBox()
        modes = ['USB', 'LSB', 'AM', 'FM', 'CW', 'CWR']
        mode_edit.addItems(modes)
        idx = mode_edit.findText(bm.get('mode', 'USB'))
        if idx >= 0:
            mode_edit.setCurrentIndex(idx)
        form.addRow("Mode:", mode_edit)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)

        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            bm['name'] = name_edit.text().strip()
            bm['freq_hz'] = int(freq_edit.value() * 1e6)
            bm['mode'] = mode_edit.currentText()
            self._populate_list()


class SettingsDialog(QtWidgets.QDialog):
    """Application settings dialog with tabs"""
    
    def __init__(self, parent=None, current_config=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)
        
        self.config = current_config or config
        self.temp_settings = self.config.settings.copy()
        
        # Main layout
        main_layout = QtWidgets.QVBoxLayout()
        
        # Tabs
        self.tabs = QtWidgets.QTabWidget()
        
        # --- Tab: Connection ---
        tab_connection = QtWidgets.QWidget()
        layout_conn = QtWidgets.QFormLayout()
        
        # Config file selection
        config_file_layout = QtWidgets.QHBoxLayout()
        self.config_file_label = QtWidgets.QLabel(os.path.basename(self.config.config_file))
        self.config_file_label.setStyleSheet("color: gray; font-style: italic;")
        btn_select_config = QtWidgets.QPushButton("Select...")
        btn_select_config.clicked.connect(self.select_config_file)
        btn_save_as_config = QtWidgets.QPushButton("Save As...")
        btn_save_as_config.clicked.connect(self.save_config_as)
        config_file_layout.addWidget(self.config_file_label)
        config_file_layout.addWidget(btn_select_config)
        config_file_layout.addWidget(btn_save_as_config)
        layout_conn.addRow("Config File:", config_file_layout)
        
        layout_conn.addRow("", QtWidgets.QLabel(""))  # Separator
        
        self.edit_host = QtWidgets.QLineEdit(str(self.temp_settings['host']))
        self.edit_port = QtWidgets.QSpinBox()
        self.edit_port.setRange(1, 65535)
        self.edit_port.setValue(self.temp_settings['port'])
        self.edit_poll_ms = QtWidgets.QSpinBox()
        self.edit_poll_ms.setRange(100, 5000)
        self.edit_poll_ms.setSuffix(" ms")
        self.edit_poll_ms.setValue(self.temp_settings['poll_ms'])
        
        layout_conn.addRow("Host IP:", self.edit_host)
        layout_conn.addRow("Rigctl Port:", self.edit_port)
        layout_conn.addRow("Poll Interval:", self.edit_poll_ms)

        layout_conn.addRow("", QtWidgets.QLabel(""))  # Separator

        audio_in_items  = [("Default (system)", None)]
        audio_out_items = [("Default (system)", None)]
        try:
            import sounddevice as _sd
            for i, d in enumerate(_sd.query_devices()):
                label = f"[{i}] {d['name']}"
                if d['max_input_channels'] > 0:
                    audio_in_items.append((label, i))
                if d['max_output_channels'] > 0:
                    audio_out_items.append((label, i))
        except Exception:
            pass

        self.combo_audio_input  = QtWidgets.QComboBox()
        self.combo_audio_output = QtWidgets.QComboBox()
        for label, idx in audio_in_items:
            self.combo_audio_input.addItem(label, idx)
        for label, idx in audio_out_items:
            self.combo_audio_output.addItem(label, idx)

        self._select_audio_combo(self.combo_audio_input,  self.temp_settings.get('audio_input_device'))
        self._select_audio_combo(self.combo_audio_output, self.temp_settings.get('audio_output_device'))

        layout_conn.addRow("Audio In (Mic):",    self.combo_audio_input)
        layout_conn.addRow("Audio Out (Speaker):", self.combo_audio_output)

        audio_note = QtWidgets.QLabel("Audio device change requires disconnecting and reconnecting audio.")
        audio_note.setStyleSheet("color: gray; font-size: 9pt;")
        audio_note.setWordWrap(True)
        layout_conn.addRow("", audio_note)

        tab_connection.setLayout(layout_conn)
        self.tabs.addTab(tab_connection, "Connection")

        # --- Tab: Radio Settings ---
        tab_radio = QtWidgets.QWidget()
        layout_radio = QtWidgets.QFormLayout()
        
        self.edit_freq_step_slow = QtWidgets.QSpinBox()
        self.edit_freq_step_slow.setRange(1, 10000)
        self.edit_freq_step_slow.setSuffix(" Hz")
        self.edit_freq_step_slow.setValue(self.temp_settings['freq_step_slow'])
        
        self.edit_freq_step_fast = QtWidgets.QSpinBox()
        self.edit_freq_step_fast.setRange(1, 10000)
        self.edit_freq_step_fast.setSuffix(" Hz")
        self.edit_freq_step_fast.setValue(self.temp_settings['freq_step_fast'])
        
        self.edit_mouse_wheel_freq = QtWidgets.QSpinBox()
        self.edit_mouse_wheel_freq.setRange(1, 10000)
        self.edit_mouse_wheel_freq.setSuffix(" Hz")
        self.edit_mouse_wheel_freq.setValue(self.temp_settings['mouse_wheel_freq_step'])
        
        self.edit_mouse_wheel_fast_freq = QtWidgets.QSpinBox()
        self.edit_mouse_wheel_fast_freq.setRange(1, 10000)
        self.edit_mouse_wheel_fast_freq.setSuffix(" Hz")
        self.edit_mouse_wheel_fast_freq.setValue(self.temp_settings['mouse_wheel_fast_freq_step'])
        
        self.edit_tx_off_delay = QtWidgets.QSpinBox()
        self.edit_tx_off_delay.setRange(0, 1000)
        self.edit_tx_off_delay.setSuffix(" ms")
        self.edit_tx_off_delay.setValue(self.temp_settings['tx_off_delay'])
        
        self.edit_default_nr = QtWidgets.QSpinBox()
        self.edit_default_nr.setRange(1, 11)
        self.edit_default_nr.setValue(self.temp_settings['default_noise_reduction'])
        
        layout_radio.addRow("Freq Step (Slow):", self.edit_freq_step_slow)
        layout_radio.addRow("Freq Step (Fast):", self.edit_freq_step_fast)
        layout_radio.addRow("Mouse Wheel Step:", self.edit_mouse_wheel_freq)
        layout_radio.addRow("Mouse Wheel Step (Fast):", self.edit_mouse_wheel_fast_freq)
        layout_radio.addRow("TX Off Delay:", self.edit_tx_off_delay)
        layout_radio.addRow("Default Noise Reduction:", self.edit_default_nr)
        
        tab_radio.setLayout(layout_radio)
        self.tabs.addTab(tab_radio, "Radio")
        
        # --- Tab: Keyboard ---
        tab_keyboard = QtWidgets.QWidget()
        layout_keyboard = QtWidgets.QFormLayout()
        
        self.edit_ptt_key = QtWidgets.QLineEdit(str(self.temp_settings['ptt_key']))
        layout_keyboard.addRow("PTT Key:", self.edit_ptt_key)
        
        help_label = QtWidgets.QLabel("Examples: ctrl_r, alt_l, shift, space, a, b, etc.")
        help_label.setStyleSheet("color: gray; font-size: 9pt;")
        layout_keyboard.addRow("", help_label)
        
        tab_keyboard.setLayout(layout_keyboard)
        self.tabs.addTab(tab_keyboard, "Keyboard")
        
        # --- Tab: Antenna Switch ---
        tab_antenna = QtWidgets.QWidget()
        layout_antenna = QtWidgets.QFormLayout()
        
        self.check_antenna_enabled = QtWidgets.QCheckBox("Enable Antenna Switch")
        self.check_antenna_enabled.setChecked(self.temp_settings['antenna_switch_enabled'])
        
        self.edit_antenna_1_name = QtWidgets.QLineEdit(str(self.temp_settings['antenna_1_name']))
        self.edit_antenna_2_name = QtWidgets.QLineEdit(str(self.temp_settings['antenna_2_name']))
        self.edit_antenna_3_name = QtWidgets.QLineEdit(str(self.temp_settings['antenna_3_name']))
        
        layout_antenna.addRow("", self.check_antenna_enabled)
        layout_antenna.addRow("Antenna 1 Name:", self.edit_antenna_1_name)
        layout_antenna.addRow("Antenna 2 Name:", self.edit_antenna_2_name)
        layout_antenna.addRow("Antenna 3 Name:", self.edit_antenna_3_name)
        
        cmd_label = QtWidgets.QLabel("Commands are fixed: 1, 2, 3")
        cmd_label.setStyleSheet("color: gray; font-size: 9pt;")
        layout_antenna.addRow("", cmd_label)
        
        tab_antenna.setLayout(layout_antenna)
        self.tabs.addTab(tab_antenna, "Antenna")
        
        # --- Tab: Waterfall ---
        tab_waterfall = QtWidgets.QWidget()
        layout_waterfall = QtWidgets.QFormLayout()
        
        self.check_waterfall_enabled = QtWidgets.QCheckBox("Enable Waterfall")
        self.check_waterfall_enabled.setChecked(self.temp_settings['waterfall_enabled'])
        
        self.edit_initial_zoom = QtWidgets.QDoubleSpinBox()
        self.edit_initial_zoom.setRange(0.05, 1.0)
        self.edit_initial_zoom.setSingleStep(0.05)
        self.edit_initial_zoom.setDecimals(2)
        self.edit_initial_zoom.setValue(self.temp_settings['waterfall_initial_zoom'])
        
        self.edit_dynamic_range = QtWidgets.QSpinBox()
        self.edit_dynamic_range.setRange(10, 100)
        self.edit_dynamic_range.setSuffix(" dB")
        self.edit_dynamic_range.setValue(self.temp_settings['waterfall_dynamic_range'])
        
        layout_waterfall.addRow("", self.check_waterfall_enabled)
        layout_waterfall.addRow("Initial Zoom:", self.edit_initial_zoom)
        layout_waterfall.addRow("Dynamic Range:", self.edit_dynamic_range)
        
        # DX Cluster settings
        dx_separator = QtWidgets.QFrame()
        dx_separator.setFrameShape(QtWidgets.QFrame.HLine)
        dx_separator.setStyleSheet("color: gray;")
        layout_waterfall.addRow(dx_separator)
        
        self.check_dx_cluster_enabled = QtWidgets.QCheckBox("Enable DX Cluster")
        self.check_dx_cluster_enabled.setChecked(self.temp_settings.get('dx_cluster_enabled', False))
        layout_waterfall.addRow("", self.check_dx_cluster_enabled)
        
        self.edit_dx_callsign = QtWidgets.QLineEdit(str(self.temp_settings.get('dx_cluster_callsign', 'N0CALL')))
        self.edit_dx_callsign.setMaxLength(12)
        layout_waterfall.addRow("Callsign:", self.edit_dx_callsign)
        
        self.edit_dx_server = QtWidgets.QLineEdit(str(self.temp_settings.get('dx_cluster_server', 'dxc.ve7cc.net')))
        layout_waterfall.addRow("Server:", self.edit_dx_server)
        
        self.edit_dx_port = QtWidgets.QSpinBox()
        self.edit_dx_port.setRange(1, 65535)
        self.edit_dx_port.setValue(self.temp_settings.get('dx_cluster_port', 23))
        layout_waterfall.addRow("Port:", self.edit_dx_port)
        
        self.edit_dx_backup = QtWidgets.QLineEdit(str(self.temp_settings.get('dx_cluster_backup_servers', '')))
        self.edit_dx_backup.setPlaceholderText("host:port,host:port,...")
        layout_waterfall.addRow("Backup Servers:", self.edit_dx_backup)
        
        restart_label = QtWidgets.QLabel("⚠️ Requires restart to apply")
        restart_label.setStyleSheet("color: orange; font-weight: bold;")
        layout_waterfall.addRow("", restart_label)
        
        tab_waterfall.setLayout(layout_waterfall)
        self.tabs.addTab(tab_waterfall, "Waterfall")
        
        # --- Tab: Filter Widths ---
        tab_filters = QtWidgets.QWidget()
        layout_filters = QtWidgets.QVBoxLayout()
        
        # Scroll area for filters
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QtWidgets.QWidget()
        layout_filters_form = QtWidgets.QFormLayout()
        
        self.filter_edits = {}
        modes = ['usb', 'lsb', 'am', 'fm', 'cw', 'cwr']
        widths = ['narrow', 'normal', 'wide']
        
        for mode in modes:
            mode_label = QtWidgets.QLabel(f"\n{mode.upper()}")
            mode_label.setStyleSheet("font-weight: bold; font-size: 11pt;")
            layout_filters_form.addRow(mode_label)
            
            for width in widths:
                key = f'filter_width_{mode}_{width}'
                spinbox = QtWidgets.QSpinBox()
                spinbox.setRange(50, 10000)
                spinbox.setSuffix(" Hz")
                spinbox.setValue(self.temp_settings[key])
                self.filter_edits[key] = spinbox
                layout_filters_form.addRow(f"  {width.capitalize()}:", spinbox)
        
        scroll_content.setLayout(layout_filters_form)
        scroll.setWidget(scroll_content)
        layout_filters.addWidget(scroll)
        
        tab_filters.setLayout(layout_filters)
        self.tabs.addTab(tab_filters, "Filters")
        
        # --- Tab: Interface ---
        tab_interface = QtWidgets.QWidget()
        layout_interface = QtWidgets.QFormLayout()
        
        self.check_stay_on_top = QtWidgets.QCheckBox("Stay on Top")
        self.check_stay_on_top.setChecked(self.temp_settings.get('stay_on_top', False))
        
        layout_interface.addRow("", self.check_stay_on_top)
        
        restart_label2 = QtWidgets.QLabel("⚠️ Requires restart to apply")
        restart_label2.setStyleSheet("color: orange; font-weight: bold;")
        layout_interface.addRow("", restart_label2)
        
        tab_interface.setLayout(layout_interface)
        self.tabs.addTab(tab_interface, "Interface")
        
        # Add tabs to main layout
        main_layout.addWidget(self.tabs)
        
        # Buttons
        button_box = QtWidgets.QDialogButtonBox()
        
        btn_save = button_box.addButton("Save", QtWidgets.QDialogButtonBox.AcceptRole)
        btn_cancel = button_box.addButton("Cancel", QtWidgets.QDialogButtonBox.RejectRole)
        btn_reset = button_box.addButton("Reset to Defaults", QtWidgets.QDialogButtonBox.ResetRole)
        
        button_box.accepted.connect(self.save_settings)
        button_box.rejected.connect(self.reject)
        btn_reset.clicked.connect(self.reset_to_defaults)
        
        main_layout.addWidget(button_box)
        
        self.setLayout(main_layout)
    
    def save_settings(self):
        """Saves settings to temp_settings and closes dialog"""
        # Update temp_settings from fields
        self.update_temp_settings_from_fields()
        
        # Update main configuration
        self.config.settings = self.temp_settings.copy()
        
        # Save to file
        if self.config.save():
            self.config.save_active_config_name()
            self.accept()
        else:
            QtWidgets.QMessageBox.warning(
                self, 
                "Error", 
                "Failed to save settings to file."
            )
    
    def reset_to_defaults(self):
        """Resets all settings to default values"""
        reply = QtWidgets.QMessageBox.question(
            self,
            "Reset to Defaults",
            "Are you sure you want to reset all settings to default values?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            self.config.reset_to_defaults()
            self.temp_settings = self.config.settings.copy()
            # Refresh all fields
            self.refresh_all_fields()
    
    def select_config_file(self):
        """Select configuration file"""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Configuration File",
            dir_path,
            "JSON Files (*.json);;All Files (*.*)"
        )
        
        if file_path:
            # Load selected configuration
            new_config = Config(file_path)
            self.config = new_config
            self.temp_settings = self.config.settings.copy()
            
            self.config.save_active_config_name()
            
            # Update file name in UI
            self.config_file_label.setText(os.path.basename(file_path))
            
            # Refresh all fields
            self.refresh_all_fields()
    
    def save_config_as(self):
        """Save current configuration to new file"""
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Configuration As",
            dir_path,
            "JSON Files (*.json);;All Files (*.*)"
        )
        
        if file_path:
            # Ensure file has .json extension
            if not file_path.endswith('.json'):
                file_path += '.json'
            
            # Update temp_settings from current field values
            self.update_temp_settings_from_fields()
            
            # Create new configuration with this file
            new_config = Config(file_path)
            new_config.settings = self.temp_settings.copy()
            
            # Save to new file
            if new_config.save():
                # Switch to new file
                self.config = new_config
                self.config.save_active_config_name()
                self.config_file_label.setText(os.path.basename(file_path))
                
                QtWidgets.QMessageBox.information(
                    self,
                    "Success",
                    f"Configuration saved to:\n{os.path.basename(file_path)}"
                )
            else:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Error",
                    "Failed to save configuration file."
                )
    
    def update_temp_settings_from_fields(self):
        """Updates temp_settings from current values in dialog fields"""
        # Connection
        self.temp_settings['host'] = self.edit_host.text().strip()
        self.temp_settings['port'] = self.edit_port.value()
        self.temp_settings['poll_ms'] = self.edit_poll_ms.value()
        
        # Radio
        self.temp_settings['freq_step_slow'] = self.edit_freq_step_slow.value()
        self.temp_settings['freq_step_fast'] = self.edit_freq_step_fast.value()
        self.temp_settings['mouse_wheel_freq_step'] = self.edit_mouse_wheel_freq.value()
        self.temp_settings['mouse_wheel_fast_freq_step'] = self.edit_mouse_wheel_fast_freq.value()
        self.temp_settings['tx_off_delay'] = self.edit_tx_off_delay.value()
        self.temp_settings['default_noise_reduction'] = self.edit_default_nr.value()
        
        # Keyboard
        self.temp_settings['ptt_key'] = self.edit_ptt_key.text().strip()
        
        # Antenna
        self.temp_settings['antenna_switch_enabled'] = self.check_antenna_enabled.isChecked()
        self.temp_settings['antenna_1_name'] = self.edit_antenna_1_name.text().strip()
        self.temp_settings['antenna_2_name'] = self.edit_antenna_2_name.text().strip()
        self.temp_settings['antenna_3_name'] = self.edit_antenna_3_name.text().strip()
        
        # Waterfall
        self.temp_settings['waterfall_enabled'] = self.check_waterfall_enabled.isChecked()
        self.temp_settings['waterfall_initial_zoom'] = self.edit_initial_zoom.value()
        self.temp_settings['waterfall_dynamic_range'] = self.edit_dynamic_range.value()
        
        # DX Cluster
        self.temp_settings['dx_cluster_enabled'] = self.check_dx_cluster_enabled.isChecked()
        self.temp_settings['dx_cluster_callsign'] = self.edit_dx_callsign.text().strip().upper()
        self.temp_settings['dx_cluster_server'] = self.edit_dx_server.text().strip()
        self.temp_settings['dx_cluster_port'] = self.edit_dx_port.value()
        self.temp_settings['dx_cluster_backup_servers'] = self.edit_dx_backup.text().strip()
        
        # Filters
        for key, spinbox in self.filter_edits.items():
            self.temp_settings[key] = spinbox.value()
        
        # Interface
        self.temp_settings['stay_on_top'] = self.check_stay_on_top.isChecked()

        # Audio
        self.temp_settings['audio_input_device']  = self.combo_audio_input.currentData()
        self.temp_settings['audio_output_device'] = self.combo_audio_output.currentData()

    def refresh_all_fields(self):
        """Refreshes all fields in dialog"""
        # Connection
        self.edit_host.setText(str(self.temp_settings['host']))
        self.edit_port.setValue(self.temp_settings['port'])
        self.edit_poll_ms.setValue(self.temp_settings['poll_ms'])
        
        # Radio
        self.edit_freq_step_slow.setValue(self.temp_settings['freq_step_slow'])
        self.edit_freq_step_fast.setValue(self.temp_settings['freq_step_fast'])
        self.edit_mouse_wheel_freq.setValue(self.temp_settings['mouse_wheel_freq_step'])
        self.edit_mouse_wheel_fast_freq.setValue(self.temp_settings['mouse_wheel_fast_freq_step'])
        self.edit_tx_off_delay.setValue(self.temp_settings['tx_off_delay'])
        self.edit_default_nr.setValue(self.temp_settings['default_noise_reduction'])
        
        # Keyboard
        self.edit_ptt_key.setText(str(self.temp_settings['ptt_key']))
        
        # Antenna
        self.check_antenna_enabled.setChecked(self.temp_settings['antenna_switch_enabled'])
        self.edit_antenna_1_name.setText(str(self.temp_settings['antenna_1_name']))
        self.edit_antenna_2_name.setText(str(self.temp_settings['antenna_2_name']))
        self.edit_antenna_3_name.setText(str(self.temp_settings['antenna_3_name']))
        
        # Waterfall
        self.check_waterfall_enabled.setChecked(self.temp_settings['waterfall_enabled'])
        self.edit_initial_zoom.setValue(self.temp_settings['waterfall_initial_zoom'])
        self.edit_dynamic_range.setValue(self.temp_settings['waterfall_dynamic_range'])
        
        # DX Cluster
        self.check_dx_cluster_enabled.setChecked(self.temp_settings.get('dx_cluster_enabled', False))
        self.edit_dx_callsign.setText(str(self.temp_settings.get('dx_cluster_callsign', 'N0CALL')))
        self.edit_dx_server.setText(str(self.temp_settings.get('dx_cluster_server', 'dxc.ve7cc.net')))
        self.edit_dx_port.setValue(self.temp_settings.get('dx_cluster_port', 23))
        self.edit_dx_backup.setText(str(self.temp_settings.get('dx_cluster_backup_servers', '')))
        
        # Filters
        for key, spinbox in self.filter_edits.items():
            spinbox.setValue(self.temp_settings[key])
        
        # Interface
        self.check_stay_on_top.setChecked(self.temp_settings.get('stay_on_top', False))

        # Audio
        self._select_audio_combo(self.combo_audio_input,  self.temp_settings.get('audio_input_device'))
        self._select_audio_combo(self.combo_audio_output, self.temp_settings.get('audio_output_device'))

    def _select_audio_combo(self, combo, device_value):
        """Selects combo item matching device index/None."""
        for i in range(combo.count()):
            if combo.itemData(i) == device_value:
                combo.setCurrentIndex(i)
                return
        combo.setCurrentIndex(0)  # fallback: Default


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
        self.request_sent = False
        self.one_time_done = set()
        self.reset_one_time.connect(self.on_reset_one_time)

    @QtCore.pyqtSlot()
    def start(self):
        self._timer = QtCore.QTimer()
        self._timer.setInterval(self.poll_ms)
        self._timer.timeout.connect(self.poll_all)
        self._timer.start()
        self.poll_all()  # first read

    @QtCore.pyqtSlot(int)
    def pause(self, ms: int):
        """Stops polling for specified time (ms)."""
        if self._timer and self._timer.isActive():
            self._timer.stop()
            # print('pause')
            QtCore.QTimer.singleShot(ms, self.resume)

    @QtCore.pyqtSlot()
    def resume(self):
        """Resumes polling."""
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
        """Allows re-execution of oneTime command read."""
        if cmd in self.one_time_done:
            self.one_time_done.remove(cmd)
        elif cmd == 'all':
            self.one_time_done = set()
            self.one_time_done.add('\\get_vfo_info VFOA')
            self.one_time_done.add('\\get_vfo_info VFOB')

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

            # skip oneTime if already executed
            if is_one_time and command in self.one_time_done:
                continue

            # skip during TX (optional)
            if getattr(self, "tx_active", 0) == 1 and is_one_time:
                continue

            # add command to set
            cmd += '+' + command + ' '

        cmd += '\n'
        # print(cmd)
        resp = self.client.send(cmd)
        # print(resp)

        if not resp:
            self.status.emit(f"No answer from {HOST}:{PORT}")
            if self.retry_cnt > MAX_RETRY_CNT:
                # self._timer.setInterval(SLOWER_POLL_MS)
                pass
            else:
                self.retry_cnt += 1
            return

        parts = re.split(r'(RPRT [+-]?\d+)', resp)
        respArray = []
        tmp = ""

        for part in parts:
            if re.match(r'RPRT [+-]?\d+', part):
                # this is the end marker -> add to current block and close block
                tmp += part + "\n"
                respArray.append(tmp)
                tmp = ""
            else:
                # data part
                tmp += part

        # remove empty elements
        respArray =  [b for b in respArray if b.strip()]
        # print(respArray)
        self.result.emit(respArray)

        # mark oneTime as executed
        for item in respArray:
            if 'RPRT 0' in item:
                for param in cyclicRefreshParams:
                    if param.get('oneTime', False):
                        if param.get('expectedResp') + ': ' + param.get('cmd').split(' ')[1] in item:
                            cmd = param['cmd']
                            if cmd not in self.one_time_done:
                                self.one_time_done.add(cmd)
                                # print(cmd + ' received OK')
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
            # means second click occurred before timer was reset -> double click
            self._click_timer.stop()
            self.doubleClicked.emit()
        else:
            # start timer and wait if second click comes
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
        # Vectorized: extract all nibbles at once
        arr = np.frombuffer(data, dtype=np.uint8)
        nibbles = np.empty(len(arr) * 2, dtype=np.int32)
        nibbles[0::2] = arr & 0x0F
        nibbles[1::2] = (arr >> 4) & 0x0F
        # Process sequentially but with less Python overhead
        idx_table = ImaAdpcmCodec.ima_index_table
        step_table = ImaAdpcmCodec.ima_step_table
        output = np.empty(len(nibbles), dtype=np.int16)
        step_index = self.step_index
        predictor = self.predictor
        step = self.step
        for i in range(len(nibbles)):
            nib = nibbles[i]
            step_index += idx_table[nib]
            if step_index < 0: step_index = 0
            elif step_index > 88: step_index = 88
            diff = step >> 3
            if nib & 1: diff += step >> 2
            if nib & 2: diff += step >> 1
            if nib & 4: diff += step
            if nib & 8: diff = -diff
            predictor += diff
            if predictor > 32767: predictor = 32767
            elif predictor < -32768: predictor = -32768
            output[i] = predictor
            step = step_table[step_index]
        self.step_index = step_index
        self.predictor = predictor
        self.step = step
        return output
    
def draw_line(data: np.ndarray, palette: np.ndarray, min_db=-120.0, max_db=-30.0, offset=0.0) -> np.ndarray:
    data_offset = data + offset
    norm = np.clip((data_offset - min_db) / (max_db - min_db), 0.0, 1.0)
    indices = (norm * (len(palette) - 1)).astype(np.int32)
    rgb_row = palette[indices]
    return rgb_row

class WaterfallWidget(QtWidgets.QWidget):
    freq_clicked = QtCore.pyqtSignal(int)   # emitted when user clicks/selects freq
    freq_hover = QtCore.pyqtSignal(int)     # emitted when mouse moves (position)
    freq_selected = QtCore.pyqtSignal(int)     # emitted when mouse moves (position)
    new_min_db = QtCore.pyqtSignal(int)
    adjust_waterfall = QtCore.pyqtSignal()
    zoom_changed = QtCore.pyqtSignal(int)   # emitted when zoom_factor changes (value 5..100)

    def __init__(self, width=800, height=200, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Waterfall view")
        self.width_px = width
        self.height_px = int(height/2)
        self.setMinimumSize(400, int(height/2))

        # QImage as buffer only for display; we also keep _buffer (numpy) to safely modify
        self._image = QtGui.QImage(self.width_px, self.height_px, QtGui.QImage.Format_RGB888)
        self._image.fill(QtGui.QColor('black'))
        self._buffer = np.zeros((self.height_px, self.width_px, 3), dtype=np.uint8)
        self.setMouseTracking(True)

        self._lock = threading.Lock()
        self.min_db = WATERFALL_MIN_DB_DEFAULT
        self.max_db = self.min_db + WATERFALL_DYNAMIC_RANGE
        self.fft_avg = 0

        # FPS limiting
        import time as _time
        self._last_frame_time = 0.0
        self._min_frame_interval = 1.0 / 20  # max ~20 FPS
        self._time = _time

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

        # frequencies - will be updated from WsReceiver
        self.samp_rate = 1000000
        self.center_freq = 14250000
        self.selected_freq = self.center_freq
        self.filter_width = FILTER_WIDTH_USB_NORMAL
        self.mode = 'USB'

        self.waterfall_config_received = False
        self.initial_zoom_set = False
        self.fast_freq = False

        # DX Cluster spots
        self.dx_spots = []
        self.dx_cluster_enabled = DX_CLUSTER_ENABLED
        self._hovered_spot = None  # spot dict when mouse is near a dot

        # Bookmarks
        self.bookmarks = []
        self._hovered_bookmark = None

        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

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

    @QtCore.pyqtSlot(bool)
    def fast_freq_update(self, val: bool):
        self.fast_freq = val

    @QtCore.pyqtSlot(int, int, str)
    def update_selected_freq(self, freq, width, mode):
        self.selected_freq = freq
        self.filter_width = width
        self.mode = mode

        if not self.initial_zoom_set and self.waterfall_config_received and self.fft_avg != 0:
            # zoom modification
            self.zoom_factor = INITIAL_ZOOM
            # zoom limits
            self.zoom_factor = max(0.05, min(1.0, self.zoom_factor))
            self.zoom_changed.emit(int(105 - self.zoom_factor * 100))
            # change view center to keep the same frequency under cursor
            if hasattr(self, "samp_rate") and self.samp_rate > 0:
                full_bw = self.samp_rate
                start_freq = self.center_freq - self.samp_rate/2
                self.center_pos = (freq - start_freq)/(full_bw) # np.clip(self.center_pos + delta_norm, 0.0, 1.0)

            # waterfall levels adjustment
            self.adjustWaterfallColors()

            self.initial_zoom_set = True
            self.update()

    @QtCore.pyqtSlot()
    def adjustWaterfallColors(self):
            self.min_db = self.fft_avg - WATERFALL_DYNAMIC_RANGE * 0.3
            self.max_db = self.min_db + WATERFALL_DYNAMIC_RANGE
            self.new_min_db.emit(int(self.min_db))

    def resizeEvent(self, event):
        new_size = event.size()
        with self._lock:
            self.width_px = new_size.width()
            self.height_px = new_size.height()
            self._image = QtGui.QImage(self.width_px, self.height_px, QtGui.QImage.Format_RGB888)
            self._image.fill(QtGui.QColor('black'))
            self._buffer = np.zeros((self.height_px, self.width_px, 3), dtype=np.uint8)

        self.update()
        super().resizeEvent(event)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()

        if event.modifiers() & QtCore.Qt.ControlModifier or self._dragging:
            # pozycja kursora (x w pikselach)
            mouse_x = event.x()

            # frequency under cursor BEFORE zoom
            freq_before = self._x_to_freq(mouse_x)

            # modify zoom
            if delta > 0:
                self.zoom_factor *= 0.8
            else:
                self.zoom_factor *= 1.2

            # ograniczenia zoomu
            self.zoom_factor = max(0.05, min(1.0, self.zoom_factor))
            self.zoom_changed.emit(int(105 - self.zoom_factor * 100))

            # frequency under cursor AFTER zoom
            freq_after = self._x_to_freq(mouse_x)

            # change center view position to keep same frequency under cursor
            if hasattr(self, "samp_rate") and self.samp_rate > 0:
                full_start = self.center_freq - (self.samp_rate / 2.0)
                full_bw = self.samp_rate
                # difference between freq_before and freq_after in units [0..1]
                delta_norm = (freq_before - freq_after) / full_bw
                self.center_pos = np.clip(self.center_pos + delta_norm, 0.0, 1.0)

            self.update()
            event.accept()

        else:
            # scrolling without Ctrl - frequency change
            if delta > 0:
                delta = 1
            elif delta < 0:
                delta = -1

            if not self.fast_freq:
                step = MOUSE_WHEEL_FREQ_STEP
            else:
                step = MOUSE_WHEEL_FAST_FREQ_STEP

            self.selected_freq -= self.selected_freq % step
            self.selected_freq += delta * step
            self.freq_clicked.emit(self.selected_freq)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._dragging = True
            self._last_x = event.x()
            self._press_x = event.x()
            self._press_y = event.y()

    def _find_spot_near(self, x, y):
        """Find DX spot near pixel position (x,y). Returns spot dict or None."""
        if not self.dx_cluster_enabled or not self.dx_spots:
            return None
        vis_start, vis_end = self._visible_freq_range()
        bw = max(1e-9, vis_end - vis_start)
        HIT_RADIUS_X = 6
        best = None
        best_dist = HIT_RADIUS_X + 1
        for spot in self.dx_spots:
            f = spot['freq_hz']
            if vis_start <= f <= vis_end:
                x_spot = int((f - vis_start) / bw * (self.width_px - 1))
                dx = abs(x - x_spot)
                if dx <= HIT_RADIUS_X and dx < best_dist:
                    best = spot
                    best_dist = dx
        return best

    def _find_bookmark_near(self, x):
        """Find bookmark near pixel x position. Returns bookmark dict or None."""
        if not self.bookmarks:
            return None
        vis_start, vis_end = self._visible_freq_range()
        bw = max(1e-9, vis_end - vis_start)
        HIT_RADIUS_X = 6
        best = None
        best_dist = HIT_RADIUS_X + 1
        for bm in self.bookmarks:
            f = bm['freq_hz']
            if vis_start <= f <= vis_end:
                x_bm = int((f - vis_start) / bw * (self.width_px - 1))
                dx = abs(x - x_bm)
                if dx <= HIT_RADIUS_X and dx < best_dist:
                    best = bm
                    best_dist = dx
        return best

    def mouseMoveEvent(self, event):
        # hover - update frequency and repaint
        freq = int(self._x_to_freq(event.x()))
        if freq != self.hover_freq:
            self.hover_freq = freq
            self.freq_hover.emit(freq)
            self.update()

        # check DX spot hover
        old_spot = self._hovered_spot
        self._hovered_spot = self._find_spot_near(event.x(), event.y())
        if self._hovered_spot != old_spot:
            self.update()

        # check bookmark hover
        old_bm = self._hovered_bookmark
        self._hovered_bookmark = self._find_bookmark_near(event.x())
        if self._hovered_bookmark != old_bm:
            self.update()

        # if dragging - keep current panning
        if self._dragging:
            dx = event.x() - self._last_x
            self._last_x = event.x()
            move = -dx / max(1.0, self.width_px) * (1.0)
            self.center_pos = np.clip(self.center_pos + move * self.zoom_factor, 0.0, 1.0)
            self.update()

    def mouseReleaseEvent(self, event):
        # if it was a short click (almost no movement) - treat as frequency selection
        self._dragging = False
        if self._press_x is not None:
            dx = abs(event.x() - self._press_x)
            dy = abs(event.y() - self._press_y)
            if dx < 4 and dy < 4:  # threshold for click
                freq = int(self._x_to_freq(event.x()))
                self.selected_freq = freq
                self.freq_clicked.emit(freq)
                self.update()
        self._press_x = None
        self._press_y = None

    def _visible_freq_range(self):
        """Returns (visible_start_freq, visible_end_freq) based on samp_rate, center_freq, zoom_factor and center_pos."""
        full_start = self.center_freq - (self.samp_rate / 2.0)
        full_bw = self.samp_rate
        vis_bw = full_bw * self.zoom_factor
        # center_pos specifies center view position relative to full band [0..1]
        center_abs = full_start + self.center_pos * full_bw
        vis_start = center_abs - vis_bw / 2.0
        vis_end = vis_start + vis_bw
        # boundary protection: keep within full band
        if vis_start < full_start:
            vis_start = full_start
            vis_end = vis_start + vis_bw
        if vis_end > full_start + full_bw:
            vis_end = full_start + full_bw
            vis_start = vis_end - vis_bw
        return vis_start, vis_end

    @QtCore.pyqtSlot(np.ndarray)
    def push_row(self, fft_row):
        # FPS limiting — drop frames if too fast
        now = self._time.time()
        if now - self._last_frame_time < self._min_frame_interval:
            return
        self._last_frame_time = now

        # zoom: select slice
        n = len(fft_row)
        self.fft_avg = np.mean(fft_row)
        visible_n = max(2, int(n * self.zoom_factor))
        center = int(self.center_pos * n)
        start = max(0, center - visible_n // 2)
        end = min(n, start + visible_n)
        if end - start < visible_n:
            start = max(0, end - visible_n)
        fft_visible = fft_row[start:end]

        # scale to widget width
        if fft_visible.size != self.width_px:
            x_old = np.arange(len(fft_visible))
            x_new = np.linspace(0, len(fft_visible) - 1, self.width_px)
            fft_visible = np.interp(x_new, x_old, fft_visible)

        rgb_row = draw_line(fft_visible, self.palette, self.min_db, self.max_db)

        with self._lock:
            # scroll buffer down by one row (only waterfall area)
            self._buffer[1+WATERFALL_MARGIN:] = self._buffer[WATERFALL_MARGIN:-1]
            self._buffer[WATERFALL_MARGIN] = rgb_row

            # copy to QImage
            ptr = self._image.bits()
            ptr.setsize(self._image.byteCount())
            bytes_per_line = self._image.bytesPerLine()
            arr2d = np.frombuffer(ptr, dtype=np.uint8).reshape((self.height_px, bytes_per_line))
            rgb_view = arr2d[:, :self.width_px * 3].reshape((self.height_px, self.width_px, 3))
            rgb_view[:, :] = self._buffer[:, :]

        # request redraw
        self.update()

    def _format_freq(self, hz):
        # frequency formatting -> Hz, kHz, MHz
        if abs(hz) >= 1e6:
            return f"{hz/1e6:.2f} MHz"
        if abs(hz) >= 1e3:
            return f"{hz/1e3:.1f} kHz"
        return f"{int(hz)} Hz"

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        # draw image
        with self._lock:
            painter.drawImage(self.rect(), self._image, self._image.rect())

            # --- drawing frequency scale (labels every 0.1 MHz + intermediate ticks)
            vis_start, vis_end = self._visible_freq_range()
            bw = vis_end - vis_start

            painter.setPen(QtGui.QPen(QtGui.QColor("#ffd000"), 1))
            font = painter.font()
            font.setPointSize(10)
            painter.setFont(font)
            metrics = painter.fontMetrics()

            # major ticks every 0.1 MHz
            start_mhz = vis_start / 1e6
            end_mhz = vis_end / 1e6
            start_tick = np.floor(start_mhz * 10) / 10
            end_tick = np.ceil(end_mhz * 10) / 10
            inv_bw = 1.0 / bw if bw > 0 else 0
            w_minus_1 = self.width_px - 1

            tick = start_tick
            while tick <= end_tick + 1e-9:
                freq_hz = tick * 1e6
                if vis_start <= freq_hz <= vis_end:
                    x = int((freq_hz - vis_start) * inv_bw * w_minus_1)
                    # major tick + label
                    painter.drawLine(x, WATERFALL_MARGIN - MAJOR_THICK_HEIGHT, x, WATERFALL_MARGIN)
                    text = f"{tick:.2f}"
                    tw = metrics.horizontalAdvance(text)
                    tx = max(2, x - tw // 2)
                    painter.drawText(tx, 16, text)

                    # intermediate ticks
                    if MINOR_TICKS_PER_MAJOR > 0:
                        step = 0.1 / MINOR_TICKS_PER_MAJOR
                        for i in range(1, MINOR_TICKS_PER_MAJOR):
                            sub_tick = tick + i * step
                            sub_freq_hz = sub_tick * 1e6
                            if sub_freq_hz >= vis_end:
                                break
                            x_sub = int((sub_freq_hz - vis_start) * inv_bw * w_minus_1)
                            painter.drawLine(x_sub, WATERFALL_MARGIN - MINOR_TICK_HEIGHT, x_sub, WATERFALL_MARGIN)
                tick += 0.05


            # draw frame and current min/max dB values in corner
            overlay_y = self.height_px - 92
            painter.setPen(QtGui.QPen(QtGui.QColor(180,180,180), 1))
            # painter.drawRect(0, 0, self.width_px-1, self.height_px-1)

            # min/max dB | hover freq overlay
            painter.fillRect(4, overlay_y + 22, 120, 52, QtGui.QColor(60,60,60,150))
            painter.setPen(QtGui.QPen(QtGui.QColor(255,255,255), 1))
            painter.drawText(8, overlay_y + 38, f"Min dB: {self.min_db:.0f}")
            painter.drawText(8, overlay_y + 54, f"Max dB: {self.max_db:.0f}")
            painter.drawText(8, overlay_y + 54 + 16, f"{self.hover_freq/1000000:.3f}")

            # --- drawing green bands for amateur bands
            for name, f_start, f_end in HAM_BANDS:
                # if band is visible at all in current range
                if f_end < vis_start or f_start > vis_end:
                    continue

                # calculate visible fragment
                start_clamped = max(f_start, vis_start)
                end_clamped = min(f_end, vis_end)

                # convert to pixels
                x1 = int((start_clamped - vis_start) / bw * (self.width_px - 1))
                x2 = int((end_clamped - vis_start) / bw * (self.width_px - 1))

                # width (min 2px to be visible even when zoomed)
                w = max(2, x2 - x1)

                # semi-transparent green band
                painter.fillRect(x1, WATERFALL_MARGIN - 10, w, 10, QtGui.QColor(0, 200, 0, 90))

                # band label (if it fits)
                text = name
                tw = metrics.horizontalAdvance(text)
                if w > tw + 4:
                    painter.setPen(QtGui.QPen(QtGui.QColor(150, 255, 150), 1))
                    painter.drawText(x1 + (w - tw) // 2, WATERFALL_MARGIN - 2, text)

            if self.hover_freq is not None:
                if vis_start <= self.hover_freq <= vis_end:
                    x_h = int((self.hover_freq - vis_start) / bw * (self.width_px - 1))
                    pen_h = QtGui.QPen(QtGui.QColor(150, 255, 150, 255), 2)   # cyan
                    painter.setPen(pen_h)
                    painter.drawLine(x_h, 0, x_h, self.height_px)
                    painter.drawText(x_h, self.height_px - 16, f"{self.hover_freq/1000000:.4f}")

            # --- drawing vertical lines: selected (yellow) and hover (cyan)
            # freq -> x mapping
            vis_start, vis_end = self._visible_freq_range()
            bw = max(1e-9, (vis_end - vis_start))
            if self.selected_freq is not None:
                if vis_start <= self.selected_freq <= vis_end:
                    x_sel = int((self.selected_freq - vis_start) / bw * (self.width_px - 1))
                    pen_sel = QtGui.QPen(QtGui.QColor(255, 255, 0, 220), 2)  # yellow
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

            # --- drawing bookmarks (cyan dots on top of scale) ---
            if self.bookmarks:
                BM_DOT_RADIUS = 3
                BM_DOT_Y = WATERFALL_MARGIN - 7
                for bm in self.bookmarks:
                    f = bm['freq_hz']
                    if vis_start <= f <= vis_end:
                        x_bm = int((f - vis_start) / bw * (self.width_px - 1))
                        painter.setPen(QtCore.Qt.NoPen)
                        painter.setBrush(QtGui.QColor(0, 200, 255, 220))
                        painter.drawEllipse(x_bm - BM_DOT_RADIUS, BM_DOT_Y - BM_DOT_RADIUS, BM_DOT_RADIUS * 2, BM_DOT_RADIUS * 2)

                # tooltip for hovered bookmark
                if self._hovered_bookmark is not None:
                    hb = self._hovered_bookmark
                    f = hb['freq_hz']
                    if vis_start <= f <= vis_end:
                        x_bm = int((f - vis_start) / bw * (self.width_px - 1))
                        tip_font = painter.font()
                        tip_font.setPointSize(9)
                        tip_font.setBold(True)
                        painter.setFont(tip_font)
                        tip_metrics = painter.fontMetrics()
                        name = hb.get('name', '')
                        tip_text = f"{name}  {f/1e6:.4f} {hb.get('mode', '')}" if name else f"{f/1e6:.4f} {hb.get('mode', '')}"
                        tw = tip_metrics.horizontalAdvance(tip_text)
                        th = tip_metrics.height()
                        tx = max(2, min(x_bm - tw // 2, self.width_px - tw - 4))
                        ty = 12
                        painter.fillRect(tx - 3, ty - 1, tw + 6, th + 4, QtGui.QColor(30, 30, 30, 140))
                        painter.setPen(QtGui.QPen(QtGui.QColor(100, 220, 255, 140), 1))
                        painter.drawRect(tx - 3, ty - 1, tw + 6, th + 4)
                        painter.setPen(QtGui.QPen(QtGui.QColor(150, 240, 255, 200), 1))
                        painter.drawText(tx, ty + th - 2, tip_text)
                        tip_font.setBold(False)
                        tip_font.setPointSize(10)
                        painter.setFont(tip_font)

                painter.setBrush(QtCore.Qt.NoBrush)

            # --- drawing DX Cluster spots (dots on scale + tooltip on hover) ---
            if self.dx_cluster_enabled and self.dx_spots:
                DOT_RADIUS = 3
                DOT_Y = WATERFALL_MARGIN - 3
                for spot in self.dx_spots:
                    f = spot['freq_hz']
                    if vis_start <= f <= vis_end:
                        x_spot = int((f - vis_start) / bw * (self.width_px - 1))
                        # orange dot on scale
                        painter.setPen(QtCore.Qt.NoPen)
                        painter.setBrush(QtGui.QColor(255, 140, 0, 220))
                        painter.drawEllipse(x_spot - DOT_RADIUS, DOT_Y - DOT_RADIUS, DOT_RADIUS * 2, DOT_RADIUS * 2)

                # tooltip for hovered spot
                if self._hovered_spot is not None:
                    hs = self._hovered_spot
                    f = hs['freq_hz']
                    if vis_start <= f <= vis_end:
                        x_spot = int((f - vis_start) / bw * (self.width_px - 1))
                        tip_font = painter.font()
                        tip_font.setPointSize(9)
                        tip_font.setBold(True)
                        painter.setFont(tip_font)
                        tip_metrics = painter.fontMetrics()
                        tip_text = f"{hs['call']}" # {f/1e3:.1f}
                        tw = tip_metrics.horizontalAdvance(tip_text)
                        th = tip_metrics.height()
                        tx = max(2, min(x_spot - tw // 2, self.width_px - tw - 4))
                        ty = WATERFALL_MARGIN - 23
                        painter.fillRect(tx - 3, ty - 1, tw + 6, th + 4, QtGui.QColor(30, 30, 30, 140))
                        painter.setPen(QtGui.QPen(QtGui.QColor(255, 200, 80, 140), 1))
                        painter.drawRect(tx - 3, ty - 1, tw + 6, th + 4)
                        painter.setPen(QtGui.QPen(QtGui.QColor(255, 220, 100, 200), 1))
                        painter.drawText(tx, ty + th - 2, tip_text)
                        # restore font
                        tip_font.setBold(False)
                        tip_font.setPointSize(10)
                        painter.setFont(tip_font)

                painter.setBrush(QtCore.Qt.NoBrush)

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
            print('Changing SDR frequency to ' + str(frequency))
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
            if self._stop_event.is_set():
                return
            if isinstance(message, str):
                try:
                    json_msg = json.loads(message)
                except Exception:
                    return
                # if this is a config message -> emit
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
                        # emit configuration to UI
                        self.config_signal.emit(cfg)
                return

            data = message
            if len(data) < COMPRESS_FFT_PAD_N:
                return
            frame_type = data[0]
            if frame_type == 1:
                # if len(payload) == self.fft_size:
                    # decoding (assume waterfall_i16 -> dB style)
                self.fft_codec.reset()
                waterfall_i16 = self.fft_codec.decode(data)
                waterfall_f32 = waterfall_i16[COMPRESS_FFT_PAD_N:].astype(np.float32) / 100.0
                if not self._stop_event.is_set():
                    self.push_row_signal.emit(waterfall_f32)

        def on_error(ws, error):
            if not self._stop_event.is_set():
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

### --- DX Cluster Client --- ###
class DxClusterClient(threading.Thread, QtCore.QObject):
    """Telnet client for DX Cluster - receives and parses spot data."""
    spots_updated = QtCore.pyqtSignal(list)  # emits list of {freq_hz, call, spotter, time_str}
    status_changed = QtCore.pyqtSignal(str)  # 'connected', 'disconnected', 'connecting'

    # Regex for standard real-time DX spot format:
    # DX de SP9PHO:     14025.0  W1AW         CQ CQ              1234Z
    SPOT_RE = re.compile(
        r'DX\s+de\s+(\S+):\s*([\d.]+)\s+(\S+)\s+(.*?)\s+(\d{4})Z',
        re.IGNORECASE
    )

    # Regex for SH/DX history format (no "DX de" prefix):
    # 14153.0  IT9AAK/P  27-Mar-2026 1423Z  CQ  <W3LPL>
    SHDX_RE = re.compile(
        r'^\s*([\d]{3,6}\.[\d]{1,2})\s+([A-Z0-9/]+)\s+(.+)',
        re.IGNORECASE
    )

    MAX_SPOTS = 200  # max spots to keep in memory
    SPOT_MAX_AGE = 1800  # seconds (30 min) - spots older than this are removed

    def __init__(self, server, port, callsign, backup_servers_str=''):
        threading.Thread.__init__(self, daemon=True)
        QtCore.QObject.__init__(self)
        self.server = server
        self.port = port
        self.callsign = callsign
        self.backup_servers = []
        if backup_servers_str:
            for entry in backup_servers_str.split(','):
                entry = entry.strip()
                if ':' in entry:
                    h, p = entry.rsplit(':', 1)
                    try:
                        self.backup_servers.append((h.strip(), int(p)))
                    except ValueError:
                        pass
                else:
                    self.backup_servers.append((entry, 23))
        self._stop_event = threading.Event()
        self._spots = []  # list of dicts: {freq_hz, call, spotter, time_str, timestamp}
        self._lock = threading.Lock()
        import time as _time
        self._time = _time

    def stop(self):
        self._stop_event.set()

    def get_spots(self):
        """Returns a copy of current spots list (thread safe)."""
        with self._lock:
            return list(self._spots)

    def _add_spot(self, spotter, freq_khz, call, comment, time_str):
        import time as _time
        freq_hz = int(float(freq_khz) * 1000)
        spot = {
            'freq_hz': freq_hz,
            'call': call.strip(),
            'spotter': spotter.strip().rstrip(':'),
            'time_str': time_str.strip(),
            'comment': comment.strip(),
            'timestamp': _time.time()
        }
        with self._lock:
            # Remove old duplicate (same call on similar freq)
            self._spots = [
                s for s in self._spots
                if not (s['call'] == spot['call'] and abs(s['freq_hz'] - spot['freq_hz']) < 500)
            ]
            self._spots.append(spot)
            # Remove expired spots
            now = _time.time()
            self._spots = [
                s for s in self._spots
                if now - s['timestamp'] < self.SPOT_MAX_AGE
            ]
            # Trim to MAX_SPOTS
            if len(self._spots) > self.MAX_SPOTS:
                self._spots = self._spots[-self.MAX_SPOTS:]
            spots_copy = list(self._spots)
        self.spots_updated.emit(spots_copy)

    def _try_connect(self, host, port):
        """Attempt to connect to a DX cluster server. Returns socket or None."""
        try:
            sock = socket.create_connection((host, port), timeout=10)
            sock.settimeout(30)
            return sock
        except Exception as e:
            print(f"DX Cluster: failed to connect to {host}:{port} - {e}")
            return None

    def run(self):
        import time as _time
        servers = [(self.server, self.port)] + self.backup_servers

        while not self._stop_event.is_set():
            sock = None
            for host, port in servers:
                if self._stop_event.is_set():
                    return
                print(f"DX Cluster: connecting to {host}:{port}...")
                self.status_changed.emit('connecting')
                sock = self._try_connect(host, port)
                if sock:
                    print(f"DX Cluster: connected to {host}:{port}")
                    break

            if not sock:
                print("DX Cluster: all servers failed, retrying in 30s...")
                self.status_changed.emit('disconnected')
                self._stop_event.wait(30)
                continue

            try:
                buf = b''
                login_sent = False
                while not self._stop_event.is_set():
                    try:
                        data = sock.recv(4096)
                    except socket.timeout:
                        continue
                    except Exception:
                        break
                    if not data:
                        break
                    buf += data
                    while b'\n' in buf:
                        line, buf = buf.split(b'\n', 1)
                        line_str = line.decode('latin-1', errors='replace').strip()
                        if not line_str:
                            continue
                        print(f"DX< {line_str}")
                        # Send callsign on login prompt
                        if not login_sent and ('login' in line_str.lower() or 'call' in line_str.lower() or 'enter' in line_str.lower()):
                            sock.sendall((self.callsign + '\r\n').encode('ascii'))
                            login_sent = True
                            print(f"DX Cluster: logged in as {self.callsign}")
                            self.status_changed.emit('connected')
                            # Request last 50 spots
                            import time as _t; _t.sleep(1)
                            sock.sendall(b'SH/DX 50\r\n')
                            continue
                        # Parse DX spot (real-time format)
                        m = self.SPOT_RE.search(line_str)
                        if m:
                            spotter, freq_khz, call, comment, time_str = m.groups()
                            print(f"DX SPOT: {call} on {freq_khz} kHz by {spotter}")
                            self._add_spot(spotter, freq_khz, call, comment, time_str)
                            continue
                        # Parse SH/DX history format
                        m2 = self.SHDX_RE.search(line_str)
                        if m2:
                            freq_khz, call, rest = m2.groups()
                            print(f"DX HIST: {call} on {freq_khz} kHz | {rest.strip()}")
                            self._add_spot('', freq_khz, call, rest.strip(), '')
            except Exception as e:
                print(f"DX Cluster: connection error - {e}")
            finally:
                try:
                    sock.close()
                except Exception:
                    pass
                self.status_changed.emit('disconnected')
            if not self._stop_event.is_set():
                print("DX Cluster: reconnecting in 5s...")
                self._stop_event.wait(5)


class AudioStateSignaler(QtCore.QObject):
    """Helper do przekazywania stanu audio z wątku do Qt UI."""
    status_changed = QtCore.pyqtSignal(str)


class MainWindow(QtWidgets.QMainWindow):
    audio_status_changed = QtCore.pyqtSignal(str)
    send_tx_signal = QtCore.pyqtSignal(int)
    send_fst_signal = QtCore.pyqtSignal(int)
    pause_polling = QtCore.pyqtSignal(int)
    resume_polling = QtCore.pyqtSignal()
    sound_finished = QtCore.pyqtSignal(object)
    waterfall_freq_update = QtCore.pyqtSignal(int, int, str)
    fast_freq_status = QtCore.pyqtSignal(bool)
    adjust_waterfall_colors = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Remote Radio Control")

        sizeObject = QtWidgets.QDesktopWidget().availableGeometry(-1)
        windowWidth = int(WINDOW_WIDTH_PERCENTAGE / 100 * sizeObject.width())
        windowWidth = int(sizeObject.width())
        windowHeight = int(WINDOW_HEIGHT_PERCENTAGE / 100 * sizeObject.height())
        if WATERFALL_ENABLED:
            windowHeight = 400
        else:
            windowHeight = 200

        self.setGeometry(0, sizeObject.height() - windowHeight - 48, windowWidth, windowHeight)

        # Stay on top based on config
        if config.get('stay_on_top', False):
            self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
        
        self.setWindowIcon(QIcon("logo.ico"))

        # self.setWindowOpacity(0.8)

        self.ignore_next_data_switch = False
        self.ignore_next_data_cnt = 3

        self.tx_active = 0
        self.tx_sent = 0
        self._audio_thread = None
        self._audio_stop_event = None

        self.filter_width = FILTER_WIDTH_USB_NORMAL
        self.current_freq = 14074000  # Hz (read from rigctld)
        self.vfoa_freq = self.current_freq
        self.vfob_freq = self.current_freq
        self.vfoa_mode = 'USB'
        self.vfob_mode = 'USB'
        self.vfoa_width = FILTER_WIDTH_USB_NORMAL
        self.vfob_width = FILTER_WIDTH_USB_NORMAL
        self.mode = 'USB'

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

        # Radio mode
        self.mode_labels = {}
        self.modes_layout = QtWidgets.QVBoxLayout()
        self.modes_layout.addSpacing(8)
        for mode in radioModes:
            label = QtWidgets.QLabel(mode)
            label.setAlignment(QtCore.Qt.AlignCenter)
            label.setFont(QtGui.QFont("Monospace", 8))
            label.setFixedHeight(16)
            self.modes_layout.setSpacing(0)        # spacing between elements
            self.modes_layout.setContentsMargins(0, 0, 0, 0)   # layout margins
            # save to dictionary
            self.mode_labels[mode] = label
            # add to layout
            self.modes_layout.addWidget(label)
        self.modes_layout.addSpacing(8)

        self.modes_widget = QtWidgets.QWidget()
        self.modes_widget.setLayout(self.modes_layout)
        self.update_mode_display()

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
        self.tx_power_btn.clicked.connect(self.set_tx_power)

        # main frequency
        self.freq_display = ClickableLabel("--- MHz")
        self.freq_display.setFont(ACTIVE_VFO_FONT)
        self.freq_display.setAlignment(QtCore.Qt.AlignCenter)
        self.freq_display.clicked.connect(self.open_frequency_dialog)
        self.set_frequency_label(self.freq_display, 0)

        # second, smaller frequency
        self.freq_display_sub = ClickableLabel("--- kHz")
        self.freq_display_sub.setFont(SECOND_VFO_FONT)
        self.freq_display_sub.setAlignment(QtCore.Qt.AlignCenter)
        self.freq_display_sub.clicked.connect(self.open_frequency_dialog)

        # vertical layout for both frequencies
        freq_layout = QtWidgets.QVBoxLayout()
        freq_layout.addWidget(QtWidgets.QLabel('VFOA:'))
        freq_layout.addWidget(self.freq_display)
        freq_layout.addWidget(QtWidgets.QLabel('VFOB:'))
        freq_layout.addWidget(self.freq_display_sub)

        # to keep them nicely together in center
        freq_widget = QtWidgets.QWidget()
        freq_widget.setLayout(freq_layout)
        freq_widget.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; border-radius: 8px;")

        right_container = QtWidgets.QWidget()
        right_grid = QtWidgets.QGridLayout()
        right_grid.setHorizontalSpacing(6)
        right_grid.setVerticalSpacing(4)
        right_grid.setContentsMargins(0, 0, 0, 0)
        right_container.setLayout(right_grid)

        # first (existing) button line
        right_grid.addWidget(self.att_btn,       0, 0)
        right_grid.addWidget(self.ipo_btn,       0, 1)
        right_grid.addWidget(self.tx_power_btn,  0, 2)

        # second line - for now only NB under first button
        self.nb_btn = QtWidgets.QPushButton("NB")
        self.nb_btn.setFixedSize(SMALL_BTN_WIDTH, SMALL_BTN_HEIGHT)
        self.nb_btn.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
        # self.nb_btn.setFont(QtGui.QFont("Monospace", 7))
        self.nb_btn.clicked.connect(self.nb_btn_clicked)
        self.nb_active = 0
        self.att_val = 0
        self.ipo_val = 0

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
        self.swr_btn.setStyleSheet("background-color: " + "#e6bb4f" + "; text-align: center; border-radius: 4px; border: 1px solid black;")
        self.swr_btn.pressed.connect(self.swr_btn_pressed)
        self.swr_btn.released.connect(self.swr_btn_released)

        right_grid.addWidget(self.swr_btn, 2, 0)

        self.miceq_btn = QtWidgets.QPushButton("MIC EQ")
        self.miceq_btn.setFixedSize(SMALL_BTN_WIDTH, SMALL_BTN_HEIGHT)
        self.miceq_btn.setStyleSheet("background-color: " + "#e6bb4f" + "; text-align: center; border-radius: 4px; border: 1px solid black;")
        self.miceq_btn.pressed.connect(self.miceq_btn_btn_pressed)

        right_grid.addWidget(self.miceq_btn, 2, 1)

        # --- GROUP WITH FREQ CTRL BUTTONS ---
        self.group_freq_ctrl = QtWidgets.QGroupBox("Freq Ctrl")
        self.group_freq_ctrl.setObjectName("groupFreqCtrl")

        # if you want the frame to have fixed size (optional)
        # self.group_freq_ctrl.setFixedSize(80, 80)
        # self.group_freq_ctrl.setContentsMargins(12,0,12,0)

        # buttons (as you already have defined, just use these objects)
        self.btn_freq_plus_slow = QtWidgets.QPushButton("+")
        self.btn_freq_plus_fast = QtWidgets.QPushButton("+\n+")
        self.btn_freq_minus_slow = QtWidgets.QPushButton("-")
        self.btn_freq_minus_fast = QtWidgets.QPushButton("-\n-")

        self.radio_fast_freq = QtWidgets.QCheckBox("Fast Scroll")
        self.radio_fast_freq.clicked.connect(self.radio_fast_freq_clicked)

        # set sizes and stretch policy (important)
        for btn in [self.btn_freq_plus_slow, self.btn_freq_plus_fast,
                    self.btn_freq_minus_slow, self.btn_freq_minus_fast]:
            btn.setFixedSize(32, 32)
            btn.setFont(QtGui.QFont("Monospace", 8, QtGui.QFont.Bold))
            btn.setStyleSheet(
                "background-color: " + NOT_ACTIVE_COLOR +
                "; text-align: center; border-radius: 8px; border: 1px solid black; margin: 0px; padding: 0px;"
            )
            btn.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

        # connections
        self.btn_freq_plus_slow.clicked.connect(lambda: self.frequency_step(+1, FREQ_STEP_SLOW))
        self.btn_freq_plus_fast.clicked.connect(lambda: self.frequency_step(+1, FREQ_STEP_FAST))
        self.btn_freq_minus_slow.clicked.connect(lambda: self.frequency_step(-1, FREQ_STEP_SLOW))
        self.btn_freq_minus_fast.clicked.connect(lambda: self.frequency_step(-1, FREQ_STEP_FAST))

        # 2x2 grid for buttons
        freq_grid = QtWidgets.QGridLayout()
        freq_grid.setVerticalSpacing(8)    # vertical spacing between rows (bring them closer)
        freq_grid.setHorizontalSpacing(8)  # spacing between columns
        freq_grid.setContentsMargins(0, 0, 0, 0)

        freq_grid.addWidget(self.btn_freq_plus_slow, 0, 0, QtCore.Qt.AlignCenter)
        freq_grid.addWidget(self.btn_freq_plus_fast, 0, 1, QtCore.Qt.AlignCenter)
        freq_grid.addWidget(self.btn_freq_minus_slow, 1, 0, QtCore.Qt.AlignCenter)
        freq_grid.addWidget(self.btn_freq_minus_fast, 1, 1, QtCore.Qt.AlignCenter)

        # main group layout: use stretches to center grid vertically
        group_layout = QtWidgets.QVBoxLayout()
        # group_layout.setContentsMargins(4, 20, 4, 8)
        group_layout.setSpacing(0)
        group_layout.addStretch(1)                  # takes space above grid
        group_layout.addLayout(freq_grid)          # button grid -> will be centered
        group_layout.addSpacing(8)                  # takes space below grid
        group_layout.addWidget(self.radio_fast_freq)
        group_layout.addStretch(1)                  # takes space below grid

        self.group_freq_ctrl.setLayout(group_layout)

        # add group to main layout (where you want)
        # main_layout.addWidget(self.group_freq_ctrl)

        self.last_squelch_pos = 0
        self.last_volume_pos = 0

        self.volume_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Vertical)
        self.volume_slider.setFixedHeight(DSP_SLIDER_HEIGHT)
        self.volume_slider.setMinimum(0)
        self.volume_slider.setMaximum(100)
        self.volume_slider.setSingleStep(1)
        self.volume_slider.setPageStep(1)
        self.volume_slider.setTickInterval(10)
        self.volume_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.volume_slider.valueChanged.connect(self.volume_change)

        self.volume_group = QtWidgets.QGroupBox("Vol[99]")
        volume_layout = QtWidgets.QVBoxLayout(self.volume_group)
        volume_layout.addWidget(self.volume_slider)

        self.squelch_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Vertical)
        self.squelch_slider.setFixedHeight(DSP_SLIDER_HEIGHT)
        self.squelch_slider.setMinimum(0)
        self.squelch_slider.setMaximum(100)
        self.squelch_slider.setSingleStep(1)
        self.squelch_slider.setPageStep(1)
        self.squelch_slider.setTickInterval(10)
        self.squelch_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.squelch_slider.valueChanged.connect(self.squelch_change)

        self.squelch_group = QtWidgets.QGroupBox("Sql[99]")
        squelch_layout = QtWidgets.QVBoxLayout(self.squelch_group)
        squelch_layout.addWidget(self.squelch_slider)

        knobs_row = QtWidgets.QHBoxLayout()
        knobs_row.addWidget(self.squelch_group)
        knobs_row.addWidget(self.volume_group)

        # ---- bottom buttons: now in 2 rows
        btns_layout = QtWidgets.QVBoxLayout()
        self.buttons = []

        # first row
        btn_row1 = QtWidgets.QHBoxLayout()

        # second row
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
        self.swr_meter.hide()  # Hide on start, will swap with S-METER during TX

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

        # Vertical layout inside frame
        antenna_layout = QtWidgets.QVBoxLayout(antenna_group)

        # Radio buttons
        self.antenna_1 = QtWidgets.QRadioButton(ANTENNA_1_NAME)
        self.antenna_2 = QtWidgets.QRadioButton(ANTENNA_2_NAME)
        self.antenna_3 = QtWidgets.QRadioButton(ANTENNA_3_NAME)

        # Default selection
        # self.antenna_1.setChecked(True)
        if ANTENNA_SWITCH_ENABLED:
            self.get_current_antenna()

        # Add buttons to vertical layout
        antenna_layout.addWidget(self.antenna_1)
        antenna_layout.addWidget(self.antenna_2)
        antenna_layout.addWidget(self.antenna_3)

        # Button group (single choice)
        self.antenna_switch_group = QtWidgets.QButtonGroup(self)
        self.antenna_switch_group.addButton(self.antenna_1)
        self.antenna_switch_group.addButton(self.antenna_2)
        self.antenna_switch_group.addButton(self.antenna_3)

        # Call function after selection change
        self.antenna_switch_group.buttonClicked.connect(self.antenna_switch_changed)

        bottom_row = QtWidgets.QHBoxLayout()
        bottom_row.addStretch()
        bottom_row.addWidget(self.filter_width_group)
        bottom_row.addStretch()
        if ANTENNA_SWITCH_ENABLED:
            bottom_row.addWidget(antenna_group)
        bottom_row.addStretch()

        # --- Horizontal layout for three vertical sliders
        dsp_layout = QtWidgets.QHBoxLayout()

        # --- Shift slider (vertical)
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

        # --- Notch slider (vertical)
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

        # --- Noise Reduction slider (vertical)
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

        # --- add all subgroups to horizontal layout
        dsp_layout.addWidget(shift_group)
        dsp_layout.addWidget(self.notch_group)
        dsp_layout.addWidget(self.nr_group)

        # playback button
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

        # --- adding to bottom_row_2
        bottom_row_2 = QtWidgets.QHBoxLayout()
        bottom_row_2.addLayout(dsp_layout)

        # top row
        top_row = QtWidgets.QHBoxLayout()
        top_row.addStretch()
        top_row.addWidget(right_container)
        top_row.addStretch()
        top_row.addLayout(knobs_row)
        top_row.addStretch()
        top_row.addWidget(self.group_freq_ctrl)
        top_row.addStretch()
        top_row.addWidget(freq_widget)
        top_row.addStretch()
        top_row.addLayout(btns_layout)
        top_row.addWidget(self.modes_widget)
        top_row.addStretch()
        top_row.addWidget(self.ptt_btn)
        top_row.addStretch()
        top_row.addLayout(bottom_row)
        top_row.addLayout(bottom_row_2)
        if PLAYER_ACTIVE:
            top_row.addWidget(self.player_group)
        top_row.addStretch()
        
        # Settings + Audio buttons stacked vertically
        right_btns_col = QtWidgets.QVBoxLayout()
        right_btns_col.setSpacing(2)

        self.settings_btn = QtWidgets.QPushButton("Settings")
        self.settings_btn.setFixedSize(NORMAL_BTN_WIDTH, NORMAL_BTN_HEIGHT)
        self.settings_btn.setStyleSheet("background-color: #d0d0d0; text-align: center; border-radius: 4px; border: 1px solid black;")
        self.settings_btn.clicked.connect(self.open_settings)

        self.audio_btn = QtWidgets.QPushButton("▶ Audio")
        self.audio_btn.setFixedSize(NORMAL_BTN_WIDTH, NORMAL_BTN_HEIGHT)
        self.audio_btn.setStyleSheet("background-color: #d0d0d0; text-align: center; border-radius: 4px; border: 1px solid black;")
        self.audio_btn.clicked.connect(self.toggle_audio_client)
        self.audio_status_label = QtWidgets.QLabel("disconnected")
        self.audio_status_label.setStyleSheet("color: gray; font-size: 8pt;")
        self.audio_status_label.setAlignment(QtCore.Qt.AlignCenter)
        self.audio_status_label.setFixedWidth(NORMAL_BTN_WIDTH)
        
        # DX Cluster status indicator
        self.dx_status_label = QtWidgets.QLabel("DX Cluster")
        self.dx_status_label.setAlignment(QtCore.Qt.AlignCenter)
        self.dx_status_label.setFixedWidth(NORMAL_BTN_WIDTH)
        self.dx_status_label.setStyleSheet("color: gray; font-size: 8pt;")
        self.dx_status_indicator = QtWidgets.QLabel("●")
        self.dx_status_indicator.setAlignment(QtCore.Qt.AlignCenter)
        self.dx_status_indicator.setFixedWidth(NORMAL_BTN_WIDTH)
        self._update_dx_status('disconnected')

        right_btns_col.addStretch()
        right_btns_col.addWidget(self.settings_btn)

        self.bookmarks_btn = QtWidgets.QPushButton("Memory")
        self.bookmarks_btn.setFixedSize(NORMAL_BTN_WIDTH, NORMAL_BTN_HEIGHT)
        self.bookmarks_btn.setStyleSheet("background-color: #d0d0d0; text-align: center; border-radius: 4px; border: 1px solid black;")
        self.bookmarks_btn.clicked.connect(self.open_bookmarks)

        self.save_bookmark_btn = QtWidgets.QPushButton("Mem+")
        self.save_bookmark_btn.setFixedSize(NORMAL_BTN_WIDTH, NORMAL_BTN_HEIGHT)
        self.save_bookmark_btn.setStyleSheet("background-color: #d0d0d0; text-align: center; border-radius: 4px; border: 1px solid black;")
        self.save_bookmark_btn.clicked.connect(self.save_bookmark)

        right_btns_col.addWidget(self.bookmarks_btn)
        right_btns_col.addWidget(self.save_bookmark_btn)
        right_btns_col.addStretch()
        right_btns_col.addWidget(self.dx_status_label)
        right_btns_col.addWidget(self.dx_status_indicator)
        right_btns_col.addStretch()
        self.audio_status_changed.connect(self.on_audio_status)
        top_row.addLayout(right_btns_col)
        top_row.addStretch()

        self.smeter_row = QtWidgets.QHBoxLayout()
        self.smeter_row.addWidget(self.s_meter)
        self.smeter_row.addWidget(self.swr_meter)
        self.smeter_row.addSpacing(20)
        self.smeter_row.addWidget(self.alc_meter)
        self.smeter_row.addSpacing(20)
        self.smeter_row.addWidget(self.po_meter)
        
        # ALC and POWER always visible, SWR hidden (will appear instead of S-METER during TX)

        # --- controls ---
        controls = QtWidgets.QHBoxLayout()

        controls.addWidget(QtWidgets.QLabel("Zoom:"))
        self.zoom_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.zoom_slider.setRange(5, 100)   # 5=oddalony (zoom_factor=1.0) .. 100=przybliżony (zoom_factor=0.05)
        self.zoom_slider.setSingleStep(1)
        self.zoom_slider.setPageStep(5)
        self.zoom_slider.setValue(int(105 - INITIAL_ZOOM * 100))
        self.zoom_slider.valueChanged.connect(self.on_zoom_changed)
        controls.addWidget(self.zoom_slider)
        self.zoom_label = QtWidgets.QLabel(f"{int(105 - INITIAL_ZOOM * 100)}%")
        controls.addWidget(self.zoom_label)

        controls.addSpacing(20)

        self.adjust_waterfall_btn = QtWidgets.QPushButton('Adjust')
        self.adjust_waterfall_btn.setFixedSize(SMALL_BTN_WIDTH, SMALL_BTN_HEIGHT)
        self.adjust_waterfall_btn.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
        self.adjust_waterfall_btn.pressed.connect(self.adjust_waterfall_btn_pressed)
        controls.addWidget(self.adjust_waterfall_btn)

        controls.addSpacing(20)

        controls.addWidget(QtWidgets.QLabel("Min[dB]:"))
        self.min_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.min_slider.setRange(-160, -10)
        self.min_slider.setSingleStep(1)
        self.min_slider.setPageStep(5)
        self.min_slider.setValue(int(self.waterfall_widget.min_db))
        self.min_slider.valueChanged.connect(self.on_min_changed)
        controls.addWidget(self.min_slider)
        self.min_label = QtWidgets.QLabel(f"{int(self.waterfall_widget.min_db)}")
        controls.addWidget(self.min_label)

        controls.addSpacing(20)

        controls.addWidget(QtWidgets.QLabel("Range[dB]:"))
        self.range_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.range_slider.setRange(0, 40)
        self.range_slider.setSingleStep(1)
        self.range_slider.setPageStep(5)
        self.range_slider.setValue(WATERFALL_DYNAMIC_RANGE)
        self.range_slider.valueChanged.connect(self.on_range_changed)
        controls.addWidget(self.range_slider)
        self.range_label = QtWidgets.QLabel(f"{WATERFALL_DYNAMIC_RANGE}")
        controls.addWidget(self.range_label)

        # ---- root layout
        self.root = QtWidgets.QVBoxLayout(central)
        self.root.addLayout(top_row)
        self.root.addLayout(self.smeter_row)
        if WATERFALL_ENABLED:
            self.root.addWidget(self.waterfall_widget, 1)
            self.root.addLayout(controls)
        else:
            self.root.addStretch()

        self.status = self.statusBar()
        self.status.setVisible(False)

        # Read thread
        self.thread = QtCore.QThread()
        self.worker = PollWorker(HOST, PORT, POLL_MS)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.start)
        self.worker.result.connect(self.parse_hamlib_response)
        self.worker.status.connect(self.status.showMessage)
        self.pause_polling.connect(self.worker.pause)
        self.resume_polling.connect(self.worker.resume)
        self.thread.start()

        # Handling sending changes to radio
        self.power_btn.clicked.connect(self.power_btn_clicked)
        self.tuner_status.singleClicked.connect(self.set_tuner)
        self.tuner_status.doubleClicked.connect(self.tuning_start)
        self.send_tx_signal.connect(self.tx_action)
        self.send_tx_signal.connect(self.worker.tx_action)
        self.send_fst_signal.connect(self.fst_action)
        self.sound_finished.connect(self._on_sound_finished)

        # Waterfall
        if WATERFALL_ENABLED:
            self.ws_thread = WsReceiver(WS_URL, fft_size=DEFAULT_FFT_SIZE)
            self.ws_thread.push_row_signal.connect(self.waterfall_widget.push_row)
            self.ws_thread.config_signal.connect(self.waterfall_widget.update_config)
            self.waterfall_widget.samp_rate = self.ws_thread.samp_rate
            self.waterfall_widget.center_freq = self.ws_thread.center_freq
            self.waterfall_widget.freq_clicked.connect(self.on_freq_clicked)
            self.waterfall_widget.new_min_db.connect(self.on_new_min_db)
            self.waterfall_widget.zoom_changed.connect(self.on_zoom_slider_sync)
            self.waterfall_freq_update.connect(self.waterfall_widget.update_selected_freq)
            self.waterfall_freq_update.connect(self.ws_thread.send_set_frequency)
            self.fast_freq_status.connect(self.waterfall_widget.fast_freq_update)
            self.adjust_waterfall_colors.connect(self.waterfall_widget.adjustWaterfallColors)
            self.ws_thread.start()

            # DX Cluster
            if DX_CLUSTER_ENABLED:
                self.dx_cluster = DxClusterClient(
                    DX_CLUSTER_SERVER, DX_CLUSTER_PORT, DX_CLUSTER_CALLSIGN,
                    DX_CLUSTER_BACKUP_SERVERS
                )
                self.dx_cluster.spots_updated.connect(self._on_dx_spots_updated)
                self.dx_cluster.status_changed.connect(self._update_dx_status)
                self.dx_cluster.start()

        self.client = RigctlClient(HOST, PORT, timeout=TCP_TIMEOUT)

        # Load bookmarks
        self._refresh_waterfall_bookmarks()

    @QtCore.pyqtSlot(list)
    def _on_dx_spots_updated(self, spots):
        """Received new DX spots from cluster - update waterfall."""
        if WATERFALL_ENABLED and hasattr(self, 'waterfall_widget'):
            self.waterfall_widget.dx_spots = spots
            self.waterfall_widget.update()

    @QtCore.pyqtSlot(str)
    def _update_dx_status(self, status):
        """Update DX Cluster connection indicator."""
        if status == 'connected':
            self.dx_status_indicator.setText("● connected")
            self.dx_status_indicator.setStyleSheet("color: #4CAF50; font-size: 9pt;")
        elif status == 'connecting':
            self.dx_status_indicator.setText("● connecting...")
            self.dx_status_indicator.setStyleSheet("color: #aa8800; font-size: 9pt;")
        else:
            self.dx_status_indicator.setText("● offline")
            self.dx_status_indicator.setStyleSheet("color: #cc3333; font-size: 9pt;")

    def parse_af_gain(self, val):
        if val is not None:
            val = float(val)
            vol = int(val/1 * 100)
            self.current_vol = vol
            self.volume_slider.setValue(vol)
            self.volume_group.setTitle(f'Vol[{vol}]')

    def parse_sql_lvl(self, val):
        if val is not None:
            val = float(val)
            sql = int(val/1 * 100)
            self.current_sql = sql
            self.squelch_slider.setValue(sql)
            self.squelch_group.setTitle(f'Sql[{sql}]')

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

        db = int(val)

        # --- linear bar fill 0..100 for -60..+60 dB ---
        pct = int((db + 60) / 120 * 100)
        pct = max(0, min(100, pct))

        # --- S labels ---
        # S0 = -60 dB
        # S9 = 0 dB
        # above 0 dB: +10, +20 ... to +60
        if db < 0:
            # Mapowanie -60..0 dB → S0..S9
            s = int((db + 60) / 60 * 9)   # liniowo
            s = max(0, min(9, s))
            label = f"S{s}"
        else:
            # Mapowanie 0..+60 dB → +10..+60 (co 10 dB)
            extra = (db // 10) * 10
            extra = max(10, min(60, extra))
            label = f"+{extra}"

        if not self.tx_active:
            self.s_meter.setRange(0, 100)
            self.s_meter.setValue(pct)
            self.s_meter.setFormat(f"S: {label:>5}")

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
                # Watchdog: radio still reports TX but we already sent T 0
                if self.tx_sent == 0:
                    self._tx_watchdog_cnt = getattr(self, '_tx_watchdog_cnt', 0) + 1
                    if self._tx_watchdog_cnt >= 2:
                        self._tx_watchdog_cnt = 0
                        QTimer.singleShot(0, self.disable_tx)
                else:
                    self._tx_watchdog_cnt = 0
            else:
                self.tx_active = 0
                self._tx_watchdog_cnt = 0
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
        if val is not None:
            val = int(val)
            self.shift_slider.setValue(val)

    def parse_mn(self, val):
        if val is not None:
            val = int(val)
            if val:
                self.notch_group.setChecked(True)
            else:
                self.notch_group.setChecked(False)

    def parse_notchf(self, val):
        if val is not None:
            val = int(val)
            self.notch_slider.setValue(val)

    def parse_u_nr(self, val):
        if val is not None:
            val = int(val)
            if val:
                self.nr_group.setChecked(True)
            else:
                self.nr_group.setChecked(False)

    def parse_l_nr(self, val):
        if val is not None:
            val = float(val)
            val = val * self.nr_slider.maximum()
            val = int(val)
            self.nr_slider.setValue(val)

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

        # get method function from self
        parser_fn = getattr(self, parser_name, None)
        if parser_fn is None:
            print(f"Parser function {parser_name} not found!")
            return

        # call dedicated parser
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

        # get method function from self
        parser_fn = getattr(self, parser_name, None)
        if parser_fn is None:
            print(f"Parser function {parser_name} not found!")
            return

        # call dedicated parser
        parser_fn(param_value)

    def parse_get_func(self, val):
        param = val.split(': ')[1].split('\n')[0]
        param_value = val.split(param + '\n')[1].split('\n')[0]

        parser_name = self.find_parser_for_get_func(param)
        if parser_name is None:
            print(f"No parser available for get_func({param})")
            return

        # get method function from self
        parser_fn = getattr(self, parser_name, None)
        if parser_fn is None:
            print(f"Parser function {parser_name} not found!")
            return

        # call dedicated parser
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

        update_needed = False

        if vfo == 'VFOA':
            self.vfoa_freq = freq
            self.vfoa_mode = mode
            self.vfoa_width = width
        elif vfo == 'VFOB':
            self.vfob_freq = freq
            self.vfob_mode = mode
            self.vfob_width = width

        if self.active_vfo == 0:
            if self.current_freq != self.vfoa_freq:
                update_needed = True
            self.current_freq = self.vfoa_freq
            self.mode = self.vfoa_mode
            self.filter_width = self.vfoa_width
            self.active_vfo_label.setText("VFO A")
            self.set_frequency_label(self.freq_display, self.vfoa_freq)
            self.set_frequency_label(self.freq_display_sub, self.vfob_freq)
            self.freq_display.setFont(ACTIVE_VFO_FONT)
            self.freq_display_sub.setFont(SECOND_VFO_FONT)
        elif self.active_vfo == 1:
            if self.current_freq != self.vfob_freq:
                update_needed = True
            self.current_freq = self.vfob_freq
            self.mode = self.vfob_mode
            self.filter_width = self.vfob_width
            self.active_vfo_label.setText("VFO B")
            self.set_frequency_label(self.freq_display, self.vfoa_freq)
            self.set_frequency_label(self.freq_display_sub, self.vfob_freq)
            self.freq_display.setFont(SECOND_VFO_FONT)
            self.freq_display_sub.setFont(ACTIVE_VFO_FONT)

        self.update_mode_display()

        # Filter width
        try:
            if globals()['FILTER_WIDTH_' + self.mode + '_WIDE'] == self.filter_width:
                if not self.filter_wide.isChecked():
                    self.filter_wide.setChecked(True)
                    update_needed = True
            elif globals()['FILTER_WIDTH_' + self.mode + '_NORMAL'] == self.filter_width:
                if not self.filter_normal.isChecked():
                    self.filter_normal.setChecked(True)
                    update_needed = True
            elif globals()['FILTER_WIDTH_' + self.mode + '_NARROW'] == self.filter_width:
                if not self.filter_narrow.isChecked():
                    self.filter_narrow.setChecked(True)
                    update_needed = True
        except:
            pass

        if update_needed:
            # print('parse_get_vfo_info')
            self.waterfall_freq_update.emit(self.current_freq, self.filter_width, self.mode)

    def parse_get_freq(self, val):
        freq = int(val.split('Frequency: ')[1].split('\n')[0])
        updated_needed = True

        if freq != self.current_freq:
            updated_needed = True
            self.current_freq = freq

        if self.active_vfo == 0:
            self.set_frequency_label(self.freq_display, freq)
            self.freq_display.setFont(ACTIVE_VFO_FONT)
            self.freq_display_sub.setFont(SECOND_VFO_FONT)
        elif self.active_vfo == 1:
            self.set_frequency_label(self.freq_display_sub, freq)
            self.freq_display.setFont(SECOND_VFO_FONT)
            self.freq_display_sub.setFont(ACTIVE_VFO_FONT)

        if updated_needed:
            # print('parse_get_freq')
            self.waterfall_freq_update.emit(freq, self.filter_width, self.mode)

    def parse_get_mode(self, val):
        mode = val.split('get_mode:\nMode: ')[1].split('\n')[0]
        width = int(val.split('\nPassband: ')[1].split('\n')[0])
        updated_needed = False

        if mode != self.mode:
            updated_needed = True
            self.mode = mode
            # print('mode')

        if width != self.filter_width:
            updated_needed = True
            self.filter_width = width
            # print('width')

        self.update_mode_display()

        # Filter width
        try:
            if globals()['FILTER_WIDTH_' + self.mode + '_WIDE'] == self.filter_width:
                if not self.filter_wide.isChecked():
                    self.filter_wide.setChecked(True)
            elif globals()['FILTER_WIDTH_' + self.mode + '_NORMAL'] == self.filter_width:
                if not self.filter_normal.isChecked():
                    self.filter_normal.setChecked(True)
            elif globals()['FILTER_WIDTH_' + self.mode + '_NARROW'] == self.filter_width:
                if not self.filter_narrow.isChecked():
                    self.filter_narrow.setChecked(True)
        except:
            pass

        if updated_needed:
            # print('parse_get_mode')
            self.waterfall_freq_update.emit(self.current_freq, self.filter_width, self.mode)

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
                elif 'get_freq' in resp:
                    self.parse_get_freq(resp)
                elif 'get_mode' in resp:
                    self.parse_get_mode(resp)
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

    def update_mode_display(self):
        for mode, label in self.mode_labels.items():
            # print(self.mode)
            if mode == self.mode:
                label.setStyleSheet(ACTIVE_STYLE)
            else:
                label.setStyleSheet(INACTIVE_STYLE)

    def on_zoom_changed(self, val):
        self.waterfall_widget.zoom_factor = (105 - val) / 100.0
        self.zoom_label.setText(f"{val}%")
        self.waterfall_widget.update()

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

    def on_new_min_db(self, new_min_db: int):
        self.min_slider.setValue(new_min_db)

    def on_zoom_slider_sync(self, val: int):
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(val)
        self.zoom_label.setText(f"{val}%")
        self.zoom_slider.blockSignals(False)

    def ignore_next_data(self, cnt=2):
        self.ignore_next_data_switch = True
        self.ignore_next_data_cnt = cnt

    def shift_slider_move(self, value):
        center = 0
        tolerance = 200  # zakres "magnesu"
        if abs(value - center) <= tolerance:
            self.shift_slider.setValue(center)

        cmd = f"L IF " + str(value)
        self.ignore_next_data()
        self.client.send(cmd)
        self.worker.reset_one_time.emit("l IF")

    def notch_slider_move(self, value):
        cmd = f"L NOTCHF " + str(value)
        self.ignore_next_data()
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
        self.ignore_next_data()
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
        Mapping raw RM0 value (0-255) to S-meter scale.
        Uses calibration table with linear interpolation.
        """
        # table: raw_value : label
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

        # if exact match
        for raw, label in cal_table:
            if val == raw:
                return label

        # interpolation: find interval
        for i in range(len(cal_table)-1):
            raw1, lab1 = cal_table[i]
            raw2, lab2 = cal_table[i+1]
            if raw1 <= val <= raw2:
                return lab1  # for simplicity return lower threshold
                # could also add interpolation e.g. "S6"
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
            self.power_btn.setStyleSheet("border-radius: 14px; background-color: orange; border: 1px solid black;")
            self.pause_polling.emit(3000)
        self.client.send(cmd)
        self.worker.reset_one_time.emit("\\get_powerstat")

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
        self.ignore_next_data(4)
        self.client.send(cmd)
        self.waterfall_widget.initial_zoom_set = False
        QTimer.singleShot(2500, lambda: self.worker.reset_one_time.emit("all"))

    def band_up_btn_clicked(self):
        cmd = f"G BAND_UP"
        self.ignore_next_data(4)
        self.client.send(cmd)
        self.waterfall_widget.initial_zoom_set = False
        QTimer.singleShot(2500, lambda: self.worker.reset_one_time.emit("all"))

    def a_eq_b_btn_clicked(self):
        cmd = f"G CPY"
        self.client.send(cmd)
        self.worker.reset_one_time.emit("all")

    def vfo_switch_btn_clicked(self):
        cmd = f"G XCHG"
        # self.ignore_next_data()
        print('VFO SWITCH')
        self.client.send(cmd)
        self.worker.reset_one_time.emit("all")
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
        current_mode_index = findIndexOfString(self.mode, radioModes)

        if current_mode_index >= len(radioModes) - 1:
            new_mode = 0
        else:
            new_mode = current_mode_index + 1

        cmd = f"M " + radioModes[new_mode] + " 0"
        self.client.send(cmd)

    def mode_up_btn_clicked(self):
        current_mode_index = findIndexOfString(self.mode, radioModes)

        if current_mode_index == 0:
            new_mode = len(radioModes) - 1
        else:
            new_mode = current_mode_index - 1

        cmd = f"M " + radioModes[new_mode] + " 0"
        self.client.send(cmd)

    def radio_fast_freq_clicked(self):
        self.fast_freq_status.emit(self.radio_fast_freq.isChecked())

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
        if self.active_vfo == 0:
            self.set_frequency_label(self.freq_display, freq)
        elif self.active_vfo == 1:
            self.set_frequency_label(self.freq_display_sub, freq)
        self.waterfall_freq_update.emit(freq, self.filter_width, self.mode)
        self.ignore_next_data()
        self.client.send(cmd)

    def volume_change(self, new_pos: int):
        if self.last_volume_pos == 0:
            self.last_volume_pos = new_pos

        delta = new_pos - self.last_volume_pos

        if delta > 50:   # wrap forward
            delta -= 100
        elif delta < -50:  # wrap backward
            delta += 100
        self.last_volume_pos = new_pos
        if delta > 0:
            delta = 1
        elif delta < 0:
            delta = -1

        if delta != 0:
            self.current_vol = self.volume_slider.value()
            self.volume_group.setTitle(f'Vol[{self.current_vol}]')
            cmd = f"L AF {self.current_vol/100:0.3f}"
            self.ignore_next_data()
            self.client.send(cmd)

    def squelch_change(self, new_pos: int):
        if self.last_squelch_pos == 0:
            self.last_squelch_pos = new_pos
        delta = new_pos - self.last_squelch_pos
        if delta > 50:   # wrap forward
            delta -= 100
        elif delta < -50:  # wrap backward
            delta += 100
        self.last_squelch_pos = new_pos
        if delta > 0:
            delta = 1
        elif delta < 0:
            delta = -1

        if delta != 0:
            self.current_sql = self.squelch_slider.value()
            self.squelch_group.setTitle(f'Sql[{self.current_sql}]')
            cmd = f"L SQL {self.current_sql/100:0.3f}"
            self.ignore_next_data()
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
        if not self.client.connected or self.client.s is None:
            self.client = RigctlClient(HOST, PORT)
        resp = self.client.send(cmd)
        if resp is None:
            # Reconnect and retry once
            self.client = RigctlClient(HOST, PORT)
            self.client.send(cmd)
        self.tx_sent = 0

    def replace_s_meter_when_tx(self, tx_state):
        """Switches between S-METER (RX) and SWR (TX). ALC and POWER always visible."""
        if tx_state:
            # TX - replace S-METER with SWR
            self.s_meter.hide()
            self.swr_meter.show()
        else:
            # RX - replace SWR with S-METER
            self.s_meter.show()
            self.swr_meter.hide()

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
            if TX_OFF_DELAY:
                QTimer.singleShot(TX_OFF_DELAY, self.disable_tx)
            else:
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
            self.filter_width = globals()['FILTER_WIDTH_' + self.mode + '_NARROW']
            # self.filter_width = FILTER_WIDTH_SSB_NARROW
        elif self.filter_normal.isChecked():
            self.filter_width = globals()['FILTER_WIDTH_' + self.mode + '_NORMAL']
            # self.filter_width = FILTER_WIDTH_SSB_NORMAL
        elif self.filter_wide.isChecked():
            self.filter_width = globals()['FILTER_WIDTH_' + self.mode + '_WIDE']
            # self.filter_width = FILTER_WIDTH_SSB_WIDE

        cmd = f"M " + self.mode + " " + str(self.filter_width)
        self.ignore_next_data()
        self.client.send(cmd)

    def antenna_switch_changed(self):
        if not self.tx_active:
            if self.antenna_1.isChecked():
                self.switch_antenna(ANTENNA_1_CMD)
            elif self.antenna_2.isChecked():
                self.switch_antenna(ANTENNA_2_CMD)
            elif self.antenna_3.isChecked():
                self.switch_antenna(ANTENNA_3_CMD)
        else:
            print("Cannot change antenna when TX")

    def set_tx_power(self):
        dialog = SliderDialog(self, value=int(self.tx_power_btn.text().replace('W', '')))
        if dialog.exec_():
            value = dialog.get_value()
            cmd = f"L RFPOWER {value/100:0.2f}"
            self.client.send(cmd)

    def open_frequency_dialog(self):
        dlg = FrequencyDialog(self, value=self.current_freq)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            new_freq = dlg.get_value()
            self.frequency_change(new_freq)

    def open_settings(self):
        """Opens settings dialog"""
        global config
        dlg = SettingsDialog(self, config)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            # Update global config instance if file was changed
            config = dlg.config
            
            # After saving settings, update UI elements that can be changed without restart
            self.update_from_config()
            
            QtWidgets.QMessageBox.information(
                self,
                "Settings Applied",
                "Some settings have been applied.\nRestart the application for all changes to take effect."
            )

    # --- Bookmarks ---
    BOOKMARKS_FILE = os.path.join(dir_path, 'bookmarks.json')

    def _load_bookmarks(self):
        """Load bookmarks from JSON file."""
        try:
            if os.path.exists(self.BOOKMARKS_FILE):
                with open(self.BOOKMARKS_FILE, 'r', encoding='utf-8') as f:
                    bm = json.load(f)
                    if isinstance(bm, list):
                        return bm
        except Exception as e:
            print(f"Error loading bookmarks: {e}")
        return []

    def _save_bookmarks(self, bookmarks):
        """Save bookmarks to JSON file."""
        try:
            with open(self.BOOKMARKS_FILE, 'w', encoding='utf-8') as f:
                json.dump(bookmarks, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving bookmarks: {e}")

    def _refresh_waterfall_bookmarks(self):
        """Push current bookmarks to waterfall widget."""
        if WATERFALL_ENABLED and hasattr(self, 'waterfall_widget'):
            self.waterfall_widget.bookmarks = self._load_bookmarks()
            self.waterfall_widget.update()

    def save_bookmark(self):
        """Save current frequency and mode as bookmark."""
        freq = self.current_freq
        mode = self.mode
        name, ok = QtWidgets.QInputDialog.getText(
            self, "Save Bookmark",
            f"Name for {freq/1e6:.4f} MHz ({mode}):",
            text=f"{freq/1e6:.4f} {mode}"
        )
        if ok and name:
            bookmarks = self._load_bookmarks()
            bookmarks.append({
                'name': name.strip(),
                'freq_hz': freq,
                'mode': mode
            })
            self._save_bookmarks(bookmarks)
            self._refresh_waterfall_bookmarks()

    def open_bookmarks(self):
        """Open bookmarks list dialog."""
        bookmarks = self._load_bookmarks()
        dlg = BookmarksDialog(self, bookmarks)
        result = dlg.exec_()
        if result == QtWidgets.QDialog.Accepted:
            sel = dlg.selected_bookmark
            if sel:
                # Switch to bookmark frequency and mode
                mode = sel.get('mode', self.mode)
                freq = sel['freq_hz']
                cmd = f"M {mode} 0"
                self.client.send(cmd)
                self.frequency_change(freq)
        # Save in case bookmarks were deleted
        self._save_bookmarks(dlg.bookmarks)
        self._refresh_waterfall_bookmarks()

    def toggle_audio_client(self):
        """Starts or stops audio client."""
        if self._audio_thread is not None and self._audio_thread.is_alive():
            # Zatrzymaj
            self._audio_stop_event.set()
            self._audio_thread = None
            self.audio_btn.setText("▶ Audio")
            self.audio_status_label.setText("disconnected")
            self.audio_status_label.setStyleSheet("color: gray; font-size: 8pt;")
        else:
            # Uruchom
            self._audio_stop_event = threading.Event()
            input_dev  = config.get('audio_input_device')
            output_dev = config.get('audio_output_device')
            server     = f"https://{config.get('host')}:8443"
            t = threading.Thread(
                target=start_audio,
                args=(input_dev, output_dev, self.audio_status_changed.emit, self._audio_stop_event, server),
                daemon=True
            )
            self._audio_thread = t
            t.start()
            self.on_audio_status("connecting")

    @QtCore.pyqtSlot(str)
    def on_audio_status(self, status):
        """Thread-safe audio status update."""
        status_map = {
            'connecting':   ('connecting...', '#aa8800', '▶ Audio'),
            'new':          ('connecting...', '#aa8800', '▶ Audio'),
            'checking':     ('checking...',   '#aa8800', '▶ Audio'),
            'connected':    ('connected',     '#4CAF50', '■ Audio'),
            'failed':       ('failed',        '#cc3333', '▶ Audio'),
            'disconnected': ('disconnected',  'gray',    '▶ Audio'),
            'closed':       ('disconnected',  'gray',    '▶ Audio'),
        }
        text, color, btn_text = status_map.get(status, (status, 'gray', '▶ Audio'))
        self.audio_status_label.setText(text)
        self.audio_status_label.setStyleSheet(f"color: {color}; font-size: 8pt;")
        self.audio_btn.setText(btn_text)
        if status in ('failed', 'disconnected', 'closed'):
            self._audio_thread = None
    
    def update_from_config(self):
        """Updates UI elements from current configuration (without restart)"""
        global HOST, PORT, POLL_MS, FREQ_STEP_SLOW, FREQ_STEP_FAST, TX_OFF_DELAY, PTT_KEY
        global ANTENNA_1_NAME, ANTENNA_2_NAME, ANTENNA_3_NAME
        global MOUSE_WHEEL_FREQ_STEP, MOUSE_WHEEL_FAST_FREQ_STEP, DEFAULT_NOISE_REDUCTION
        
        # Update global variables
        HOST = config.get('host')
        PORT = config.get('port')
        POLL_MS = config.get('poll_ms')
        FREQ_STEP_SLOW = config.get('freq_step_slow')
        FREQ_STEP_FAST = config.get('freq_step_fast')
        TX_OFF_DELAY = config.get('tx_off_delay')
        PTT_KEY = config.get('ptt_key')
        ANTENNA_1_NAME = config.get('antenna_1_name')
        ANTENNA_2_NAME = config.get('antenna_2_name')
        ANTENNA_3_NAME = config.get('antenna_3_name')
        MOUSE_WHEEL_FREQ_STEP = config.get('mouse_wheel_freq_step')
        MOUSE_WHEEL_FAST_FREQ_STEP = config.get('mouse_wheel_fast_freq_step')
        DEFAULT_NOISE_REDUCTION = config.get('default_noise_reduction')
        
        # Zaktualizuj nazwy anten w UI
        if hasattr(self, 'antenna_1'):
            self.antenna_1.setText(ANTENNA_1_NAME)
            self.antenna_2.setText(ANTENNA_2_NAME)
            self.antenna_3.setText(ANTENNA_3_NAME)
        
        # Zaktualizuj PTT button label
        self.ptt_btn.setText(f"PTT\\n({PTT_KEY})")
        
        # Stay on top
        if config.get('stay_on_top'):
            self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowStaysOnTopHint)
        self.show()  # Need to show window again after changing flags




    def ptt_btn_pressed(self):
        self.send_tx_signal.emit(1)
        self.ptt_btn.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border-radius: 20px; border: 1px solid black;")

    def ptt_btn_released(self):
        self.send_tx_signal.emit(0)
        self.ptt_btn.setStyleSheet("background-color: " + NOT_ACTIVE_COLOR + "; text-align: center; border-radius: 20px; border: 1px solid black;")

    def swr_btn_pressed(self):
        self.current_power = self.tx_power_btn.text().replace('W', '')
        self.current_mode = self.mode
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
        self.swr_btn.setStyleSheet("background-color: " + "#e6bb4f" + "; text-align: center; border-radius: 4px; border: 1px solid black;")

        QTimer.singleShot(TX_OFF_DELAY, self.stop_swr_check)

    def miceq_btn_btn_pressed(self):
        cmd = "EX037"
        current_eq = self.client.send('w' + cmd + ';')
        if cmd in current_eq:
            current_eq = current_eq.replace(cmd, '')
            current_eq = current_eq.replace(';', '')
            current_eq = current_eq.replace('\0', '')
            current_eq = current_eq.replace('RPRT 0', '')
            current_eq = current_eq.replace('\n', '')
            dlg = EqDialog(self, current_eq)
            if dlg.exec_():
                eq_value = dlg.selected_eq
                cmd = 'w' + cmd + str(eq_value) + ';'
                self.client.send(cmd)

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
        
            # callback will execute after playback finishes
            def on_finished():
                self.sound_finished.emit(widget)

            playSound(path, on_finished=on_finished)

    def _on_sound_finished(self, widget):
        self.send_tx_signal.emit(0)
        widget.setStyleSheet("background-color: " + ACTIVE_COLOR + "; text-align: center; border-radius: 4px; border: 1px solid black;")
        QTimer.singleShot(TX_OFF_DELAY, self.disable_monitor)

    def disable_monitor(self):
        cmd = f"U MON 0"
        self.client.send(cmd)

    def play1_btn_pressed(self):
        self.play_sound(REC1_PATH, self.play1_btn)

    def play2_btn_pressed(self):
        self.play_sound(REC2_PATH, self.play2_btn)

    def adjust_waterfall_btn_pressed(self):
        self.adjust_waterfall_colors.emit()

    def closeEvent(self, event):
        if WATERFALL_ENABLED and hasattr(self, 'ws_thread'):
            self.ws_thread.stop()
        if hasattr(self, 'dx_cluster'):
            self.dx_cluster.stop()
        if self._audio_stop_event is not None:
            self._audio_stop_event.set()
        if self._audio_thread is not None and self._audio_thread.is_alive():
            self._audio_thread.join(timeout=3)
        self.thread.quit()
        self.thread.wait(1000)
        super().closeEvent(event)

    def switch_antenna(self, cmd, host=HOST, port=ANTENNA_SWITCH_PORT):
        try:
            with socket.create_connection((host, port), timeout=1) as s:
                s.sendall(cmd.encode("ascii", errors="ignore"))
                response = s.recv(1024).decode('utf-8').strip()
                print("Antenna server response:", response)
                self.status.showMessage(response)
        except Exception as e:
            print("Connection error:", e)

    def get_current_antenna(self, host=HOST, port=ANTENNA_SWITCH_PORT):
        try:
            with socket.create_connection((host, port), timeout=1) as s:
                cmd = GET_ANTENNA_CMD
                s.sendall(cmd.encode("ascii", errors="ignore"))
                response = s.recv(1024).decode('utf-8').strip()
                print("Antenna server response:", response)
                try:
                    getattr(self, f"antenna_{response}").setChecked(True)
                except:
                    pass
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

            # TX (e.g. Alt)
            if PTT_KEY in pressed_keys and not tx_pressed:
                tx_pressed = True
                main_window.send_tx_signal.emit(1)

            # FST combo (e.g. Shift + Q)
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

def start_audio(input_device=None, output_device=None, status_callback=None, stop_event=None, server_url=None):
    try:
        asyncio.run(audioClientRun(
            input_device=input_device,
            output_device=output_device,
            status_callback=status_callback,
            stop_event=stop_event,
            server_url=server_url,
        ))
    except Exception as e:
        print(f"Audio client error: {e}")
        if status_callback:
            status_callback("failed")

def main():
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    thread = threading.Thread(target=start_keyboard_listener, args=(w,), daemon=True)
    thread.start()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
