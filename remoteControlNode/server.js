// server.js
const express = require('express');
const net = require('net');
const path = require('path');
const https = require('https');
const fs = require('fs');
const app = express();

// Konfiguracja
const RIGCTLD_HOST = '0.0.0.0';
const RIGCTLD_PORT = 4532;
const WEB_PORT = 443;
const TCP_TIMEOUT = 1000;
const ANTENNA_SWITCH_HOST = '0.0.0.0';
const ANTENNA_SWITCH_PORT = 5000;

// Python WebRTC serwer (lokalnie na RPi)
const PYTHON_SERVER = 'https://127.0.0.1:8443';

app.use(express.json());
app.use(express.static('public'));

// ── Proxy do Python WebRTC serwera ──────────────────────────
app.post('/offer', async (req, res) => {
    try {
        // Node.js nie ma fetch wbudowanego w starszych wersjach — użyj http/https
        const data = JSON.stringify(req.body);

        const options = {
            hostname: '127.0.0.1',
            port: 8443,
            path: '/offer',
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Content-Length': Buffer.byteLength(data),
            },
            // Ignoruj self-signed cert Pythona (lokalne połączenie)
            rejectUnauthorized: false,
        };

        const proxyReq = https.request(options, (proxyRes) => {
            let body = '';
            proxyRes.on('data', chunk => body += chunk);
            proxyRes.on('end', () => {
                res.setHeader('Content-Type', 'application/json');
                res.send(body);
            });
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

// HTTPS — wymagane dla WebRTC (mikrofon działa tylko na HTTPS)
const sslOptions = {
    key:  fs.readFileSync('key.pem'),
    cert: fs.readFileSync('cert.pem'),
};

require('https').createServer(sslOptions, app).listen(WEB_PORT, () => {
    console.log(`Web Radio Control: https://localhost:${WEB_PORT}`);
    console.log(`Proxy WebRTC → Python: ${PYTHON_SERVER}`);
});