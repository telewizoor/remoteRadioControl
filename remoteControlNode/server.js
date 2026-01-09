// server.js
const express = require('express');
const net = require('net');
const path = require('path');
const app = express();

// Konfiguracja
const RIGCTLD_HOST = '192.168.152.12';
const RIGCTLD_PORT = 4532;
const WEB_PORT = 3000;
const TCP_TIMEOUT = 100;

app.use(express.json());
app.use(express.static('public'));

// Funkcja do komunikacji z rigctld
function sendRigCommand(cmd) {
    return new Promise((resolve, reject) => {
        const client = new net.Socket();
        let data = '';

        client.setTimeout(TCP_TIMEOUT);

        client.connect(RIGCTLD_PORT, RIGCTLD_HOST, () => {
            if (!cmd.endsWith('\n')) {
                cmd = cmd + '\n';
            }
            client.write(cmd);
        });

        client.on('data', (chunk) => {
            data += chunk.toString();
            // Jeśli dostaliśmy RPRT lub koniec linii, zakończ
            if (data.includes('RPRT') || data.includes('\n')) {
                client.destroy();
            }
        });

        client.on('close', () => {
            resolve(data.trim());
        });

        client.on('error', (err) => {
            reject(err);
        });

        client.on('timeout', () => {
            client.destroy();
            resolve(data.trim() || null);
        });
    });
}

// API Endpoints

// Pobierz status zasilania
app.get('/api/powerstat', async (req, res) => {
    try {
        const result = await sendRigCommand('\\get_powerstat');
        const match = result.match(/Power Status: (\d+)/);
        const status = match ? parseInt(match[1]) : 0;
        res.json({ power: status });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Ustaw status zasilania
app.post('/api/powerstat', async (req, res) => {
    try {
        const { state } = req.body;
        await sendRigCommand(`\\set_powerstat ${state}`);
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Pobierz częstotliwość
app.get('/api/frequency', async (req, res) => {
    try {
        const result = await sendRigCommand('f');
        const freq = result.split('\n')[0].trim();
        res.json({ frequency: parseInt(freq) });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Ustaw częstotliwość
app.post('/api/frequency', async (req, res) => {
    try {
        const { frequency } = req.body;
        await sendRigCommand(`F ${frequency}`);
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Pobierz informacje o VFO
app.get('/api/vfo/:vfo', async (req, res) => {
    try {
        const vfo = req.params.vfo.toUpperCase();
        const result = await sendRigCommand(`\\get_vfo_info ${vfo}`);
        
        const freqMatch = result.match(/Freq: (-?\d+)/);
        const modeMatch = result.match(/Mode: (\w+)/);
        const widthMatch = result.match(/Width: (\d+)/);
        
        res.json({
            frequency: freqMatch ? parseInt(freqMatch[1]) : 0,
            mode: modeMatch ? modeMatch[1] : 'USB',
            width: widthMatch ? parseInt(widthMatch[1]) : 2400
        });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Pobierz aktywny VFO
app.get('/api/vfo', async (req, res) => {
    try {
        const result = await sendRigCommand('v');
        const vfo = result.split('\n')[0].trim();
        res.json({ vfo: vfo });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Przełącz VFO (A/B)
app.post('/api/vfo/switch', async (req, res) => {
    try {
        await sendRigCommand('G XCHG');
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Pobierz mode
app.get('/api/mode', async (req, res) => {
    try {
        const result = await sendRigCommand('m');
        const lines = result.split('\n');
        const mode = lines[0].trim();
        const width = lines[1] ? parseInt(lines[1].trim()) : 0;
        res.json({ mode, width });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Ustaw mode
app.post('/api/mode', async (req, res) => {
    try {
        const { mode, width } = req.body;
        await sendRigCommand(`M ${mode} ${width || 0}`);
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Zmiana pasma w górę
app.post('/api/band/up', async (req, res) => {
    try {
        await sendRigCommand('G BAND_UP');
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Zmiana pasma w dół
app.post('/api/band/down', async (req, res) => {
    try {
        await sendRigCommand('G BAND_DOWN');
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// A=B
app.post('/api/vfo/copy', async (req, res) => {
    try {
        await sendRigCommand('G CPY');
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// PTT
app.post('/api/ptt', async (req, res) => {
    try {
        const { state } = req.body;
        await sendRigCommand(`T ${state}`);
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Split
app.post('/api/split', async (req, res) => {
    try {
        const { state, vfo } = req.body;
        await sendRigCommand(`S ${state} ${vfo}`);
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Poziomy (Volume, Squelch, etc.)
app.get('/api/level/:level', async (req, res) => {
    try {
        const level = req.params.level;
        const result = await sendRigCommand(`l ${level}`);
        const lines = result.split('\n');
        const value = lines.length > 0 ? parseFloat(lines[0].trim()) : 0;
        res.json({ value });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.post('/api/level/:level', async (req, res) => {
    try {
        const level = req.params.level;
        const { value } = req.body;
        await sendRigCommand(`L ${level} ${value}`);
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Funkcje (Tuner, NB, etc.)
app.get('/api/func/:func', async (req, res) => {
    try {
        const func = req.params.func;
        const result = await sendRigCommand(`u ${func}`);
        const lines = result.split('\n');
        const value = lines.length > 0 ? parseInt(lines[0].trim()) : 0;
        res.json({ value });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.post('/api/func/:func', async (req, res) => {
    try {
        const func = req.params.func;
        const { value } = req.body;
        await sendRigCommand(`U ${func} ${value}`);
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// S-meter
app.get('/api/strength', async (req, res) => {
    try {
        const result = await sendRigCommand('l STRENGTH');
        const lines = result.split('\n');
        const value = lines.length > 0 ? parseInt(lines[0].trim()) : 0;
        res.json({ value });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// TX status
app.get('/api/tx', async (req, res) => {
    try {
        const result = await sendRigCommand('t');
        const match = result.match(/PTT: (\d+)/);
        const status = match ? parseInt(match[1]) : 0;
        res.json({ tx: status });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Serwowanie strony głównej
app.get('/', (req, res) => {
    res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

app.listen(WEB_PORT, () => {
    console.log(`Web Radio Control running on http://localhost:${WEB_PORT}`);
    console.log(`Connecting to rigctld at ${RIGCTLD_HOST}:${RIGCTLD_PORT}`);
});