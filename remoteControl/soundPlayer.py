import sounddevice as sd
import soundfile as sf
import threading
import os
import time
from typing import Optional, Callable

# ==============================
# KONFIGURACJA
# ==============================
OUTPUT_DEVICE_NAME = "CABLE Input"  # np. VB-Audio Cable Input

# ==============================
# ZMIENNE GLOBALNE
# ==============================
_play_thread: Optional[threading.Thread] = None
_stop_flag = threading.Event()
_on_finished: Optional[Callable[[], None]] = None


def _get_device_id(device_name: str):
    """Zwraca ID urządzenia o danej nazwie (ignoruje wielkość liter)."""
    for i, dev in enumerate(sd.query_devices()):
        if device_name.lower() in dev["name"].lower():
            return i
    return None


def _play_audio(file_path: str, device_id: int):
    """Wewnętrzna funkcja odtwarzająca audio w osobnym wątku."""
    global _stop_flag, _on_finished
    try:
        data, fs = sf.read(file_path, dtype='float32')
    except Exception as e:
        print(f"❌ Błąd odczytu pliku: {e}")
        return

    stream = sd.OutputStream(
        samplerate=fs,
        device=device_id,
        channels=data.shape[1] if len(data.shape) > 1 else 1,
    )
    stream.start()

    blocksize = 1024
    i = 0
    while i < len(data):
        if _stop_flag.is_set():
            break
        end = i + blocksize
        stream.write(data[i:end])
        i = end

    stream.stop()
    stream.close()

    if _on_finished and not _stop_flag.is_set():
        try:
            _on_finished()
        except Exception as e:
            print(f"⚠️ Błąd w callbacku on_play_finished: {e}")


def playSound(path: str, on_finished: Optional[Callable[[], None]] = None):
    """
    Uruchamia odtwarzanie pliku WAV w osobnym wątku.
    Można przekazać callback `on_finished`, który zostanie wywołany po zakończeniu.
    """
    global _play_thread, _stop_flag, _on_finished
    base_dir = os.path.dirname(os.path.realpath(__file__))
    file_path = os.path.join(base_dir, path)

    if not os.path.exists(file_path):
        print(f"❌ Nie znaleziono pliku: {file_path}")
        return

    device_id = _get_device_id(OUTPUT_DEVICE_NAME)
    if device_id is None:
        print(f"❌ Nie znaleziono urządzenia: {OUTPUT_DEVICE_NAME}")
        return

    stopSound()
    _stop_flag.clear()
    _on_finished = on_finished

    _play_thread = threading.Thread(target=_play_audio, args=(file_path, device_id), daemon=True)
    _play_thread.start()


def stopSound():
    """Zatrzymuje aktualne odtwarzanie."""
    global _stop_flag
    if not _stop_flag.is_set():
        _stop_flag.set()


def isPlaying() -> bool:
    """Zwraca True jeśli dźwięk nadal jest odtwarzany."""
    global _play_thread
    return _play_thread is not None and _play_thread.is_alive()
