#!/usr/bin/env python3
"""
WebRTC Audio Bridge
- One global sd.Stream duplex (device never occupied twice)
- Each connection has its own capture queue (no cross-contamination)
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
# aiortc hardcodes bit_rate=96000 and ignores SDP fmtp / setParameters()
OPUS_BITRATE = 32_000

import aiortc.codecs.opus as _opus_mod
import aiortc.codecs as _codecs_mod

_OrigOpusEncoder = _opus_mod.OpusEncoder

class _PatchedOpusEncoder(_OrigOpusEncoder):
    def __init__(self):
        super().__init__()
        self.codec.bit_rate = OPUS_BITRATE

_opus_mod.OpusEncoder = _PatchedOpusEncoder
_codecs_mod.OpusEncoder = _PatchedOpusEncoder
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

# ── Global audio engine ────────────────────────────────────
_lock            = threading.Lock()
_capture_subs    = []     # mutable list, modified under _lock
_capture_snap    = ()     # immutable tuple snapshot for lock-free callback
_playback_q      = queue.Queue(maxsize=24)
_audio_stream    = None
_active_mics     = 0      # counter of active MicSink

# Playback buffering
PLAYBACK_PREFILL         = 2    # blocks before starting playback (60 ms)
PLAYBACK_DRAIN_THRESHOLD = 30   # drain when queue exceeds this

_pb_prefilled = False

def _safe_async_put(aq, block):
    """Called in the event loop via call_soon_threadsafe — catches QueueFull."""
    try:
        aq.put_nowait(block)
    except asyncio.QueueFull:
        pass


def _audio_callback(indata, outdata, frames, time_info, status):
    global _pb_prefilled

    if status:
        log.warning("audio: %s", status)

    # ── Capture: broadcast to WebRTC clients (lock-free via snapshot) ──
    block = indata[:, 0].copy()
    for (loop, aq) in _capture_snap:    # tuple snapshot — no lock needed
        try:
            loop.call_soon_threadsafe(_safe_async_put, aq, block)
        except Exception:
            pass

    # ── Playback: feed USB audio device from mic queue ──
    if not _pb_prefilled:
        if _playback_q.qsize() >= PLAYBACK_PREFILL:
            _pb_prefilled = True
        else:
            outdata[:, 0] = 0.0
            return

    # Drain excess — max 2 per callback to avoid large audio jumps
    drained = 0
    while _playback_q.qsize() > PLAYBACK_DRAIN_THRESHOLD and drained < 2:
        try:
            _playback_q.get_nowait()
            drained += 1
        except queue.Empty:
            break

    try:
        chunk = _playback_q.get_nowait()
        n = min(len(chunk), frames)
        outdata[:n, 0] = chunk[:n]
        if n < frames:
            outdata[n:, 0] = 0.0
    except queue.Empty:
        outdata[:, 0] = 0.0


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
    raise RuntimeError(f"Device '{DEVICE_NAME}' not found. Available: {[d['name'] for d in sd.query_devices()]}")


pcs = set()


# ─────────────────────────────────────────────────────────────
# TRANSMITTING: own capture queue → WebRTC
# ─────────────────────────────────────────────────────────────

class RadioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self):
        super().__init__()
        self._loop      = asyncio.get_event_loop()
        self._async_q   = asyncio.Queue(maxsize=8)   # 160 ms max (was 50=1s!)
        self._pts       = 0
        self._time_base = fractions.Fraction(1, SAMPLE_RATE)
        self._cnt       = 0
        # Register in broadcast list + update lock-free snapshot
        global _capture_snap
        with _lock:
            _capture_subs.append((self._loop, self._async_q))
            _capture_snap = tuple(_capture_subs)
        log.info("RadioTrack: registered (active: %d)", len(_capture_subs))

    async def recv(self):
        # Pure await on asyncio.Queue — no executor threads, cancellable
        samples = await self._async_q.get()

        # Adaptive drain: if the queue grows, discard old frames
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
        # Unregister from broadcast list + update lock-free snapshot
        global _capture_snap
        with _lock:
            try:
                _capture_subs.remove((self._loop, self._async_q))
            except ValueError:
                pass
            _capture_snap = tuple(_capture_subs)
        log.info("RadioTrack: unregistered (active: %d)", len(_capture_subs))


# ─────────────────────────────────────────────────────────────
# RECEIVING: WebRTC mic → playback
# ─────────────────────────────────────────────────────────────

class MicSink:

    def __init__(self):
        global _active_mics
        self._resampler = av.AudioResampler(format="fltp", layout="mono", rate=SAMPLE_RATE)
        self._active    = True
        with _lock:
            _active_mics += 1
        log.info("MicSink: new (active: %d)", _active_mics)

    def addTrack(self, track):
        asyncio.ensure_future(self._run(track))

    async def _run(self, track):
        cnt = 0
        while self._active:
            try:
                frame = await track.recv()
                cnt += 1

                # Resample synchronously — fast, doesn't block long, no executor
                for of in self._resampler.resample(frame):
                    samples = np.frombuffer(bytes(of.planes[0]), dtype=np.float32).copy()
                    try:
                        _playback_q.put_nowait(samples)
                    except queue.Full:
                        pass  # drop new frame — callback drain keeps latency bounded

                if cnt % 200 == 1:
                    log.info("RX mic #%d rate=%d fmt=%s samples=%d pq=%d",
                             cnt, frame.sample_rate, frame.format.name,
                             frame.samples, _playback_q.qsize())
            except Exception as e:
                log.warning("MicSink ended: %s", e)
                break

    def stop(self):
        global _pb_prefilled, _active_mics
        self._active = False
        with _lock:
            _active_mics = max(0, _active_mics - 1)
            remaining = _active_mics
        log.info("MicSink: stop (remaining: %d)", remaining)
        # Reset prefill and clear queue only when the last client disconnects
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
            log.info("Mic received → USB Audio Device")
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

    # Wait for full ICE candidate gathering (important for ZeroTier / custom interfaces)
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
            log.warning("ICE gathering timeout – sending what we have")

    log.info("ICE candidates in response:\n%s",
             "\n".join(l for l in pc.localDescription.sdp.split("\n") if "candidate" in l))

    log.info("SENDERS: %s", pc.getSenders())
    log.info("RECEIVERS: %s", pc.getReceivers())

    log.info("New WebRTC connection [active: %d]", len(pcs))
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
    log.info("Available audio devices:")
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
    log.info("Server: https://%s:%d | %dHz | '%s'", HOST, PORT, SAMPLE_RATE, DEVICE_NAME)
    web.run_app(build_app(), host=HOST, port=PORT, ssl_context=ssl_ctx)