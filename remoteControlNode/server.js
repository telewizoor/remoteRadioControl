const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const net = require('net');
const config = require('./config');

const app = express();
const server = http.createServer(app);
const io = new Server(server);

// static
app.use(express.static('public'));

// constants from original
const cyclicRefreshParams = ['AG0', 'SQ0', 'RM0', 'PS', 'FA', 'FB', 'PC', 'AC', 'TX', 'RA0', 'PA0', 'VS', 'NB0', 'MD0', 'ML0'];

let rigSocket = null;
let connected = false;
let retryCnt = 0;
let pollInterval = config.POLL_MS;
let pollTimer = null;
let lastBuffer = '';

// helper: connect to rigctl
function connectRig() {
  if (rigSocket) {
    try { rigSocket.destroy(); } catch(e) {}
    rigSocket = null;
    connected = false;
  }

  rigSocket = new net.Socket();
  rigSocket.setTimeout(config.TCP_TIMEOUT_MS);

  rigSocket.on('connect', () => {
    connected = true;
    retryCnt = 0;
    console.log(`Connected to rig ${config.RIG_HOST}:${config.RIG_PORT}`);
  });

  rigSocket.on('timeout', () => {
    // just note it; we'll handle when reading
    // console.log('rig timeout');
  });

  rigSocket.on('error', (err) => {
    connected = false;
    // do not crash
    // console.log('rig error', err.message);
  });

  rigSocket.on('close', () => {
    connected = false;
    // try reconnect later
    // console.log('rig closed');
  });

  rigSocket.on('data', (data) => {
    lastBuffer += data.toString('utf8');
    // rig returns \n terminated chunks; we let polling read responses when we expect them
  });

  rigSocket.connect(config.RIG_PORT, config.RIG_HOST);
}

// send raw command (ensures newline)
function sendToRig(cmd, cb) {
  if (!connected || !rigSocket) {
    if (cb) cb(null);
    return;
  }
  if (!cmd.endsWith('\n')) cmd = cmd + '\n';
  try {
    rigSocket.write(cmd, 'ascii', cb);
  } catch (e) {
    if (cb) cb(null);
  }
}

// parse integer from string like "AG0123"
function parse_level_from_response_piece(piece) {
  const m = piece.match(/(-?\d+)/);
  if (!m) return null;
  const v = parseInt(m[1], 10);
  if (isNaN(v)) return null;
  return Math.max(0, Math.min(255, v));
}

// Polling: send aggregated "wAG0;SQ0;RM0;..." like original
function pollOnce() {
  if (!connected) {
    io.emit('status', `No connection to ${config.RIG_HOST}:${config.RIG_PORT}`);
    retryCnt++;
    if (retryCnt > config.MAX_RETRY_CNT) {
      pollInterval = config.SLOWER_POLL_MS;
      restartPolling();
    }
    return;
  }

  lastBuffer = ''; // reset accumulator for this poll
  const cmd = 'w' + cyclicRefreshParams.map(p => p + ';').join('');
  sendToRig(cmd, () => {
    // wait a bit then parse buffer (rig usually replies quickly)
    setTimeout(() => {
      const resp = lastBuffer.replace(/\x00/g,'').replace(/\r/g,'').replace(/\n/g,';');
      if (!resp || resp.length < 2) {
        io.emit('status', `No answer from ${config.RIG_HOST}:${config.RIG_PORT}`);
        retryCnt++;
        if (retryCnt > config.MAX_RETRY_CNT) {
          pollInterval = config.SLOWER_POLL_MS;
          restartPolling();
        }
        return;
      }

      retryCnt = 0;
      if (pollInterval !== config.POLL_MS) {
        pollInterval = config.POLL_MS;
        restartPolling();
      }

      const parts = resp.split(';').filter(Boolean);
      // create map key->value (take first matching piece)
      const map = {};
      for (const p of parts) {
        for (const key of cyclicRefreshParams) {
            if (p.startsWith(key)) {
                if (key === 'FA' || key === 'FB') {
                // częstotliwości: całe Hz
                const hz = parseInt(p.substring(2), 10);
                if (!isNaN(hz)) map[key] = hz;
                } else {
                const num = parse_level_from_response_piece(p);
                map[key] = num;
                }
                break;
            }
        }
      }

      // emit each key like original worker.result.emit(req, val)
      for (const key of cyclicRefreshParams) {
        if (map[key] !== undefined) {
          io.emit('value', { key, val: map[key] });
        }
      }

      io.emit('status', `Connected with ${config.RIG_HOST}:${config.RIG_PORT}`);
    }, 60);
  });
}

function restartPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(pollOnce, pollInterval);
}

// handle incoming socket.io from frontend
io.on('connection', (socket) => {
  console.log('client connected');
  socket.emit('status', connected ? `Connected with ${config.RIG_HOST}:${config.RIG_PORT}` : `Not connected`);
  // forward commands from frontend to rig
  socket.on('command', (cmd) => {
    // basic sanitization
    if (typeof cmd !== 'string') return;
    sendToRig(cmd);
    // small echo
    socket.emit('cmd_ack', cmd);
  });

  // pause polling (ms)
  socket.on('pause_polling', (ms) => {
    if (pollTimer) clearInterval(pollTimer);
    setTimeout(() => { restartPolling(); }, ms);
  });

  // request immediate poll
  socket.on('poll_now', () => pollOnce());
});

// start server + connect rig
server.listen(config.SERVER_PORT, () => {
  console.log(`HTTP server listening on port ${config.SERVER_PORT}`);
  connectRig();
  restartPolling();
});

// try reconnect if rig disconnected
setInterval(() => {
  if (!connected) {
    try {
      connectRig();
    } catch(e) {}
  }
}, 5000);
