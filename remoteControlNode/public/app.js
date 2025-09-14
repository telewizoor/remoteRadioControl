const socket = io();

// state
let currentFreq = 14074000;
let activeVFO = 0; // 0 -> A
let txActive = 0;

// helper: safe send
function sendCmd(cmd) {
  socket.emit('command', cmd);
}

// receive values from server
socket.on('value', (data) => {
  const { key, val } = data;
  if (key === 'SQ0') {
    if (!knobSquelchObj.userActive) {
      knobSquelchObj.setValue(val);
    }
  } else if (key === 'AG0') {
    if (!knobVolumeObj.userActive) {
      knobVolumeObj.setValue(val);
    }
  } else if (key === 'RM0') {
    smeter.value = val;
    if (!txActive) {
      smeterLabel.textContent = smeterLabelFromVal(val);
    } else {
      smeterLabel.textContent = 'SWR ' + swrFromVal(val);
    }
  } else if (key === 'FA') {
    if (!activeVFO) {
      setFreqLabel(freqMain, val);
      currentFreq = val;
      vfoLabel.textContent = 'VFO A';
    } else {
      setFreqLabel(freqSub, val);
    }
  } else if (key === 'FB') {
    if (activeVFO) {
      setFreqLabel(freqMain, val);
      currentFreq = val;
      vfoLabel.textContent = 'VFO B';
    } else {
      setFreqLabel(freqSub, val);
    }
  } else if (key === 'PC') {
    txPowerBtn.textContent = (val || '') + 'W';
  } else if (key === 'VS') {
    activeVFO = val;
  } else if (key === 'RA0') {
    attBtn.style.background = val ? 'lightgreen' : 'lightgray';
  } else if (key === 'PA0') {
    ipoBtn.style.background = val ? 'lightgreen' : 'lightgray';
  } else if (key === 'AC') {
    tunerBtn.style.background = val ? 'lightgreen' : 'lightgray';
  } else if (key === 'TX') {
    txActive = val;
    if (val) document.body.style.backgroundColor = '#ffefdf';
    else document.body.style.backgroundColor = '';
  } else if (key === 'NB0') {
    nbBtn.style.background = val ? 'lightgreen' : 'lightgray';
  } else if (key === 'PS') {
    powerBtn.textContent = val ? 'OFF' : 'ON';
    powerBtn.style.background = val ? '#fa6060' : 'lightgray';
    powerIndicator.style.background = val ? 'lightgreen' : 'lightgray';
    powerIndicator.title = val ? 'Radio ON' : 'Radio OFF';
} else if (key === 'MD0') {
    // mode mapping
    const map = {1:'LSB',2:'USB',3:'CW',4:'FM',5:'AM',6:'DATA-L',7:'CW-R',8:'USER-L',9:'DATA-U'};
    if (map[val]) modeLabel.textContent = map[val];
  } else if (key === 'ML0') {
    monitorBtn.style.background = val ? 'lightgreen' : 'lightgray';
  }
});

// status
const statusBar = document.getElementById('statusBar');
socket.on('status', (s) => statusBar.textContent = s);

// elements
const powerIndicator = document.getElementById('powerIndicator');
const vfoLabel = document.getElementById('vfoLabel');
const modeLabel = document.getElementById('modeLabel');
const freqMain = document.getElementById('freqMain');
const freqSub = document.getElementById('freqSub');

const knobFreqEl = document.getElementById('knobFreq');
const knobFreqVal = document.getElementById('knobFreqVal');
const knobSquelchEl = document.getElementById('knobSquelch');
const knobSquelchVal = document.getElementById('knobSquelchVal');
const knobVolumeEl = document.getElementById('knobVolume');
const knobVolumeVal = document.getElementById('knobVolumeVal');

const powerBtn = document.getElementById('powerBtn');
const bandDownBtn = document.getElementById('bandDownBtn');
const bandUpBtn = document.getElementById('bandUpBtn');
const aEqBBtn = document.getElementById('aEqBBtn');
const vfoSwitchBtn = document.getElementById('vfoSwitchBtn');

const ipoAttBtn = document.getElementById('ipoAttBtn');
const splitBtn = document.getElementById('splitBtn');
const modeDownBtn = document.getElementById('modeDownBtn');
const modeUpBtn = document.getElementById('modeUpBtn');

const attBtn = document.getElementById('attBtn');
const ipoBtn = document.getElementById('ipoBtn');
const txPowerBtn = document.getElementById('txPowerBtn');
const nbBtn = document.getElementById('nbBtn');
const tunerBtn = document.getElementById('tunerBtn');
const monitorBtn = document.getElementById('monitorBtn');

const smeter = document.getElementById('smeter');
const smeterLabel = document.getElementById('smeterLabel');

// simple helpers for labels
function setFreqLabel(el, freq) {
  el.textContent = (freq/1000000).toFixed(6) + ' MHz';
}

function smeterLabelFromVal(val) {
  const table = [
    [0, "S0"],[20,"S1"],[40,"S3"],[53,"S4"],[75,"S5"],
    [88,"S6"],[110,"S7"],[155,"S9"],[165,"+10"],[190,"+20"],[220,"+40"],[255,"+60"]
  ];
  for (let [raw,label] of table) if (val === raw) return label;
  for (let i=0;i<table.length-1;i++){
    if (val >= table[i][0] && val <= table[i+1][0]) return table[i][1];
  }
  return "S?";
}

function swrFromVal(val) {
  if (val <= 127) {
    const swr = 1.0 + (val / 127.0) * 2.0;
    return swr.toFixed(1);
  } else {
    const swr = 3.0 + ((val - 127) / 128.0) * (99.9 - 3.0);
    return swr.toFixed(1);
  }
}

// Knob behaviour: emulate user_active, and send only after 500ms idle
class Knob {
  constructor(rangeEl, valueEl, opts) {
    this.el = rangeEl;
    this.valueEl = valueEl;
    this.userActive = false;
    this.timer = null;
    this.opts = opts || {};
    this.lastPos = parseInt(this.el.value, 10);
    this.el.addEventListener('input', (e)=>this._onInput(e));
    this.el.addEventListener('mouseup', ()=>this._onRelease());
    this.el.addEventListener('touchend', ()=>this._onRelease());
    // wheel support
    this.el.addEventListener('wheel', (e)=> {
      e.preventDefault();
      const delta = e.deltaY < 0 ? 1 : -1;
      let v = parseInt(this.el.value,10) + delta;
      if (v < parseInt(this.el.min)) v = this.el.max;
      if (v > parseInt(this.el.max)) v = this.el.min;
      this.el.value = v;
      this._onInput();
      this._startIdleTimer();
    }, {passive:false});
  }
  _onInput() {
    this.userActive = true;
    this.valueEl.textContent = this.el.value;
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(()=> this._onIdleAfterMove(), 500);
    if (this.opts.onChangeRealtime) this.opts.onChangeRealtime(parseInt(this.el.value,10));
  }
  _onRelease() {
    if (this.timer) clearTimeout(this.timer);
    this._onIdleAfterMove();
  }
  _startIdleTimer() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(()=> this._onIdleAfterMove(), 500);
  }
  _onIdleAfterMove() {
    this.userActive = false;
    if (this.opts.onIdle) this.opts.onIdle(parseInt(this.el.value,10));
  }
  setValue(v) {
    this.el.value = v;
    this.valueEl.textContent = v;
  }
}

const knobFreqObj = new Knob(knobFreqEl, knobFreqVal, {
  onIdle: (v) => {
    let newPos = v;
    let delta = newPos - knobFreqObj.lastPos;
    if (delta > 50) delta -= 100;
    if (delta < -50) delta += 100;
    knobFreqObj.lastPos = newPos;
    if (delta >= 0) delta = 1; else delta = -1;
    currentFreq += delta * 10;
    const cmd = `F ${currentFreq}`;
    sendCmd(cmd);
  }
});
knobFreqObj.lastPos = parseInt(knobFreqEl.value,10);

const knobSquelchObj = new Knob(knobSquelchEl, knobSquelchVal, {
  onIdle: (v) => {
    const cmd = `L SQL ${(v/255).toFixed(3)}`;
    sendCmd(cmd);
  }
});

const knobVolumeObj = new Knob(knobVolumeEl, knobVolumeVal, {
  onIdle: (v) => {
    const cmd = `L AF ${(v/255).toFixed(3)}`;
    sendCmd(cmd);
  }
});

// Buttons mapping
powerBtn.addEventListener('click', () => {
  const value = powerBtn.textContent === 'ON' ? 1 : 0;
  sendCmd(`\\set_powerstat ${value}`);
  socket.emit('pause_polling', 5000);
});

attBtn.addEventListener('click', () => {
  const active = attBtn.style.background === 'lightgreen';
  sendCmd(`wRA0${active ? 0 : 1};`);
});

ipoBtn.addEventListener('click', () => {
  const active = ipoBtn.style.background === 'lightgreen';
  sendCmd(`L PREAMP ${active ? 0 : 10};`);
});

ipoAttBtn.addEventListener('click', () => {
  // przykład: toggle między IPO i ATT
  if (ipoBtn.style.background === 'lightgreen') {
    sendCmd('U IPO 0');
    sendCmd('U ATT 1');
  } else {
    sendCmd('U ATT 0');
    sendCmd('U IPO 1');
  }
});

nbBtn.addEventListener('click', () => {
  const active = nbBtn.style.background === 'lightgreen';
  sendCmd(`U NB ${active ? 0 : 1}`);
});

monitorBtn.addEventListener('click', () => {
  const active = monitorBtn.style.background === 'lightgreen';
  sendCmd(`U MON ${active ? 0 : 1}`);
});

const pttBtn = document.getElementById('pttBtn');

function startPTT(e) {
  e.preventDefault();
  pttBtn.classList.add('active');
  sendCmd('T 1');
}

function stopPTT(e) {
  e.preventDefault();
  pttBtn.classList.remove('active');
  sendCmd('T 0');
}

// desktop
pttBtn.addEventListener('mousedown', startPTT);
pttBtn.addEventListener('mouseup', stopPTT);
pttBtn.addEventListener('mouseleave', stopPTT);

// mobile
pttBtn.addEventListener('touchstart', startPTT);
pttBtn.addEventListener('touchend', stopPTT);
pttBtn.addEventListener('touchcancel', stopPTT);

modeDownBtn.addEventListener('click', () => sendCmd('wMK8;'));
modeUpBtn.addEventListener('click', () => sendCmd('wMK7;'));
bandDownBtn.addEventListener('click', () => sendCmd('G BAND_DOWN'));
bandUpBtn.addEventListener('click', () => sendCmd('G BAND_UP'));
aEqBBtn.addEventListener('click', () => sendCmd('G CPY'));
vfoSwitchBtn.addEventListener('click', () => sendCmd('G XCHG'));

splitBtn.addEventListener('click', () => {
  if (splitBtn.classList.contains('active')) {
    splitBtn.classList.remove('active');
    splitBtn.style.background = 'lightgray';
    sendCmd('S 0 VFOA');
  } else {
    splitBtn.classList.add('active');
    splitBtn.style.background = 'lightgreen';
    sendCmd('S 1 VFOB');
  }
});

txPowerBtn.addEventListener('click', () => {
  const cur = parseInt(txPowerBtn.textContent.replace('W','')) || 50;
  const val = parseInt(prompt('Set TX power (1-100):', cur) || cur, 10);
  if (!isNaN(val)) {
    sendCmd(`L RFPOWER ${(val/100).toFixed(2)}`);
  }
});

// keyboard TX
document.addEventListener('keydown', (e) => {
  if (e.key === '\\') {
    sendCmd('T 1');
  }
});
document.addEventListener('keyup', (e) => {
  if (e.key === '\\') {
    sendCmd('T 0');
  }
});
