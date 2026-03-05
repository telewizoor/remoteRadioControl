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

# ── Monkey-patch: Opus bitrate ────────────────────────────────
# aiortc hardkoduje bit_rate=96000 i ignoruje SDP fmtp / setParameters()
# (issue #1393). Jedyne pewne rozwiązanie to podmiana klasy enkodra.
OPUS_BITRATE = 32_000   # 32 kbps — niższy codec delay niż 16k, wciąż oszczędne

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
_playback_q    = queue.Queue(maxsize=8)   # 160 ms max (było 100=2s!)
_audio_stream  = None
_active_mics   = 0            # licznik aktywnych MicSink — gdy spadnie do 0 resetuj prefill

# Buforowanie odtwarzania — analogicznie jak w kliencie Python
PLAYBACK_PREFILL  = 1       # 1 blok = 20 ms (było 3=60ms)
PLAYBACK_FADE_LEN = 256     # próbki fade-out przy underrun
PLAYBACK_DRAIN_THRESHOLD = 4  # powyżej tej ilości bloków w kolejce → skipuj najstarsze

_pb_prefilled = False
_pb_last      = np.zeros(BLOCK_SIZE, dtype=np.float32)
_pb_fade_win  = np.linspace(1.0, 0.0, PLAYBACK_FADE_LEN, dtype=np.float32)

def _safe_async_put(aq, block):
    """Wywoływane w event loop przez call_soon_threadsafe — łapie QueueFull."""
    try:
        aq.put_nowait(block)
    except asyncio.QueueFull:
        pass


def _audio_callback(indata, outdata, frames, time_info, status):
    global _pb_prefilled

    if status:
        log.warning("audio: %s", status)

    # Broadcast capture do wszystkich aktywnych połączeń
    block = indata[:, 0].copy()
    with _lock:
        for (loop, aq) in _capture_subs:
            try:
                loop.call_soon_threadsafe(_safe_async_put, aq, block)
            except Exception:
                pass

    # Playback — prefill + adaptive drain + fade-out
    if not _pb_prefilled:
        if _playback_q.qsize() >= PLAYBACK_PREFILL:
            _pb_prefilled = True
        else:
            outdata[:, 0] = 0.0
            return

    # Adaptive drain: jeśli kolejka rośnie ponad próg, wyrzucaj najstarsze
    # żeby opóźnienie nie kumulowało się w nieskończoność
    while _playback_q.qsize() > PLAYBACK_DRAIN_THRESHOLD:
        try:
            _playback_q.get_nowait()
        except queue.Empty:
            break

    try:
        chunk = _playback_q.get_nowait()
        if len(chunk) < frames:
            chunk = np.pad(chunk, (0, frames - len(chunk)))
        samples = chunk[:frames].astype(np.float32)
        _pb_last[:frames] = samples
        outdata[:, 0] = samples
    except queue.Empty:
        # Łagodne wygaszenie zamiast skoku do zera — eliminuje trzaski
        fade = _pb_last.copy()
        apply_len = min(PLAYBACK_FADE_LEN, frames)
        fade[:apply_len] *= _pb_fade_win[:apply_len]
        fade[apply_len:]  = 0.0
        _pb_last[:]       = 0.0
        outdata[:, 0]     = fade[:frames]


def _start_audio(device_index: int):
    global _audio_stream
    _audio_stream = sd.Stream(
        device=(device_index, device_index),
        samplerate=SAMPLE_RATE,
        channels=(CHANNELS, CHANNELS),
        dtype=("int16", "float32"),
        blocksize=BLOCK_SIZE,
        latency='low',
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
        self._loop      = asyncio.get_event_loop()
        self._async_q   = asyncio.Queue(maxsize=8)   # 160 ms max (było 50=1s!)
        self._pts       = 0
        self._time_base = fractions.Fraction(1, SAMPLE_RATE)
        self._cnt       = 0
        # Zarejestruj w loop+queue w broadcast liście
        with _lock:
            _capture_subs.append((self._loop, self._async_q))
        log.info("RadioTrack: zarejestrowano (aktywne: %d)", len(_capture_subs))

    async def recv(self):
        # Czyste await na asyncio.Queue — żadnych wątków executor, możliwe do anulowania
        samples = await self._async_q.get()

        # Adaptive drain: jeśli kolejka rośnie, wyrzuć stare ramki
        while self._async_q.qsize() > 3:
            try:
                samples = self._async_q.get_nowait()
            except asyncio.QueueEmpty:
                break

        self._cnt += 1
        if self._cnt % 200 == 1:
            log.info("TX #%d peak=%d qsize=%d", self._cnt,
                     int(np.max(np.abs(samples))), self._async_q.qsize())

        frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = SAMPLE_RATE
        frame.pts         = self._pts
        frame.time_base   = self._time_base
        self._pts        += len(samples)
        return frame

    def stop(self):
        super().stop()
        # Wyrejestruj z broadcast listy
        with _lock:
            try:
                _capture_subs.remove((self._loop, self._async_q))
            except ValueError:
                pass
        log.info("RadioTrack: wyrejestrowano (aktywne: %d)", len(_capture_subs))


# ─────────────────────────────────────────────────────────────
# ODBIERANIE: WebRTC mic → playback
# ─────────────────────────────────────────────────────────────

class MicSink:

    def __init__(self):
        global _active_mics
        self._resampler = av.AudioResampler(format="fltp", layout="mono", rate=SAMPLE_RATE)
        self._active    = True
        with _lock:
            _active_mics += 1
        log.info("MicSink: nowy (aktywne: %d)", _active_mics)

    def addTrack(self, track):
        asyncio.ensure_future(self._run(track))

    async def _run(self, track):
        cnt = 0
        while self._active:
            try:
                frame = await track.recv()
                cnt += 1

                # Resample synchronicznie — szybkie, nie blokuje długo, bez executor
                for of in self._resampler.resample(frame):
                    samples = np.frombuffer(bytes(of.planes[0]), dtype=np.float32).copy()
                    try:
                        _playback_q.put_nowait(samples)
                    except queue.Full:
                        # Wyrzuca najstarszą ramkę żeby zrobić miejsce
                        try:
                            _playback_q.get_nowait()
                        except queue.Empty:
                            pass
                        _playback_q.put_nowait(samples)

                if cnt % 200 == 1:
                    log.info("RX mic #%d rate=%d fmt=%s samples=%d pq=%d",
                             cnt, frame.sample_rate, frame.format.name,
                             frame.samples, _playback_q.qsize())
            except Exception as e:
                log.warning("MicSink koniec: %s", e)
                break

    def stop(self):
        global _pb_prefilled, _active_mics
        self._active = False
        with _lock:
            _active_mics = max(0, _active_mics - 1)
            remaining = _active_mics
        log.info("MicSink: stop (pozostało: %d)", remaining)
        # Resetuj prefill i wyczyść kolejkę tylko gdy ostatni klient się rozłączył
        if remaining == 0:
            _pb_prefilled = False
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

    # Czekaj na pełne zebranie kandydatów ICE (ważne dla ZeroTier / niestandardowych interfejsów)
    if pc.iceGatheringState != "complete":
        gather_done = asyncio.Event()

        @pc.on("icegatheringstatechange")
        def on_gather():
            log.info("ICE gathering: %s", pc.iceGatheringState)
            if pc.iceGatheringState == "complete":
                gather_done.set()

        try:
            await asyncio.wait_for(gather_done.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            log.warning("ICE gathering timeout – wysyłam co jest")

    log.info("ICE candidates w odpowiedzi:\n%s",
             "\n".join(l for l in pc.localDescription.sdp.split("\n") if "candidate" in l))

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