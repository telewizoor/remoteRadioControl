// server.js
const express  = require('express');
const net      = require('net');
const path     = require('path');
const https    = require('https');
const fs       = require('fs');
const WebSocket = require('ws');
const { spawn } = require('child_process');
const app = express();

// Konfiguracja
const RIGCTLD_HOST = '0.0.0.0';
const RIGCTLD_PORT = 4532;
const WEB_PORT = 443;
const TCP_TIMEOUT = 1000;
const ANTENNA_SWITCH_HOST = '0.0.0.0';
const ANTENNA_SWITCH_PORT = 5000;

// ── Audio bridge config ───────────────────────────────────────────
// Set AUDIO_DEVICE env var to override, e.g. AUDIO_DEVICE=hw:CARD=Device,DEV=0
const AUDIO_DEVICE  = process.env.AUDIO_DEVICE || 'hw:CARD=Device,DEV=0';
const AUDIO_RATE    = 48000;
const FRAME_SAMPLES = 960;          // 20 ms @ 48 kHz
const FRAME_BYTES   = FRAME_SAMPLES * 2;  // int16 mono
const OPUS_BITRATE  = 12000;        // 12 kbps — plenty for SSB voice
// ────────────────────────────────────────────────────────────────

app.use(express.json());
app.use(express.static('public'));

// Funkcja do komunikacji z rigctld
function sendRigCommand(cmd) {
    return new Promise((resolve, reject) => {
        const client = new net.Socket();
        let data = '';

        client.setTimeout(TCP_TIMEOUT);

        client.connect(RIGCTLD_PORT, RIGCTLD_HOST, () => {
            if (!cmd.endsWith('\n')) cmd = cmd + '\n';
            client.write(cmd);
        });

        client.on('data', (chunk) => {
            data += chunk.toString();
            if (data.includes('RPRT') || data.endsWith('\n')) client.destroy();
        });

        client.on('close', () => resolve(data.trim()));
        client.on('error', (err) => { client.destroy(); reject(err); });
        client.on('timeout', () => { client.destroy(); reject(new Error('Timeout')); });
    });
}

// API Endpoints (bez zmian)
app.get('/api/powerstat', async (req, res) => {
    try {
        const result = await sendRigCommand('\\get_powerstat');
        res.json({ power: parseInt(result.trim()) });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.post('/api/powerstat', async (req, res) => {
    try {
        await sendRigCommand(`\\set_powerstat ${req.body.state}`);
        res.json({ success: true });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.get('/api/frequency', async (req, res) => {
    try {
        const result = await sendRigCommand('f');
        res.json({ frequency: parseInt(result.split('\n')[0].trim()) });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.post('/api/frequency', async (req, res) => {
    try {
        await sendRigCommand(`F ${req.body.frequency}`);
        res.json({ success: true });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.get('/api/vfo/:vfo', async (req, res) => {
    try {
        const result = await sendRigCommand(`\\get_vfo_info ${req.params.vfo.toUpperCase()}`);
        const freqMatch = result.match(/Freq: (-?\d+)/);
        const modeMatch = result.match(/Mode: (\w+)/);
        const widthMatch = result.match(/Width: (\d+)/);
        res.json({
            frequency: freqMatch ? parseInt(freqMatch[1]) : 0,
            mode: modeMatch ? modeMatch[1] : 'USB',
            width: widthMatch ? parseInt(widthMatch[1]) : 2400
        });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.get('/api/vfo', async (req, res) => {
    try {
        const result = await sendRigCommand('v');
        res.json({ vfo: result.split('\n')[0].trim() });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.post('/api/vfo/switch', async (req, res) => {
    try { await sendRigCommand('G XCHG'); res.json({ success: true }); }
    catch (err) { res.status(500).json({ error: err.message }); }
});

app.get('/api/mode', async (req, res) => {
    try {
        const result = await sendRigCommand('m');
        const lines = result.split('\n');
        res.json({ mode: lines[0].trim(), width: lines[1] ? parseInt(lines[1].trim()) : 0 });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.post('/api/mode', async (req, res) => {
    try {
        await sendRigCommand(`M ${req.body.mode} ${req.body.width || 0}`);
        res.json({ success: true });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.post('/api/band/up', async (req, res) => {
    try { await sendRigCommand('G BAND_UP'); res.json({ success: true }); }
    catch (err) { res.status(500).json({ error: err.message }); }
});

app.post('/api/band/down', async (req, res) => {
    try { await sendRigCommand('G BAND_DOWN'); res.json({ success: true }); }
    catch (err) { res.status(500).json({ error: err.message }); }
});

app.post('/api/vfo/copy', async (req, res) => {
    try { await sendRigCommand('G CPY'); res.json({ success: true }); }
    catch (err) { res.status(500).json({ error: err.message }); }
});

app.post('/api/ptt', async (req, res) => {
    try { await sendRigCommand(`T ${req.body.state}`); res.json({ success: true }); }
    catch (err) { res.status(500).json({ error: err.message }); }
});

app.post('/api/split', async (req, res) => {
    try { await sendRigCommand(`S ${req.body.state} ${req.body.vfo}`); res.json({ success: true }); }
    catch (err) { res.status(500).json({ error: err.message }); }
});

app.get('/api/level/:level', async (req, res) => {
    try {
        const result = await sendRigCommand(`l ${req.params.level}`);
        res.json({ value: parseFloat(result.split('\n')[0].trim()) });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.post('/api/level/:level', async (req, res) => {
    try { await sendRigCommand(`L ${req.params.level} ${req.body.value}`); res.json({ success: true }); }
    catch (err) { res.status(500).json({ error: err.message }); }
});

app.get('/api/func/:func', async (req, res) => {
    try {
        const result = await sendRigCommand(`u ${req.params.func}`);
        res.json({ value: parseInt(result.split('\n')[0].trim()) });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.post('/api/func/:func', async (req, res) => {
    try { await sendRigCommand(`U ${req.params.func} ${req.body.value}`); res.json({ success: true }); }
    catch (err) { res.status(500).json({ error: err.message }); }
});

app.get('/api/strength', async (req, res) => {
    try {
        const result = await sendRigCommand('l STRENGTH');
        res.json({ value: parseInt(result.split('\n')[0].trim()) });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.get('/api/tx', async (req, res) => {
    try {
        const result = await sendRigCommand('t');
        const match = result.match(/PTT: (\d+)/);
        res.json({ tx: match ? parseInt(match[1]) : 0 });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

// ── Antenna switch ──────────────────────────────────────────
function sendAntennaCommand(cmd) {
    return new Promise((resolve, reject) => {
        const client = new net.Socket();
        let data = '';
        client.setTimeout(1000);
        client.connect(ANTENNA_SWITCH_PORT, ANTENNA_SWITCH_HOST, () => {
            client.write(cmd);
        });
        client.on('data', (chunk) => { data += chunk.toString(); client.destroy(); });
        client.on('close', () => resolve(data.trim()));
        client.on('error', (err) => { client.destroy(); reject(err); });
        client.on('timeout', () => { client.destroy(); reject(new Error('Timeout')); });
    });
}

app.get('/api/antenna', async (req, res) => {
    try {
        const result = await sendAntennaCommand('get');
        res.json({ antenna: result.trim() });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.post('/api/antenna', async (req, res) => {
    try {
        const result = await sendAntennaCommand(String(req.body.antenna));
        res.json({ success: true, response: result });
    } catch (err) { res.status(500).json({ error: err.message }); }
});
// ────────────────────────────────────────────────────────────

app.get('/', (req, res) => {
    res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

// ── WebSocket Audio Bridge ────────────────────────────────────────
const audioClients = new Set();
let captureProc  = null;
let playbackProc = null;
let captureBuf   = Buffer.alloc(0);

function setupAudioBridge(httpsServer) {
    let OpusEncoder, OpusDecoder;
    try {
        ({ OpusEncoder, OpusDecoder } = require('@discordjs/opus'));
    } catch (e) {
        console.warn('Audio bridge disabled — run: npm i @discordjs/opus');
        return;
    }

    const encoder = new OpusEncoder(AUDIO_RATE, 1, 2048);  // 2048 = OPUS_APPLICATION_VOIP
    encoder.setBitrate(OPUS_BITRATE);
    const decoder = new OpusDecoder(AUDIO_RATE, 1);

    // Capture: ALSA → raw PCM → encode Opus → broadcast to all WS clients
    captureProc = spawn('ffmpeg', [
        '-f', 'alsa', '-i', AUDIO_DEVICE,
        '-ar', String(AUDIO_RATE), '-ac', '1',
        '-f', 's16le', 'pipe:1'
    ], { stdio: ['ignore', 'pipe', 'pipe'] });
    captureProc.stderr.on('data', () => {});
    captureProc.on('error', (e) => console.error('Capture FFmpeg error:', e.message));

    captureProc.stdout.on('data', (chunk) => {
        captureBuf = Buffer.concat([captureBuf, chunk]);
        while (captureBuf.length >= FRAME_BYTES) {
            const frame = captureBuf.slice(0, FRAME_BYTES);
            captureBuf = captureBuf.slice(FRAME_BYTES);
            try {
                const opus = encoder.encode(frame);
                for (const ws of audioClients) {
                    if (ws.readyState === WebSocket.OPEN) ws.send(opus);
                }
            } catch (_) {}
        }
    });

    // Playback: receive Opus from any WS client → decode PCM → ALSA
    playbackProc = spawn('ffmpeg', [
        '-f', 's16le', '-ar', String(AUDIO_RATE), '-ac', '1', '-i', 'pipe:0',
        '-f', 'alsa', AUDIO_DEVICE
    ], { stdio: ['pipe', 'ignore', 'pipe'] });
    playbackProc.stderr.on('data', () => {});
    playbackProc.on('error', (e) => console.error('Playback FFmpeg error:', e.message));

    // WebSocket server — same HTTPS server, path /audio
    const wss = new WebSocket.Server({ server: httpsServer, path: '/audio' });

    wss.on('connection', (ws, req) => {
        console.log('Audio WS connected:', req.socket.remoteAddress);
        audioClients.add(ws);

        ws.on('message', (data) => {
            if (!playbackProc || playbackProc.killed) return;
            try {
                const pcm = decoder.decode(Buffer.from(data));
                playbackProc.stdin.write(pcm);
            } catch (_) {}
        });

        ws.on('close', () => {
            audioClients.delete(ws);
            console.log('Audio WS disconnected:', req.socket.remoteAddress);
        });
        ws.on('error', () => audioClients.delete(ws));
    });

    console.log(`Audio bridge: device=${AUDIO_DEVICE} rate=${AUDIO_RATE}Hz bitrate=${OPUS_BITRATE}bps`);
}
// ─────────────────────────────────────────────────────────────────

// HTTPS — wymagane dla WebRTC (mikrofon działa tylko na HTTPS)
const sslOptions = {
    key:  fs.readFileSync('key.pem'),
    cert: fs.readFileSync('cert.pem'),
};

const httpsServer = require('https').createServer(sslOptions, app);

setupAudioBridge(httpsServer);

httpsServer.listen(WEB_PORT, () => {
    console.log(`Web Radio Control: https://localhost:${WEB_PORT}`);
    console.log(`Audio WebSocket:    wss://localhost:${WEB_PORT}/audio`);
});