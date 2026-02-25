#!/usr/bin/env python3
"""
WebRTC Audio Bridge — FT-450D
- Jeden globalny sd.Stream duplex (karta nigdy nie zajęta podwójnie)
- Każde połączenie ma własną kolejkę capture (brak cross-contamination)
- HTTPS self-signed
"""

import asyncio
import json
import logging
import ssl
import fractions
import os
import queue
import threading
import av
import numpy as np
import sounddevice as sd
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
import aiohttp_cors

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("radio")

DEVICE_NAME = "USB Audio Device"
SAMPLE_RATE = 48000
CHANNELS    = 1
SAMPLE_TIME = 20
BLOCK_SIZE  = SAMPLE_RATE * SAMPLE_TIME // 1000  # 960 próbki = 20ms

HOST      = "0.0.0.0"
PORT      = 8443
CERT_FILE = "cert.pem"
KEY_FILE  = "key.pem"

# ── Globalny audio engine ────────────────────────────────────
_lock          = threading.Lock()
_capture_subs  = []   # lista kolejek aktywnych RadioTrack
_playback_q    = queue.Queue(maxsize=100)
_audio_stream  = None


def _audio_callback(indata, outdata, frames, time_info, status):
    if status:
        log.warning("audio: %s", status)

    # Broadcast capture do wszystkich aktywnych połączeń
    block = indata[:, 0].copy()
    with _lock:
        for q in _capture_subs:
            try:
                q.put_nowait(block)
            except queue.Full:
                pass  # to połączenie nie nadąża — pomijamy

    # Playback
    try:
        chunk = _playback_q.get_nowait()
        if len(chunk) < frames:
            chunk = np.pad(chunk, (0, frames - len(chunk)))
        outdata[:, 0] = chunk[:frames].astype(np.float32)
    except queue.Empty:
        outdata[:, 0] = np.zeros(frames, dtype=np.float32)


def _start_audio(device_index: int):
    global _audio_stream
    _audio_stream = sd.Stream(
        device=(device_index, device_index),
        samplerate=SAMPLE_RATE,
        channels=(CHANNELS, CHANNELS),
        dtype=("int16", "float32"),
        blocksize=BLOCK_SIZE,
        callback=_audio_callback,
    )
    _audio_stream.start()
    log.info("Audio stream: device=%d %dHz blocksize=%d", device_index, SAMPLE_RATE, BLOCK_SIZE)


def _find_device() -> int:
    for i, d in enumerate(sd.query_devices()):
        if DEVICE_NAME in d['name']:
            log.info("Device '%s' → idx=%d in=%d out=%d",
                     d['name'], i, d['max_input_channels'], d['max_output_channels'])
            return i
    raise RuntimeError(f"Nie znaleziono '{DEVICE_NAME}'. Dostępne: {[d['name'] for d in sd.query_devices()]}")


pcs = set()


# ─────────────────────────────────────────────────────────────
# NADAWANIE: własna kolejka capture → WebRTC
# ─────────────────────────────────────────────────────────────

class RadioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self):
        super().__init__()
        self._q         = queue.Queue(maxsize=50)
        self._pts       = 0
        self._time_base = fractions.Fraction(1, SAMPLE_RATE)
        self._cnt       = 0
        # Zarejestruj własną kolejkę w broadcast liście
        with _lock:
            _capture_subs.append(self._q)
        log.info("RadioTrack: zarejestrowano (aktywne: %d)", len(_capture_subs))

    async def recv(self):
        loop = asyncio.get_event_loop()
        samples = await loop.run_in_executor(None, self._q.get)

        self._cnt += 1
        if self._cnt % 200 == 1:
            log.info("TX #%d peak=%d qsize=%d", self._cnt,
                     int(np.max(np.abs(samples))), self._q.qsize())

        frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = SAMPLE_RATE
        frame.pts         = self._pts
        frame.time_base   = self._time_base
        self._pts        += len(samples)
        return frame

    def stop(self):
        super().stop()
        # Wyrejestruj kolejkę z broadcast listy
        with _lock:
            try:
                _capture_subs.remove(self._q)
            except ValueError:
                pass
        log.info("RadioTrack: wyrejestrowano (aktywne: %d)", len(_capture_subs))


# ─────────────────────────────────────────────────────────────
# ODBIERANIE: WebRTC mic → playback
# ─────────────────────────────────────────────────────────────

class MicSink:

    def __init__(self):
        self._resampler = av.AudioResampler(format="fltp", layout="mono", rate=SAMPLE_RATE)
        self._active    = True

    def addTrack(self, track):
        asyncio.ensure_future(self._run(track))

    async def _run(self, track):
        loop = asyncio.get_event_loop()
        cnt = 0
        while self._active:
            try:
                frame = await track.recv()
                cnt += 1

                def process(f):
                    for of in self._resampler.resample(f):
                        samples = np.frombuffer(bytes(of.planes[0]), dtype=np.float32).copy()
                        try:
                            _playback_q.put_nowait(samples)
                        except queue.Full:
                            pass

                await loop.run_in_executor(None, process, frame)

                if cnt % 200 == 1:
                    log.info("RX mic #%d rate=%d fmt=%s samples=%d pq=%d",
                             cnt, frame.sample_rate, frame.format.name,
                             frame.samples, _playback_q.qsize())
            except Exception as e:
                log.warning("MicSink koniec: %s", e)
                break

    def stop(self):
        self._active = False
        # Wyczyść playback queue żeby nie było starych danych
        while not _playback_q.empty():
            try: _playback_q.get_nowait()
            except: break


# ─────────────────────────────────────────────────────────────
# SIGNALING
# ─────────────────────────────────────────────────────────────

async def offer(request):
    params    = await request.json()
    offer_sdp = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection()
    pcs.add(pc)

    radio_track = RadioTrack()
    pc.addTrack(radio_track)
    mic_sink = MicSink()

    @pc.on("connectionstatechange")
    async def on_state():
        log.info("connectionState: %s [total: %d]", pc.connectionState, len(pcs))
        if pc.connectionState in ("failed", "closed", "disconnected"):
            radio_track.stop()
            mic_sink.stop()
            await pc.close()
            pcs.discard(pc)

    @pc.on("track")
    def on_track(track):
        if track.kind == "audio":
            log.info("Mic odebrany → USB Audio Device")
            mic_sink.addTrack(track)

    await pc.setRemoteDescription(offer_sdp)
    answer = await pc.createAnswer()

    # answer.sdp = answer.sdp.replace(
    #     "a=rtpmap:96 opus/48000/2",
    #     "a=rtpmap:96 opus/48000/2\r\n"
    #     "a=fmtp:96 stereo=0;"
    #     "sprop-stereo=0;"
    #     "maxaveragebitrate=16000;"
    #     "maxplaybackrate=16000;"
    #     "ptime=20;"
    #     "minptime=20;"
    #     "useinbandfec=0;"
    #     "usedtx=1\r\n"
    # )

    # answer.sdp = answer.sdp.replace(
    #     "m=audio 9 UDP/TLS/RTP/SAVPF 96 9 0 8",
    #     "m=audio 9 UDP/TLS/RTP/SAVPF 8"
    # )

    log.info("SDP offer:\n%s", answer.sdp)

    await pc.setLocalDescription(answer)
    await asyncio.sleep(0.5)

    log.info("SENDERS: %s", pc.getSenders())
    log.info("RECEIVERS: %s", pc.getReceivers())

    log.info("Nowe połączenie WebRTC [aktywne: %d]", len(pcs))
    return web.Response(
        content_type="application/json",
        text=json.dumps({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}),
    )


async def on_shutdown(app):
    global _audio_stream
    await asyncio.gather(*[pc.close() for pc in pcs])
    pcs.clear()
    if _audio_stream:
        _audio_stream.stop()
        _audio_stream.close()


def build_app():
    app = web.Application()
    app.on_shutdown.append(on_shutdown)
    app.router.add_post("/offer", offer)
    # app.router.add_static("/", path="static", show_index=True)
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True, expose_headers="*",
            allow_headers="*", allow_methods="*",
        )
    })
    for route in list(app.router.routes()):
        try: cors.add(route)
        except: pass
    return app


if __name__ == "__main__":
    log.info("Dostępne urządzenia audio:")
    for i, d in enumerate(sd.query_devices()):
        log.info("  [%d] %s (in=%d out=%d)",
                 i, d['name'], d['max_input_channels'], d['max_output_channels'])

    dev = _find_device()
    _start_audio(dev)

    if not os.path.exists(CERT_FILE):
        os.system(
            f'openssl req -x509 -newkey rsa:2048 -keyout {KEY_FILE} -out {CERT_FILE} '
            f'-days 3650 -nodes -subj "/CN=radio"'
        )
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(CERT_FILE, KEY_FILE)
    log.info("Serwer: https://%s:%d | %dHz | '%s'", HOST, PORT, SAMPLE_RATE, DEVICE_NAME)
    web.run_app(build_app(), host=HOST, port=PORT, ssl_context=ssl_ctx)