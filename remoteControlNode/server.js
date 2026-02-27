// server.js
const express = require('express');
const net = require('net');
const path = require('path');
const https = require('https');
const fs = require('fs');
const { Server: SocketIO } = require('socket.io');

const app = express();

// Konfiguracja
const RIGCTLD_HOST   = '127.0.0.1';
const RIGCTLD_PORT   = 4532;
const WEB_PORT       = 443;
const TCP_TIMEOUT    = 1000;
const ANTENNA_SWITCH_HOST = '127.0.0.1';
const ANTENNA_SWITCH_PORT = 5000;
const POLL_INTERVAL_MS    = 500;

// Python WebRTC serwer (lokalnie na RPi)
const PYTHON_SERVER = 'https://127.0.0.1:8443';

app.use(express.json());
app.use(express.static('public'));

// ── TCP helpers ──────────────────────────────────────────────
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

function sendAntennaCommand(cmd) {
    return new Promise((resolve, reject) => {
        const client = new net.Socket();
        let data = '';
        client.setTimeout(1000);
        client.connect(ANTENNA_SWITCH_PORT, ANTENNA_SWITCH_HOST, () => { client.write(cmd); });
        client.on('data', (chunk) => { data += chunk.toString(); client.destroy(); });
        client.on('close', () => resolve(data.trim()));
        client.on('error', (err) => { client.destroy(); reject(err); });
        client.on('timeout', () => { client.destroy(); reject(new Error('Timeout')); });
    });
}

// ── Proxy do Python WebRTC serwera (tylko /offer, bez zmian) ─
app.post('/offer', async (req, res) => {
    try {
        const data = JSON.stringify(req.body);
        const options = {
            hostname: '127.0.0.1', port: 8443, path: '/offer', method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) },
            rejectUnauthorized: false,
        };
        const proxyReq = https.request(options, (proxyRes) => {
            let body = '';
            proxyRes.on('data', chunk => body += chunk);
            proxyRes.on('end', () => { res.setHeader('Content-Type', 'application/json'); res.send(body); });
        });
        proxyReq.on('error', (err) => {
            console.error('Błąd proxy do Python:', err.message);
            res.status(502).json({ error: 'Python WebRTC serwer niedostępny' });
        });
        proxyReq.write(data);
        proxyReq.end();
    } catch (err) {
        console.error('Offer proxy error:', err);
        res.status(500).json({ error: err.message });
    }
});
// ────────────────────────────────────────────────────────────

app.get('/', (req, res) => {
    res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

// ── HTTPS server + Socket.IO ─────────────────────────────────
const sslOptions = {
    key:  fs.readFileSync('key.pem'),
    cert: fs.readFileSync('cert.pem'),
};

const httpsServer = https.createServer(sslOptions, app);
const io = new SocketIO(httpsServer);

// ── Command handler ──────────────────────────────────────────
async function handleCommand(msg) {
    switch (msg.cmd) {
        case 'setFrequency':  await sendRigCommand(`F ${msg.frequency}`); break;
        case 'setMode':       await sendRigCommand(`M ${msg.mode} ${msg.width || 0}`); break;
        case 'setPTT':        await sendRigCommand(`T ${msg.state}`); break;
        case 'setLevel':      await sendRigCommand(`L ${msg.level} ${msg.value}`); break;
        case 'setFunc':       await sendRigCommand(`U ${msg.func} ${msg.value}`); break;
        case 'setAntenna':    await sendAntennaCommand(String(msg.antenna)); break;
        case 'bandUp':        await sendRigCommand('G BAND_UP'); break;
        case 'bandDown':      await sendRigCommand('G BAND_DOWN'); break;
        case 'vfoSwitch':     await sendRigCommand('G XCHG'); break;
        case 'vfoCopy':       await sendRigCommand('G CPY'); break;
        case 'setPowerstat':  await sendRigCommand(`\\set_powerstat ${msg.state}`); break;
        case 'setSplit':      await sendRigCommand(`S ${msg.state} ${msg.vfo}`); break;
        default: console.warn('Unknown command:', msg.cmd);
    }
}

io.on('connection', (socket) => {
    console.log(`Client connected: ${socket.id}`);
    socket.on('command', async (msg) => {
        try { await handleCommand(msg); }
        catch (err) { console.error('Command error:', err.message, msg); }
    });
    socket.on('disconnect', () => console.log(`Client disconnected: ${socket.id}`));
});

// ── State polling — alle 500ms, nur bei verbundenen Clients ──
function firstLine(settled) {
    if (settled.status === 'rejected') return null;
    return settled.value?.split('\n')[0]?.trim() ?? null;
}

async function pollState() {
    const settled = await Promise.allSettled([
        sendRigCommand('f'),                    // 0  active VFO freq
        sendRigCommand('m'),                    // 1  mode + width (2 lines)
        sendRigCommand('v'),                    // 2  active VFO name
        sendRigCommand('\\get_powerstat'),      // 3  power state
        sendRigCommand('l STRENGTH'),           // 4  S-meter (dBm)
        sendRigCommand('l AF'),                 // 5  volume (0-1)
        sendRigCommand('l SQL'),                // 6  squelch (0-1)
        sendRigCommand('u TUNER'),              // 7  tuner
        sendRigCommand('u NB'),                 // 8  noise blanker
        sendRigCommand('u MON'),                // 9  monitor
        sendRigCommand('l ATT'),                // 10 attenuator (dB)
        sendRigCommand('l PREAMP'),             // 11 preamp (dB)
        sendRigCommand('l IF'),                 // 12 IF shift (Hz)
        sendRigCommand('u MN'),                 // 13 manual notch enable
        sendRigCommand('l NOTCHF'),             // 14 notch freq (Hz)
        sendRigCommand('u NR'),                 // 15 noise reduction enable
        sendRigCommand('l NR'),                 // 16 NR level (0-1)
        sendRigCommand('l RFPOWER_METER'),      // 17 TX power meter (0-1)
        sendRigCommand('l RFPOWER'),            // 18 TX power set (0-1)
        sendRigCommand('\\get_vfo_info VFOB'),  // 19 VFO B info
        sendAntennaCommand('get'),              // 20 antenna switch
    ]);

    const v = (i) => firstLine(settled[i]);
    const modeLines  = settled[1].status === 'fulfilled' ? settled[1].value.split('\n') : [];
    const vfoBInfo   = settled[19].status === 'fulfilled' ? settled[19].value : '';
    const freqBMatch = vfoBInfo.match(/Freq: (-?\d+)/);

    io.emit('state', {
        frequency:    parseInt(v(0))          || 0,
        freqB:        freqBMatch ? parseInt(freqBMatch[1]) : 0,
        mode:         modeLines[0]?.trim()    || 'USB',
        width:        modeLines[1] ? parseInt(modeLines[1].trim()) : 0,
        vfo:          v(2)                    || 'VFOA',
        power:        parseInt(v(3))          || 0,
        strength:     parseFloat(v(4))        || -60,
        volume:       parseFloat(v(5))        || 0,
        squelch:      parseFloat(v(6))        || 0,
        tuner:        parseInt(v(7))          || 0,
        nb:           parseInt(v(8))          || 0,
        monitor:      parseInt(v(9))          || 0,
        att:          parseFloat(v(10))       || 0,
        preamp:       parseFloat(v(11))       || 0,
        shift:        parseInt(v(12))         || 0,
        notchEn:      parseInt(v(13))         || 0,
        notchFreq:    parseInt(v(14))         || 2000,
        nrEn:         parseInt(v(15))         || 0,
        nrLevel:      parseFloat(v(16))       || 0,
        rfpowerMeter: parseFloat(v(17))       || 0,
        rfpower:      parseFloat(v(18))       || 0,
        antenna:      settled[20].status === 'fulfilled' ? settled[20].value.trim() : null,
    });
}

setInterval(async () => {
    if (io.sockets.sockets.size === 0) return;
    try { await pollState(); }
    catch (err) { console.error('Poll error:', err.message); }
}, POLL_INTERVAL_MS);

httpsServer.listen(WEB_PORT, () => {
    console.log(`Web Radio Control: https://localhost:${WEB_PORT}`);
    console.log(`Proxy WebRTC → Python: ${PYTHON_SERVER}`);
    console.log(`State push via Socket.IO every ${POLL_INTERVAL_MS}ms`);
});