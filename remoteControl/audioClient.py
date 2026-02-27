#!/usr/bin/env python3
"""
Klient WebSocket Audio — Windows PC
Odbiera audio z radia (RX), wysyła mikrofon (TX).
Zastępuje klienta aiortc/WebRTC — brak ICE/DTLS/SRTP, niskie opóźnienie,
~12 kbps Opus zamiast 100+ kbps.

Instalacja:
    pip install websockets sounddevice numpy pyogg

Użycie:
    python audioClient.py                              # domyślne urządzenia
    python audioClient.py --list-devices               # lista urządzeń
    python audioClient.py --input 1 --output 3         # konkretne urządzenia
    python audioClient.py --server wss://192.168.x.x/audio
"""

import asyncio
import ssl
import logging
import argparse
import queue
import threading
import time
import numpy as np
import sounddevice as sd
import websockets
import pyogg

# Logging — gdy używany jako moduł nie wysyła nic (NullHandler).
# Przy uruchomieniu bezpośrednim basicConfig jest wywoływany w __main__.
log = logging.getLogger("audioClient")
log.addHandler(logging.NullHandler())

SERVER        = "wss://192.168.152.12/audio"
SD_RATE       = 48000
FRAME_SAMPLES = 960         # 20 ms @ 48 kHz
FRAME_BYTES   = FRAME_SAMPLES * 2   # int16 mono
OPUS_BITRATE  = 12000       # 12 kbps — wystarczy dla SSB
RX_QUEUE_SIZE = 15          # ~300 ms bufora jitter
RX_PREFILL    = 2           # ile ramek wstępnie buforować
FADE_LEN      = 256         # próbki fade-out przy underrun


# ─────────────────────────────────────────────────────────────
# Audio Bridge: WebSocket ↔ sounddevice, Opus encode/decode
# ─────────────────────────────────────────────────────────────

class AudioBridge:
    """Bidirectional audio over a single WebSocket connection.

    RX  radio → server → WebSocket → Opus decode → sounddevice output
    TX  sounddevice input → Opus encode → WebSocket → server → radio
    """

    def __init__(self, input_device=None, output_device=None):
        self._in_dev  = input_device
        self._out_dev = output_device

        self._enc = pyogg.OpusEncoder()
        self._enc.set_application("voip")
        self._enc.set_sampling_frequency(SD_RATE)
        self._enc.set_channels(1)
        self._dec = pyogg.OpusDecoder()
        self._dec.set_sampling_frequency(SD_RATE)
        self._dec.set_channels(1)

        # Raw int16 PCM bytes from mic capture  → encode → WS send
        self._tx_q = queue.Queue(maxsize=6)
        # Decoded float32 samples from WS receive → playback callback
        self._rx_q = queue.Queue(maxsize=RX_QUEUE_SIZE)

        self._prefilled = False
        self._last      = np.zeros(FRAME_SAMPLES, dtype=np.float32)
        self._fade_win  = np.linspace(1.0, 0.0, FADE_LEN, dtype=np.float32)

    # ── Playback thread ───────────────────────────────────────────────

    def _start_output(self):
        def callback(outdata, frames, time_info, status):
            if not self._prefilled:
                if self._rx_q.qsize() >= RX_PREFILL:
                    self._prefilled = True
                else:
                    outdata[:, 0] = 0.0
                    return
            try:
                chunk = self._rx_q.get_nowait()
                if len(chunk) < frames:
                    chunk = np.pad(chunk, (0, frames - len(chunk)))
                self._last[:] = chunk[:FRAME_SAMPLES]
                outdata[:, 0] = chunk[:frames]
            except queue.Empty:
                # Łagodne wygaszenie zamiast skoku do zera → brak trzasku
                fade = self._last.copy()
                n = min(FADE_LEN, frames)
                fade[:n] *= self._fade_win[:n]
                fade[n:]  = 0.0
                self._last[:] = 0.0
                outdata[:, 0] = fade[:frames]

        kwargs = dict(samplerate=SD_RATE, channels=1, dtype="float32",
                      blocksize=FRAME_SAMPLES, callback=callback)
        if self._out_dev is not None:
            kwargs["device"] = self._out_dev

        def _run():
            log.debug("Odtwarzanie: device=%s %dHz", self._out_dev, SD_RATE)
            with sd.OutputStream(**kwargs):
                threading.Event().wait()

        threading.Thread(target=_run, daemon=True).start()

    # ── Capture thread ────────────────────────────────────────────────

    def _start_input(self):
        def callback(indata, frames, time_info, status):
            chunk = (indata[:, 0] * 32767).clip(-32768, 32767).astype(np.int16).tobytes()
            try:
                self._tx_q.put_nowait(chunk)
            except queue.Full:
                try:    self._tx_q.get_nowait()
                except queue.Empty: pass
                self._tx_q.put_nowait(chunk)

        kwargs = dict(samplerate=SD_RATE, channels=1, dtype="float32",
                      blocksize=FRAME_SAMPLES, callback=callback)
        if self._in_dev is not None:
            kwargs["device"] = self._in_dev

        def _run():
            log.debug("Mikrofon: device=%s %dHz", self._in_dev, SD_RATE)
            with sd.InputStream(**kwargs):
                threading.Event().wait()

        threading.Thread(target=_run, daemon=True).start()

    # ── RX coroutine: WebSocket → decode → play queue ─────────────────

    async def _rx_loop(self, ws):
        async for message in ws:
            if not isinstance(message, (bytes, bytearray)):
                continue
            try:
                pcm = self._dec.decode(bytes(message))
                samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
                try:
                    self._rx_q.put_nowait(samples)
                except queue.Full:
                    try:    self._rx_q.get_nowait()
                    except queue.Empty: pass
                    self._rx_q.put_nowait(samples)
            except Exception as e:
                log.debug("Decode error: %s", e)

    # ── TX coroutine: capture queue → encode → WebSocket ──────────────

    async def _tx_loop(self, ws):
        loop = asyncio.get_event_loop()
        while True:
            try:
                pcm_bytes = await asyncio.wait_for(
                    loop.run_in_executor(None, self._tx_q.get), timeout=2.0)
                opus = self._enc.encode(pcm_bytes)
                await ws.send(opus)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                log.warning("TX error: %s", e)
                break

    # ── Main ──────────────────────────────────────────────────────────

    async def run(self, server_url=None, status_callback=None, stop_event=None):
        url = server_url or SERVER
        if status_callback:
            status_callback("connecting")

        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode    = ssl.CERT_NONE

        self._start_output()
        self._start_input()

        log.info("Łączę z %s", url)
        async with websockets.connect(url, ssl=ssl_ctx) as ws:
            log.info("Połączono!")
            if status_callback:
                status_callback("connected")

            tasks = [
                asyncio.ensure_future(self._rx_loop(ws)),
                asyncio.ensure_future(self._tx_loop(ws)),
            ]

            if stop_event is not None:
                loop = asyncio.get_event_loop()
                stop_task = asyncio.ensure_future(
                    loop.run_in_executor(None, stop_event.wait))
                tasks.append(stop_task)

            try:
                done, pending = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for t in tasks:
                    t.cancel()

        if status_callback:
            status_callback("disconnected")


# ─────────────────────────────────────────────────────────────
# Public API (backwards-compatible with remoteControl.py imports)
# ─────────────────────────────────────────────────────────────

async def run(input_device, output_device, status_callback=None,
              stop_event=None, server_url=None):
    bridge = AudioBridge(input_device, output_device)
    await bridge.run(server_url, status_callback, stop_event)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FT-450D WebSocket audio client")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--input",  type=int, default=None, metavar="N")
    parser.add_argument("--output", type=int, default=None, metavar="N")
    parser.add_argument("--server", default=None, metavar="URL",
                        help=f"WebSocket URL (default: {SERVER})")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Pokaż szczegółowe logi (DEBUG)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.list_devices:
        print(sd.query_devices())
        raise SystemExit

    try:
        asyncio.run(run(args.input, args.output, server_url=args.server))
    except KeyboardInterrupt:
        log.info("Zatrzymano")
