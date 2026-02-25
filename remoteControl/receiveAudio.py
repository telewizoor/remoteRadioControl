#!/usr/bin/env python3
"""
Klient WebRTC — Windows PC
Odbiera audio z radia, wysyła mikrofon.
Opus po stronie aiortc sam ogarnia resample.

Instalacja:
    pip install aiortc aiohttp sounddevice numpy

Użycie:
    python receive_audio.py                        # domyślne urządzenia
    python receive_audio.py --list-devices         # lista urządzeń
    python receive_audio.py --input 1 --output 3  # konkretne urządzenia
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

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("client")

SERVER     = "https://192.168.152.12:8443"
# sounddevice domyślnie 48kHz na Windows — Opus ogarnie
SD_RATE    = 48000
SAMPLE_TIME = 20
BLOCK_SIZE  = SD_RATE * SAMPLE_TIME // 1000  # 960 próbki = 20ms

# ─────────────────────────────────────────────────────────────
# ODBIÓR: WebRTC track → sounddevice output
# ─────────────────────────────────────────────────────────────

class RadioPlayer:

    def __init__(self, device):
        self._device    = device
        self._async_q   = None
        self._sync_q    = queue.Queue(maxsize=3)
        self._resampler = av.AudioResampler(format="s16", layout="mono", rate=SD_RATE)

    def start(self, loop):
        self._async_q = asyncio.Queue(maxsize=3)
        # drainuj async → sync queue
        asyncio.ensure_future(self._drain())
        # uruchom sounddevice w osobnym wątku
        t = threading.Thread(target=self._sd_thread, daemon=True)
        t.start()

    async def _drain(self):
        while True:
            chunk = await self._async_q.get()
            try:
                self._sync_q.put_nowait(chunk)
            except queue.Full:
                pass

    def _sd_thread(self):
        silence = np.zeros(BLOCK_SIZE, dtype=np.float32)

        def callback(outdata, frames, time_info, status):
            try:
                chunk = self._sync_q.get_nowait()
                if len(chunk) < frames:
                    chunk = np.pad(chunk, (0, frames - len(chunk)))
                outdata[:, 0] = chunk[:frames]
            except queue.Empty:
                outdata[:, 0] = silence[:frames]

        kwargs = dict(samplerate=SD_RATE, channels=1, dtype="float32",
                      blocksize=BLOCK_SIZE, callback=callback)
        if self._device is not None:
            kwargs["device"] = self._device

        log.info("Odtwarzanie: device=%s %dHz", self._device, SD_RATE)
        with sd.OutputStream(**kwargs):
            while True:
                time.sleep(1)

    def addTrack(self, track):
        asyncio.ensure_future(self._run(track))

    async def _run(self, track):
        cnt = 0
        log.info("RadioPlayer: start odbioru")
        while True:
            try:
                frame = await track.recv()
                cnt += 1
                if cnt == 1:
                    log.info("FRAME: fmt=%s rate=%d samples=%d layout=%s",
                             frame.format.name, frame.sample_rate, frame.samples, frame.layout.name)

                # Resampler ogarnie każdy format/layout → s16 mono 48kHz
                for f in self._resampler.resample(frame):
                    raw = np.frombuffer(bytes(f.planes[0]), dtype=np.int16)
                    samples = raw.astype(np.float32) / 32768.0
                    await self._async_q.put(samples)

                # if cnt % 200 == 1:
                #     log.info("RX radio #%d rate=%d layout=%s", cnt, frame.sample_rate, frame.layout.name)
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
        self._sync_q    = queue.Queue(maxsize=3)
        self._pts       = 0
        self._time_base = fractions.Fraction(1, SD_RATE)
        self._cnt       = 0

    def start_capture(self):
        t = threading.Thread(target=self._sd_thread, daemon=True)
        t.start()

    def _sd_thread(self):
        def callback(indata, frames, time_info, status):
            chunk = (indata[:, 0] * 32767).clip(-32768, 32767).astype(np.int16).copy()
            try:
                self._sync_q.put_nowait(chunk)
            except queue.Full:
                pass

        kwargs = dict(samplerate=SD_RATE, channels=1, dtype="float32",
                      blocksize=BLOCK_SIZE, callback=callback)
        if self._device is not None:
            kwargs["device"] = self._device

        log.info("Mikrofon: device=%s %dHz", self._device, SD_RATE)
        with sd.InputStream(**kwargs):
            while True:
                time.sleep(1)

    async def recv(self):
        loop = asyncio.get_event_loop()
        # Pobierz blok z mikrofonu (blokujące — w executorze)
        chunk = await loop.run_in_executor(None, self._sync_q.get)

        frame = av.AudioFrame.from_ndarray(chunk.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = SD_RATE
        frame.pts         = self._pts
        frame.time_base   = self._time_base
        self._pts        += len(chunk)

        self._cnt += 1
        if self._cnt % 200 == 1:
            log.info("TX mic #%d peak=%d", self._cnt, int(np.max(np.abs(chunk))))

        return frame


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

async def run(input_device, output_device):
    loop = asyncio.get_event_loop()

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
        log.info("Track z RPi: %s", track.kind)
        if track.kind == "audio":
            player.addTrack(track)

    @pc.on("connectionstatechange")
    async def on_conn():
        log.info("connectionState: %s", pc.connectionState)

    @pc.on("iceconnectionstatechange")
    async def on_ice():
        log.info("ICE: %s", pc.iceConnectionState)

    offer = await pc.createOffer()

    # offer.sdp = offer.sdp.replace(
    #     "a=rtpmap:96 opus/48000/2",
    #     "a=rtpmap:96 opus/48000/2\r\n"
    #     "a=fmtp:96 stereo=0;"
    #     # "sprop-stereo=0;"
    #     "maxaveragebitrate=16000;"
    #     "maxplaybackrate=16000;"
    #     "sprop-maxcapturerate=16000;"
    #     # "ptime=20;"
    #     # "minptime=20;"
    #     "useinbandfec=0;"
    #     "usedtx=1"
    # ) # maxplaybackrate=16000; sprop-maxcapturerate=16000; maxaveragebitrate=20000; stereo=1; useinbandfec=1; usedtx=0

    # offer.sdp = offer.sdp.replace(
    #     "m=audio 9 UDP/TLS/RTP/SAVPF 96 9 0 8",
    #     "m=audio 9 UDP/TLS/RTP/SAVPF 8"
    # )

    await pc.setLocalDescription(offer)
    log.info("SDP offer:\n%s", offer.sdp)

    for _ in range(30):
        if pc.iceGatheringState == "complete":
            break
        await asyncio.sleep(0.1)

    log.info("Wysyłam offer → %s", SERVER)

    asyncio.create_task(monitor(pc))

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_ctx)) as session:
        async with session.post(
            f"{SERVER}/offer",
            json={"sdp": pc.localDescription.sdp, "type": pc.localDescription.type},
        ) as resp:
            data = await resp.json()

    await pc.setRemoteDescription(RTCSessionDescription(sdp=data["sdp"], type=data["type"]))
    log.info("Połączono! Ctrl+C żeby zatrzymać.")
    await asyncio.Event().wait()

async def monitor(pc):
    prev = 0
    while True:
        stats = await pc.getStats()
        for r in stats.values():
            if r.type == "outbound-rtp" and r.kind == "audio":
                now = r.bytesSent
                bitrate = (now - prev) * 8 / 2 / 1000
                print("AUDIO kbps:", bitrate)
                prev = now
        await asyncio.sleep(2)



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FT-450D WebRTC client")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--input",  type=int, default=None, metavar="N")
    parser.add_argument("--output", type=int, default=None, metavar="N")
    args = parser.parse_args()

    if args.list_devices:
        print(sd.query_devices())
        raise SystemExit

    try:
        asyncio.run(run(args.input, args.output))
    except KeyboardInterrupt:
        log.info("Zatrzymano")