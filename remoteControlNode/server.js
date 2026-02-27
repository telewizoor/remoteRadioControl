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

// Track TX state — set when client sends setPTT
let txActive = false;

// ── Command handler ──────────────────────────────────────────
async function handleCommand(msg) {
    switch (msg.cmd) {
        case 'setFrequency':  await sendRigCommand(`F ${msg.frequency}`); break;
        case 'setMode':       await sendRigCommand(`M ${msg.mode} ${msg.width || 0}`); break;
        case 'setPTT':
            txActive = msg.state === 1;
            await sendRigCommand(`T ${msg.state}`);
            break;
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

// ── State polling ────────────────────────────────────────────
// Params safe to read during TX (fast-changing, rig won't glitch)
const TX_SAFE_CMDS = [
    { key: 'f',    cmd: () => sendRigCommand('f') },
    { key: 'm',    cmd: () => sendRigCommand('m') },
    { key: 'v',    cmd: () => sendRigCommand('v') },
    { key: 'pwr',  cmd: () => sendRigCommand('\\get_powerstat') },
    { key: 'str',  cmd: () => sendRigCommand('l STRENGTH') },
    { key: 'af',   cmd: () => sendRigCommand('l AF') },
    { key: 'sql',  cmd: () => sendRigCommand('l SQL') },
    { key: 'rfm',  cmd: () => sendRigCommand('l RFPOWER_METER') },
    { key: 'rfp',  cmd: () => sendRigCommand('l RFPOWER') },
    { key: 'ant',  cmd: () => sendAntennaCommand('get') },
];

// Params NOT safe during TX (DSP/config registers — rigctld returns 0 or garbage)
const RX_ONLY_CMDS = [
    { key: 'tuner',   cmd: () => sendRigCommand('u TUNER') },
    { key: 'nb',      cmd: () => sendRigCommand('u NB') },
    { key: 'mon',     cmd: () => sendRigCommand('u MON') },
    { key: 'att',     cmd: () => sendRigCommand('l ATT') },
    { key: 'preamp',  cmd: () => sendRigCommand('l PREAMP') },
    { key: 'shift',   cmd: () => sendRigCommand('l IF') },
    { key: 'notchEn', cmd: () => sendRigCommand('u MN') },
    { key: 'notchF',  cmd: () => sendRigCommand('l NOTCHF') },
    { key: 'nrEn',    cmd: () => sendRigCommand('u NR') },
    { key: 'nrLvl',   cmd: () => sendRigCommand('l NR') },
    { key: 'freqB',   cmd: () => sendRigCommand('\\get_vfo_info VFOB') },
];

function firstLine(settled) {
    if (settled.status === 'rejected') return null;
    return settled.value?.split('\n')[0]?.trim() ?? null;
}

// Cache for RX-only values — keep last known good values during TX
let rxCache = {};

async function pollState() {
    // Always query TX-safe params
    const txKeys  = TX_SAFE_CMDS.map(e => e.key);
    const txSettled = await Promise.allSettled(TX_SAFE_CMDS.map(e => e.cmd()));

    // Build partial state from TX-safe results
    const r = {};
    txKeys.forEach((k, i) => { r[k] = txSettled[i]; });

    const v = (settled) => {
        if (!settled || settled.status === 'rejected') return null;
        return settled.value?.split('\n')[0]?.trim() ?? null;
    };

    const modeLines = r.m?.status === 'fulfilled'
        ? (r.m.value?.split('\n') ?? []) : [];

    const state = {
        frequency:    parseInt(v(r.f))     || 0,
        mode:         modeLines[0]?.trim() || 'USB',
        width:        modeLines[1] ? parseInt(modeLines[1].trim()) : 0,
        vfo:          v(r.v)               || 'VFOA',
        power:        parseInt(v(r.pwr))   || 0,
        strength:     parseFloat(v(r.str)) || -60,
        volume:       parseFloat(v(r.af))  || 0,
        squelch:      parseFloat(v(r.sql)) || 0,
        rfpowerMeter: parseFloat(v(r.rfm)) || 0,
        rfpower:      parseFloat(v(r.rfp)) || 0,
        antenna:      r.ant?.status === 'fulfilled' ? (r.ant.value?.trim() ?? null) : null,
    };

    if (!txActive) {
        // Full RX poll — query DSP/config registers
        const rxKeys    = RX_ONLY_CMDS.map(e => e.key);
        const rxSettled = await Promise.allSettled(RX_ONLY_CMDS.map(e => e.cmd()));
        rxKeys.forEach((k, i) => {
            if (rxSettled[i].status === 'fulfilled') rxCache[k] = rxSettled[i];
        });
    }
    // Always use cache (last good RX values) for DSP fields
    const rc = rxCache;
    const cv = (k) => v(rc[k]);

    const vfoBInfo   = rc.freqB?.status === 'fulfilled' ? (rc.freqB.value ?? '') : '';
    const freqBMatch = vfoBInfo.match(/Freq: (-?\d+)/);

    state.freqB    = freqBMatch ? parseInt(freqBMatch[1]) : 0;
    state.tuner    = parseInt(cv('tuner'))   || 0;
    state.nb       = parseInt(cv('nb'))      || 0;
    state.monitor  = parseInt(cv('mon'))     || 0;
    state.att      = parseFloat(cv('att'))   || 0;
    state.preamp   = parseFloat(cv('preamp'))|| 0;
    state.shift    = parseInt(cv('shift'))   || 0;
    state.notchEn  = parseInt(cv('notchEn')) || 0;
    state.notchFreq= parseInt(cv('notchF'))  || 2000;
    state.nrEn     = parseInt(cv('nrEn'))    || 0;
    state.nrLevel  = parseFloat(cv('nrLvl')) || 0;

    io.emit('state', state);
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