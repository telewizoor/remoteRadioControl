#!/usr/bin/env python3
"""
Klient WebRTC — Windows PC
Odbiera audio z radia, wysyła mikrofon.

Instalacja:
    pip install aiortc aiohttp sounddevice numpy

Użycie:
    python audioClient.py                          # domyślne urządzenia
    python audioClient.py --list-devices           # lista urządzeń
    python audioClient.py --input 1 --output 3    # konkretne urządzenia
"""

import asyncio
import ssl
import logging
import argparse
import queue
import threading
import time
import fractions
import numpy as np
import sounddevice as sd
import aiohttp
import av
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack

# ── Monkey-patch: Opus bitrate ────────────────────────────────
# aiortc hardkoduje bit_rate=96000 i ignoruje SDP fmtp / setParameters()
# (issue #1393). Jedyne pewne rozwiązanie to podmiana klasy enkodra.
OPUS_BITRATE = 16_000   # 16 kbps — więcej niż dość na SSB 3 kHz voice

import aiortc.codecs.opus as _opus_mod
import aiortc.codecs as _codecs_mod

_OrigOpusEncoder = _opus_mod.OpusEncoder

class _LowBitrateOpusEncoder(_OrigOpusEncoder):
    def __init__(self):
        super().__init__()
        self.codec.bit_rate = OPUS_BITRATE

_opus_mod.OpusEncoder = _LowBitrateOpusEncoder
_codecs_mod.OpusEncoder = _LowBitrateOpusEncoder
# ─────────────────────────────────────────────────────────────

# Logging — gdy używany jako moduł nie wysyła nic (NullHandler).
# Przy uruchomieniu bezpośrednim basicConfig jest wywoływany w __main__.
log = logging.getLogger("audioClient")
log.addHandler(logging.NullHandler())

SERVER      = "https://192.168.152.12:8443"
SD_RATE     = 48000
SAMPLE_TIME = 20
BLOCK_SIZE  = SD_RATE * SAMPLE_TIME // 1000   # 960 próbek = 20 ms

# Rozmiar kolejki odbioru: ~300 ms bufora jitter. Przy maxsize=3 (60 ms) każde
# chwilowe opóźnienie sieci powoduje underrun → skok do zera → trzask.
RX_QUEUE_SIZE = 10

# Ile próbek wstępnie buforować zanim zacznie wychodzić dźwięk (2 bloki = 40 ms).
RX_PREFILL = 2

# Długość fade-out przy underrun (próbki). Zamiast skoku do zera stosujemy
# krótkie wygaszenie, co eliminuje "klik".
FADE_LEN = 256

# ─────────────────────────────────────────────────────────────
# ODBIÓR: WebRTC track → sounddevice output
# ─────────────────────────────────────────────────────────────

class RadioPlayer:

    def __init__(self, device):
        self._device    = device
        self._sync_q    = queue.Queue(maxsize=RX_QUEUE_SIZE)
        self._resampler = av.AudioResampler(format="s16", layout="mono", rate=SD_RATE)
        self._prefilled = False
        # ostatni odtworzony fragment — do fade-out przy underrun
        self._last      = np.zeros(BLOCK_SIZE, dtype=np.float32)
        self._fade_win  = np.linspace(1.0, 0.0, FADE_LEN, dtype=np.float32)

    def start(self, loop):
        t = threading.Thread(target=self._sd_thread, daemon=True)
        t.start()

    def _sd_thread(self):

        def callback(outdata, frames, time_info, status):
            # Czekaj na wstępne buforowanie żeby uniknąć natychmiastowych underrunów.
            if not self._prefilled:
                if self._sync_q.qsize() >= RX_PREFILL:
                    self._prefilled = True
                else:
                    outdata[:, 0] = 0.0
                    return

            try:
                chunk = self._sync_q.get_nowait()
                if len(chunk) < frames:
                    chunk = np.pad(chunk, (0, frames - len(chunk)))
                self._last[:] = chunk[:BLOCK_SIZE]
                outdata[:, 0] = chunk[:frames]
            except queue.Empty:
                # Łagodne wygaszenie zamiast skoku do zera → brak trzasku
                fade = self._last.copy()
                apply = min(FADE_LEN, frames)
                fade[:apply] *= self._fade_win[:apply]
                fade[apply:]  = 0.0
                self._last[:] = 0.0
                outdata[:, 0] = fade[:frames]

        kwargs = dict(samplerate=SD_RATE, channels=1, dtype="float32",
                      blocksize=BLOCK_SIZE, callback=callback)
        if self._device is not None:
            kwargs["device"] = self._device

        log.debug("Odtwarzanie: device=%s %d Hz", self._device, SD_RATE)
        with sd.OutputStream(**kwargs):
            while True:
                time.sleep(1)

    def addTrack(self, track):
        asyncio.ensure_future(self._run(track))

    async def _run(self, track):
        log.debug("RadioPlayer: start odbioru")
        while True:
            try:
                frame = await track.recv()
                for f in self._resampler.resample(frame):
                    raw     = np.frombuffer(bytes(f.planes[0]), dtype=np.int16)
                    samples = raw.astype(np.float32) / 32768.0
                    try:
                        self._sync_q.put_nowait(samples)
                    except queue.Full:
                        # Kolejka pełna — stary bufor wypychamy żeby zrobić miejsce
                        try:
                            self._sync_q.get_nowait()
                        except queue.Empty:
                            pass
                        self._sync_q.put_nowait(samples)
            except Exception as e:
                log.warning("RadioPlayer koniec: %s", e)
                break


# ─────────────────────────────────────────────────────────────
# NADAWANIE: sounddevice input → WebRTC track
# ─────────────────────────────────────────────────────────────

class MicTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self, device):
        super().__init__()
        self._device    = device
        self._sync_q    = queue.Queue(maxsize=6)
        self._pts       = 0
        self._time_base = fractions.Fraction(1, SD_RATE)

    def start_capture(self):
        t = threading.Thread(target=self._sd_thread, daemon=True)
        t.start()

    def _sd_thread(self):
        def callback(indata, frames, time_info, status):
            chunk = (indata[:, 0] * 32767).clip(-32768, 32767).astype(np.int16).copy()
            try:
                self._sync_q.put_nowait(chunk)
            except queue.Full:
                # Zamiast cicho upuścić ramkę, wyrzuć najstarszą
                try:
                    self._sync_q.get_nowait()
                except queue.Empty:
                    pass
                self._sync_q.put_nowait(chunk)

        kwargs = dict(samplerate=SD_RATE, channels=1, dtype="float32",
                      blocksize=BLOCK_SIZE, callback=callback)
        if self._device is not None:
            kwargs["device"] = self._device

        log.debug("Mikrofon: device=%s %d Hz", self._device, SD_RATE)
        with sd.InputStream(**kwargs):
            while True:
                time.sleep(1)

    async def recv(self):
        loop = asyncio.get_event_loop()
        chunk = await loop.run_in_executor(None, self._sync_q.get)

        frame            = av.AudioFrame.from_ndarray(chunk.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = SD_RATE
        frame.pts         = self._pts
        frame.time_base   = self._time_base
        self._pts        += len(chunk)
        return frame


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

async def run(input_device, output_device, status_callback=None, stop_event=None, server_url=None):
    loop = asyncio.get_event_loop()
    target_server = server_url or SERVER

    if status_callback:
        status_callback("connecting")

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode    = ssl.CERT_NONE

    pc = RTCPeerConnection()

    mic = MicTrack(input_device)
    mic.start_capture()
    pc.addTrack(mic)

    player = RadioPlayer(output_device)
    player.start(loop)

    @pc.on("track")
    def on_track(track):
        log.debug("Track z RPi: %s", track.kind)
        if track.kind == "audio":
            player.addTrack(track)

    @pc.on("connectionstatechange")
    async def on_conn():
        log.info("connectionState: %s", pc.connectionState)
        if status_callback:
            status_callback(pc.connectionState)

    @pc.on("iceconnectionstatechange")
    async def on_ice():
        log.debug("ICE: %s", pc.iceConnectionState)

    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)

    for _ in range(30):
        if pc.iceGatheringState == "complete":
            break
        await asyncio.sleep(0.1)

    log.info("Wysyłam offer → %s", target_server)

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_ctx)) as session:
        async with session.post(
            f"{target_server}/offer",
            json={"sdp": pc.localDescription.sdp, "type": pc.localDescription.type},
        ) as resp:
            data = await resp.json()

    await pc.setRemoteDescription(RTCSessionDescription(sdp=data["sdp"], type=data["type"]))
    log.info("Połączono!")

    if stop_event is not None:
        await loop.run_in_executor(None, stop_event.wait)
        await pc.close()
    else:
        await asyncio.Event().wait()



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FT-450D WebRTC client")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--input",  type=int, default=None, metavar="N")
    parser.add_argument("--output", type=int, default=None, metavar="N")
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
        asyncio.run(run(args.input, args.output))
    except KeyboardInterrupt:
        log.info("Zatrzymano")