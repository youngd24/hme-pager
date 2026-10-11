// Pager behaviour, modelled on the Motorola Advisor user manual (refdocs/advisor_inst.pdf).
// The server owns the message memory and settings; this file owns screens, buttons,
// timers, sounds and the LCD.
'use strict';

(() => {
  const COLS = 20;
  const ROWS = 4;
  const HOLD_MS = 1000;           // Function / On-Reset hold
  const SCREEN_MS = 4000;         // auto-scroll per screen
  const SINGLE_SCREEN_MS = 8000;  // a one-screen message stays up 8 s
  const MENU_TIMEOUT_MS = 8000;
  const EDIT_TIMEOUT_MS = 20000;
  const ALERT_MS = 12000;         // incoming-message symbol / alert length
  const REMINDER_MS = 120000;     // unread reminder beep
  const BACKLIGHT_MS = 15000;

  const $ = (sel) => document.querySelector(sel);
  const params = new URLSearchParams(location.search);

  // ------------------------------------------------------------------ logging

  function uilog(level, msg) {
    try {
      fetch('/api/log', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ level, msg }),
      }).catch(() => {});
    } catch (e) { /* nothing useful to do */ }
    if (level === 'error') console.error(msg);
  }
  window.addEventListener('error', (e) => uilog('error', `${e.message} at ${e.filename}:${e.lineno}:${e.colno}`));
  window.addEventListener('unhandledrejection', (e) => uilog('error', `unhandled rejection: ${e.reason}`));

  // ------------------------------------------------------------------ server state

  let S = { capcode: null, power: true, settings: {}, messages: [], status: {}, last_decode: null, log_file: null };

  const byId = (a, b) => a.id - b.id;
  const regular = () => S.messages.filter((m) => !m.personal).sort(byId);
  const personal = () => S.messages.filter((m) => m.personal).sort(byId);
  const findMsg = (id) => S.messages.find((m) => m.id === id);
  const hasUnread = () => S.messages.some((m) => !m.read);

  function applyState(st) {
    S = Object.assign({}, S, st);
    renderInfo();
    render();
  }

  async function api(action, body = {}) {
    const resp = await fetch('/api/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Object.assign({ action }, body)),
    });
    const data = await resp.json();
    if (data.state) applyState(data.state);
    if (!data.ok) throw new Error(data.error || 'ERROR');
    return data;
  }

  // ------------------------------------------------------------------ text helpers

  const pad2 = (n) => String(n).padStart(2, '0');
  const center = (s) => {
    s = s.slice(0, COLS);
    return ' '.repeat(Math.floor((COLS - s.length) / 2)) + s;
  };

  function fmtTime(d) {
    let h = d.getHours();
    const ap = h >= 12 ? 'PM' : 'AM';
    h = h % 12 || 12;
    return `${h}:${pad2(d.getMinutes())} ${ap}`;
  }
  const fmtDate = (d) => `${d.getMonth() + 1}/${d.getDate()}/${pad2(d.getFullYear() % 100)}`;

  // "  3:20 PM    6/14/91" like the bottom line of the Advisor's message screen
  function stampLine(d) {
    const left = '  ' + fmtTime(d);
    const right = fmtDate(d) + ' ';
    return left + ' '.repeat(Math.max(1, COLS - left.length - right.length)) + right;
  }

  function wrap(text, width = COLS) {
    const words = text.replace(/\s+/g, ' ').trim().split(' ');
    const lines = [];
    let cur = '';
    for (let word of words) {
      while (word.length > width) {
        if (cur) { lines.push(cur); cur = ''; }
        lines.push(word.slice(0, width));
        word = word.slice(width);
      }
      if (!word) continue;
      if (!cur) cur = word;
      else if (cur.length + 1 + word.length <= width) cur += ' ' + word;
      else { lines.push(cur); cur = word; }
    }
    if (cur) lines.push(cur);
    return lines.length ? lines : [''];
  }

  // A frame is 4 rows of text plus cells to blink or underline.
  class Frame {
    constructor() {
      this.rows = Array.from({ length: ROWS }, () => Array(COLS).fill(' '));
      this.blink = new Set();
      this.under = new Set();
    }
    put(r, c, text, { blink = false, under = false } = {}) {
      for (let i = 0; i < text.length && c + i < COLS; i++) {
        if (c + i < 0) continue;
        this.rows[r][c + i] = text[i];
        if (blink) this.blink.add(`${r},${c + i}`);
        if (under) this.under.add(`${r},${c + i}`);
      }
      return this;
    }
    line(r, text, opts) { return this.put(r, 0, text.padEnd(COLS).slice(0, COLS), opts); }
    clone() {
      const f = new Frame();
      f.rows = this.rows.map((row) => row.slice());
      f.blink = new Set(this.blink);
      f.under = new Set(this.under);
      return f;
    }
  }

  // ------------------------------------------------------------------ LCD renderer

  class LCD {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext('2d');
      this.frame = new Frame();
      this.blinkOn = true;
      this.backlight = false;
      this.blank = false;
      new ResizeObserver(() => this.resize()).observe(canvas);
      this.resize();
    }
    resize() {
      const dpr = window.devicePixelRatio || 1;
      const rect = this.canvas.getBoundingClientRect();
      this.canvas.width = Math.max(1, Math.round(rect.width * dpr));
      this.canvas.height = Math.max(1, Math.round(rect.height * dpr));
      this.draw();
    }
    show(frame) { this.frame = frame; this.draw(); }
    draw() {
      const { ctx, canvas } = this;
      const W = canvas.width;
      const H = canvas.height;
      // background: reflective LCD, or green-glowing when backlit
      let bg;
      if (this.backlight) {
        bg = ctx.createRadialGradient(W / 2, H / 2, H * 0.1, W / 2, H / 2, W * 0.65);
        bg.addColorStop(0, '#c8f7a6');
        bg.addColorStop(1, '#86d38a');
      } else {
        bg = ctx.createLinearGradient(0, 0, 0, H);
        bg.addColorStop(0, '#adcdb9');
        bg.addColorStop(1, '#9cbfaa');
      }
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, W, H);

      const dotsX = COLS * 6 - 1;          // 5 dots + 1 gap per char
      const dotsY = ROWS * 10 - 2;         // 8 dots (7 + underline) + 2 gap per row
      const margin = Math.min(W, H) * 0.07;
      const px = (W - 2 * margin) / dotsX;
      const py = (H - 2 * margin) / dotsY;
      const ox = (W - dotsX * px) / 2;
      const oy = (H - dotsY * py) / 2;
      const dw = px * 0.84;
      const dh = py * 0.84;

      const lit = [];
      ctx.fillStyle = this.backlight ? 'rgba(20, 70, 30, 0.025)' : 'rgba(25, 60, 45, 0.025)';
      for (let r = 0; r < ROWS; r++) {
        for (let c = 0; c < COLS; c++) {
          const key = `${r},${c}`;
          const hidden = this.blank || (this.frame.blink.has(key) && !this.blinkOn);
          const glyph = hidden ? null : glyphFor(this.frame.rows[r][c]);
          const under = !this.blank && this.frame.under.has(key);
          for (let x = 0; x < 5; x++) {
            for (let y = 0; y < 8; y++) {
              const on = y < 7 ? (glyph ? (glyph[x] >> y) & 1 : 0) : under;
              const cx = ox + (c * 6 + x) * px;
              const cy = oy + (r * 10 + y) * py;
              if (on) lit.push(cx, cy);
              else ctx.fillRect(cx, cy, dw, dh);   // faint "ghost" dot
            }
          }
        }
      }
      // liquid crystal casts a soft shadow onto the backplate
      ctx.fillStyle = 'rgba(0, 0, 0, 0.16)';
      for (let i = 0; i < lit.length; i += 2) ctx.fillRect(lit[i] + px * 0.35, lit[i + 1] + py * 0.4, dw, dh);
      ctx.fillStyle = this.backlight ? '#10261a' : '#17241f';
      for (let i = 0; i < lit.length; i += 2) ctx.fillRect(lit[i], lit[i + 1], dw, dh);
    }
  }

  const lcd = new LCD($('#lcd-canvas'));

  // ------------------------------------------------------------------ sound

  const sound = {
    ctx: null,
    nodes: [],
    unlock() {
      if (!this.ctx) {
        try { this.ctx = new (window.AudioContext || window.webkitAudioContext)(); }
        catch (e) { uilog('warn', `no Web Audio: ${e}`); return; }
      }
      if (this.ctx.state === 'suspended') this.ctx.resume();
      $('#sound-hint').hidden = true;
    },
    ready() { return this.ctx && this.ctx.state === 'running'; },
    beep(t, dur, vol, freq = 2900) {
      const c = this.ctx;
      const o = c.createOscillator();
      const g = c.createGain();
      o.type = 'square';
      o.frequency.value = freq;
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(vol, t + 0.004);
      g.gain.setValueAtTime(vol, t + dur - 0.004);
      g.gain.linearRampToValueAtTime(0, t + dur);
      o.connect(g).connect(c.destination);
      o.start(t);
      o.stop(t + dur + 0.01);
      this.nodes.push(o);
      o.onended = () => { this.nodes = this.nodes.filter((n) => n !== o); };
    },
    burst(t, vol) { for (let i = 0; i < 4; i++) this.beep(t + i * 0.1, 0.06, vol); },
    // Alert patterns from the manual. Lengths match; the beep cadence itself is a guess.
    play(name, { preview = false } = {}) {
      if (!this.ready()) {
        uilog('warn', `sound "${name}" not played: audio is locked until the page is clicked`);
        return;
      }
      const LOUD = 0.2;
      const SOFT = 0.03;
      const t0 = this.ctx.currentTime + 0.05;
      const patterns = {
        escalert: [12, null], loud_long: [12, LOUD], loud_short: [2, LOUD],
        soft_long: [12, SOFT], soft_short: [2, SOFT],
      };
      if (name in patterns) {
        let [secs, vol] = patterns[name];
        if (preview) secs = Math.min(secs, 2);
        for (let i = 0; i < secs; i++) {
          const v = vol !== null ? vol : SOFT + (LOUD - SOFT) * (i / Math.max(1, secs - 1));
          this.burst(t0 + i, v);
        }
      } else if (name === 'chirp') {
        this.beep(t0, 0.035, LOUD);
        this.beep(t0 + 0.07, 0.035, LOUD);
      } else if (name === 'reminder') {
        this.beep(t0, 0.08, SOFT * 2);
      } else if (name === 'powerup') {
        const notes = [1900, 2300, 2700, 3100];
        for (let i = 0; i < 16; i++) this.beep(t0 + i * 0.25, 0.12, 0.08, notes[i % 4]);
      }
    },
    stop() {
      for (const o of this.nodes) { try { o.stop(); } catch (e) { /* already stopped */ } }
      this.nodes = [];
    },
  };

  // ------------------------------------------------------------------ vibrate, lamp, backlight

  const pagerEl = $('#pager');
  const lampEl = $('#lamp');
  const lcdEl = $('#lcd');

  const vib = {
    timers: [],
    start(ms, delay = 0) {
      for (let t = delay; t < delay + ms; t += 900) {
        this.timers.push(setTimeout(() => pagerEl.classList.add('vibrating'), t));
        this.timers.push(setTimeout(() => pagerEl.classList.remove('vibrating'), t + 550));
      }
    },
    stop() {
      this.timers.forEach(clearTimeout);
      this.timers = [];
      pagerEl.classList.remove('vibrating');
    },
  };

  const lamp = {
    timer: null,
    flash(ms) {
      this.stop();
      let on = false;
      const end = Date.now() + ms;
      this.timer = setInterval(() => {
        on = !on && Date.now() < end;
        lampEl.classList.toggle('on', on);
        if (Date.now() >= end) this.stop();
      }, 250);
    },
    stop() {
      clearInterval(this.timer);
      this.timer = null;
      lampEl.classList.remove('on');
    },
  };

  let backlightTimer = null;
  function setBacklight(on) {
    lcd.backlight = on;
    lcdEl.classList.toggle('lit', on);
    clearTimeout(backlightTimer);
    if (on) backlightTimer = setTimeout(() => setBacklight(false), BACKLIGHT_MS);
    lcd.draw();
    uilog('debug', `backlight ${on ? 'on' : 'off'}`);
  }
  function bumpBacklight() {
    if (!lcd.backlight) return;
    clearTimeout(backlightTimer);
    backlightTimer = setTimeout(() => setBacklight(false), BACKLIGHT_MS);
  }

  // ------------------------------------------------------------------ alerts

  const alert = { active: false, timer: null };

  function startAlert(reason) {
    stopAlert();
    alert.active = true;
    const s = S.settings;
    if (s.speaker === 'audible') {
      sound.play(s.audible_alert);
    } else if (s.silent_alert === 'chirp_vibrate') {
      sound.play('chirp');
      vib.start(ALERT_MS, 300);
    } else if (s.silent_alert === 'vibrate') {
      vib.start(ALERT_MS);
    }
    lamp.flash(ALERT_MS);
    alert.timer = setTimeout(stopAlert, ALERT_MS);
    uilog('info', `alert (${reason}): ${s.speaker === 'audible' ? s.audible_alert : s.silent_alert}`);
    render();
  }

  function stopAlert() {
    if (!alert.active) return;
    alert.active = false;
    clearTimeout(alert.timer);
    sound.stop();
    vib.stop();
    lamp.stop();
    render();
  }

  // ------------------------------------------------------------------ screens

  let screen = null;
  let screenTimer = null;

  function go(next) {
    if (screen && screen.leave) screen.leave();
    screen = next;
    uilog('debug', `screen ${next.name}`);
    armTimeout();
    if (next.enter) next.enter();
    render();
  }

  function armTimeout() {
    clearTimeout(screenTimer);
    if (screen && screen.timeout) {
      screenTimer = setTimeout(() => (screen.onTimeout ? screen.onTimeout() : go(Idle())), screen.timeout);
    }
  }

  function render() {
    if (!screen) return;
    lcd.blank = screen.name === 'off';
    lcd.show(screen.render());
  }

  function Toast(text, next, ms = 1500, sub = '') {
    return {
      name: 'toast',
      timeout: ms,
      onTimeout: () => go(next()),
      render: () => new Frame().line(1, center(text)).line(2, center(sub)),
      key: () => go(next()),
    };
  }

  function Off() {
    return { name: 'off', render: () => new Frame(), key: () => {} };
  }

  function Boot() {
    const started = Date.now();
    let timer = null;
    return {
      name: 'boot',
      enter() {
        sound.play('powerup');
        timer = setTimeout(() => go(Idle()), 4000);
      },
      leave() { clearTimeout(timer); sound.stop(); },
      render() {
        const f = new Frame();
        if (Date.now() - started < 700) {
          for (let r = 0; r < ROWS; r++) f.line(r, ICON.BLOCK.repeat(COLS));
          return f;
        }
        f.line(1, center('VIRTUAL PAGER'));
        f.line(2, center(S.capcode ? `CAP ${String(S.capcode).padStart(7, '0')}` : 'NO CAPCODE SET'));
        return f;
      },
      key: () => go(Idle()),
    };
  }

  function Idle() {
    return {
      name: 'idle',
      render() {
        const f = new Frame();
        const now = new Date();
        // flashing ON = a message has been received but not read
        f.put(0, 0, ICON.ON, { blink: hasUnread() });
        if (alert.active) f.put(0, 2, ICON.ENVELOPE, { blink: true });
        if (S.settings.alarm_enabled) f.put(0, COLS - 1, ICON.BELL);
        if (!S.capcode) f.line(1, center('NO CAPCODE SET'));
        f.line(2, center(`${fmtTime(now)}   ${fmtDate(now)}`));
        if (S.settings.speaker === 'audible') f.put(3, 0, ICON.SPEAKER);
        return f;
      },
      key(k) {
        if (k === 'read') {
          if (!S.messages.length) go(Toast('NO MESSAGES', Idle));
          else go(Status());
        } else if (k === 'func') {
          go(Menu('global', { back: Idle }));
        }
      },
    };
  }

  // Memory-location screen: arrows show where messages are; flashing = unread.
  // Locations 1-10 on the top line, 11-19 on the second, the Personal Message
  // File in location 20 at the right end of the second line.
  function Status(selected) {
    const order = () => {
      const ids = regular().map((m) => m.id);
      if (personal().length) ids.push('P');
      return ids;
    };
    const pickDefault = () => {
      const reg = regular();
      if (reg.length) return reg[reg.length - 1].id;   // most recent
      return personal().length ? 'P' : null;
    };
    let sel = selected;
    const st = {
      name: 'status',
      timeout: MENU_TIMEOUT_MS,
      render() {
        const ids = order();
        if (!ids.includes(sel)) sel = pickDefault();
        if (sel === null) return new Frame().line(1, center('NO MESSAGES'));
        const f = new Frame();
        regular().forEach((m, i) => {
          const r = i < 10 ? 0 : 1;
          const c = (i % 10) * 2;
          f.put(r, c, m.locked ? ICON.LOCK : ICON.ARROW, { blink: !m.read, under: m.id === sel });
        });
        const pers = personal();
        if (pers.length) {
          f.put(1, 18, ICON.FOLDER, { blink: pers.some((m) => !m.read), under: sel === 'P' });
        }
        if (sel === 'P') {
          f.line(3, `PERSONAL FILE (${pers.length})`);
        } else {
          const m = findMsg(sel);
          const d = new Date(m.received);
          const slot = regular().findIndex((x) => x.id === sel) + 1;
          f.line(3, `${pad2(slot)} ${fmtTime(d).replace(' ', '')} ${fmtDate(d)}`);
          if (m.locked) f.put(3, COLS - 1, ICON.LOCK);
        }
        return f;
      },
      key(k) {
        const ids = order();
        let i = ids.indexOf(sel);
        if (k === 'left' && i > 0) sel = ids[i - 1];
        else if (k === 'right' && i < ids.length - 1) sel = ids[i + 1];
        else if (k === 'down' && personal().length) sel = 'P';
        else if (k === 'up' && sel === 'P') sel = pickDefault() === 'P' ? 'P' : regular().slice(-1)[0].id;
        else if (k === 'read') {
          if (sel === 'P') go(Reader(personal().map((m) => m.id), { personalFile: true }));
          else if (sel !== null) go(Reader([sel]));
          return;
        } else if (k === 'func') {
          if (sel !== null && sel !== 'P') go(Menu('message', { id: sel, back: () => Status(sel), parent: st }));
          else go(Menu('global', { back: Idle }));
          return;
        }
        render();
      },
    };
    return st;
  }

  // Message display: auto-scrolls a screen every 4 s; Read again switches to manual
  // (each Read = next screen), up/down scroll a line at a time.
  function Reader(ids, { personalFile = false } = {}) {
    let idx = 0;
    let line = 0;
    let manual = false;
    let autoTimer = null;

    const current = () => findMsg(ids[idx]);
    const linesFor = (m) => {
      let prefix;
      if (personalFile) prefix = `P${idx + 1}:`;
      else prefix = `${pad2(regular().findIndex((x) => x.id === m.id) + 1)}:`;
      if (m.locked) prefix = ICON.LOCK + prefix;
      const body = m.kind === 'tone' ? '(TONE ONLY)' : m.text;
      return [...wrap(`${prefix} ${body}`), stampLine(new Date(m.received))];
    };

    function markRead() {
      const m = current();
      if (m && !m.read) api('read', { id: m.id }).catch((e) => uilog('warn', `mark read failed: ${e.message}`));
    }

    function scheduleAuto() {
      clearTimeout(autoTimer);
      if (manual) return;
      const m = current();
      if (!m) return;
      const n = linesFor(m).length;
      const dwell = n <= ROWS && ids.length === 1 ? SINGLE_SCREEN_MS : SCREEN_MS;
      autoTimer = setTimeout(() => {
        if (line + ROWS < n) line += ROWS;
        else if (idx < ids.length - 1) { idx += 1; line = 0; markRead(); }
        else { go(Idle()); return; }
        armTimeout();
        render();
        scheduleAuto();
      }, dwell);
    }

    function goManual() {
      manual = true;
      clearTimeout(autoTimer);
    }

    const st = {
      name: 'message',
      timeout: MENU_TIMEOUT_MS + SINGLE_SCREEN_MS,
      get manual() { return manual; },
      currentId: () => ids[idx],
      enter() { markRead(); scheduleAuto(); },
      leave() { clearTimeout(autoTimer); },
      render() {
        const m = current();
        if (!m) return new Frame().line(1, center('MESSAGE GONE'));
        const lines = linesFor(m);
        const f = new Frame();
        for (let r = 0; r < ROWS; r++) f.line(r, lines[line + r] || '');
        return f;
      },
      key(k) {
        const m = current();
        if (!m) { go(Idle()); return; }
        const n = linesFor(m).length;
        if (k === 'read') {
          if (!manual) { goManual(); st.timeout = MENU_TIMEOUT_MS; }
          if (line + ROWS < n) line += ROWS;
          else if (idx < ids.length - 1) { idx += 1; line = 0; markRead(); }
          else { go(Status(personalFile ? 'P' : m.id)); return; }
        } else if (k === 'down') {
          goManual();
          if (line + ROWS < n) line += 1;
        } else if (k === 'up') {
          goManual();
          if (line > 0) line -= 1;
        } else if (k === 'left' || k === 'right') {
          const step = k === 'left' ? -1 : 1;
          if (personalFile) {
            const j = idx + step;
            if (j >= 0 && j < ids.length) { idx = j; line = 0; markRead(); }
          } else {
            const reg = regular();
            const j = reg.findIndex((x) => x.id === m.id) + step;
            if (j >= 0 && j < reg.length) { go(Reader([reg[j].id])); return; }
          }
          scheduleAuto();
        } else if (k === 'func') {
          go(Menu('message', { id: m.id, back: () => Status(personalFile ? 'P' : m.id), parent: st }));
          return;
        }
        render();
      },
    };
    return st;
  }

  // Function menu: symbols along the bottom line, the chosen one flashes.
  function Menu(context, { id = null, back, parent = null }) {
    const parentFrame = parent ? parent.render() : null;
    const items = () => {
      if (context === 'message') {
        const m = findMsg(id);
        if (!m) return [];
        const list = [
          { key: m.locked ? 'unlock' : 'lock', icon: ICON.LOCK, label: m.locked ? 'UNLOCK' : 'LOCK' },
          { key: 'delete', icon: ICON.TRASH, label: 'DELETE' },
        ];
        if (!m.personal) list.push({ key: 'file', icon: ICON.FOLDER, label: 'PERSONAL FILE' });
        return list;
      }
      const audible = S.settings.speaker === 'audible';
      return [
        { key: 'speaker', icon: audible ? ICON.SPEAKER : ICON.VIBRATE, label: audible ? 'SPEAKER: AUDIBLE' : 'SPEAKER: VIBRATE' },
        { key: 'alerts', icon: ICON.NOTE, label: 'ALERTS' },
        { key: 'clock', icon: ICON.CLOCK, label: 'CLOCK' },
        { key: 'alarm', icon: ICON.BELL, label: 'ALARM' },
        { key: 'setup', icon: ICON.GEAR, label: 'CAPCODE' },
      ];
    };
    let sel = 0;

    async function activate(item) {
      uilog('info', `function ${item.key}${id !== null ? ` on message ${id}` : ''}`);
      try {
        switch (item.key) {
          case 'speaker': {
            const next = S.settings.speaker === 'audible' ? 'silent' : 'audible';
            await api('settings', { value: { speaker: next } });
            if (next === 'audible') sound.play('chirp'); else vib.start(700);
            go(Toast(next === 'audible' ? 'AUDIBLE' : 'VIBRATE', Idle));
            break;
          }
          case 'alerts': go(AlertsEdit()); break;
          case 'clock': go(ClockView()); break;
          case 'alarm': go(AlarmEdit()); break;
          case 'setup': go(CapcodeEdit()); break;
          case 'lock':
          case 'unlock':
            await api(item.key, { id });
            go(Toast(item.key === 'lock' ? 'LOCKED' : 'UNLOCKED', back));
            break;
          case 'file':
            await api('file', { id });
            go(Toast('FILED', () => Status('P')));
            break;
          case 'delete':
            go(Confirm('DELETE?', async () => {
              await api('delete', { id });
              go(Toast('DELETED', () => Status()));
            }, back));
            break;
          default:
            break;
        }
      } catch (e) {
        go(Toast(e.message, back));
      }
    }

    return {
      name: 'menu',
      timeout: MENU_TIMEOUT_MS,
      render() {
        const list = items();
        const f = parentFrame ? parentFrame.clone() : back().render();
        f.blink.clear();
        f.under.clear();
        if (!list.length) return f.line(2, '').line(3, center('NO FUNCTIONS'));
        sel = Math.min(sel, list.length - 1);
        f.line(2, center(list[sel].label));
        const width = list.length * 2 - 1;
        const start = Math.floor((COLS - width) / 2);
        f.line(3, '');
        list.forEach((it, i) => f.put(3, start + i * 2, it.icon, { blink: i === sel }));
        return f;
      },
      key(k) {
        const list = items();
        if (k === 'left') sel = (sel - 1 + list.length) % list.length;
        else if (k === 'right') sel = (sel + 1) % list.length;
        else if (k === 'func') { if (list.length) activate(list[sel]); return; }
        else if (k === 'read' || k === 'up') { go(back()); return; }
        render();
      },
    };
  }

  function Confirm(question, onYes, back) {
    return {
      name: 'confirm',
      timeout: MENU_TIMEOUT_MS,
      onTimeout: () => go(back()),
      render: () => new Frame().line(1, center(question)).line(3, center('FUNCTION = YES')),
      key(k) {
        if (k === 'func') onYes().catch((e) => go(Toast(e.message, back)));
        else go(back());
      },
    };
  }

  const AUDIBLE = [
    ['escalert', 'ESCALERT'], ['loud_long', 'LOUD LONG'], ['loud_short', 'LOUD SHORT'],
    ['soft_long', 'SOFT LONG'], ['soft_short', 'SOFT SHORT'], ['chirp', 'CHIRP'], ['none', 'NO ALERT'],
  ];
  const SILENT = [['chirp_vibrate', 'CHIRP+VIBRATE'], ['vibrate', 'VIBRATE ONLY'], ['none', 'NO ALERT']];

  // Alerts: up/down = audible or silent, left/right = which alert, Function saves both.
  function AlertsEdit() {
    let cat = S.settings.speaker === 'audible' ? 0 : 1;
    const idx = [
      Math.max(0, AUDIBLE.findIndex(([k]) => k === S.settings.audible_alert)),
      Math.max(0, SILENT.findIndex(([k]) => k === S.settings.silent_alert)),
    ];
    const preview = () => {
      sound.stop();
      vib.stop();
      if (cat === 0) sound.play(AUDIBLE[idx[0]][0], { preview: true });
      else {
        const k = SILENT[idx[1]][0];
        if (k === 'chirp_vibrate') { sound.play('chirp'); vib.start(900, 300); }
        else if (k === 'vibrate') vib.start(900);
      }
    };
    return {
      name: 'alerts',
      timeout: EDIT_TIMEOUT_MS,
      leave() { sound.stop(); vib.stop(); },
      render() {
        const f = new Frame().line(0, 'ALERTS');
        f.put(1, 0, cat === 0 ? ICON.RIGHT : ' ').put(1, 1, 'AUD ');
        f.put(1, 5, AUDIBLE[idx[0]][1], { blink: cat === 0 });
        f.put(2, 0, cat === 1 ? ICON.RIGHT : ' ').put(2, 1, 'SIL ');
        f.put(2, 5, SILENT[idx[1]][1], { blink: cat === 1 });
        return f.line(3, center('FUNCTION = SAVE'));
      },
      async key(k) {
        if (k === 'up' || k === 'down') cat = 1 - cat;
        else if (k === 'left' || k === 'right') {
          const list = cat === 0 ? AUDIBLE : SILENT;
          idx[cat] = (idx[cat] + (k === 'left' ? -1 : 1) + list.length) % list.length;
          preview();
        } else if (k === 'func') {
          try {
            await api('settings', { value: { audible_alert: AUDIBLE[idx[0]][0], silent_alert: SILENT[idx[1]][0] } });
            go(Toast('SAVED', Idle));
          } catch (e) { go(Toast(e.message, Idle)); }
          return;
        } else if (k === 'read') { go(Idle()); return; }
        render();
      },
    };
  }

  // The app follows the PC clock, so this screen only shows it.
  function ClockView() {
    const DAYS = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
    const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
    return {
      name: 'clock',
      timeout: EDIT_TIMEOUT_MS,
      render() {
        const d = new Date();
        let h = d.getHours();
        const ap = h >= 12 ? 'PM' : 'AM';
        h = h % 12 || 12;
        return new Frame()
          .put(0, 0, ICON.CLOCK)
          .line(1, center(`${h}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())} ${ap}`))
          .line(2, center(`${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`))
          .line(3, center('SET FROM PC CLOCK'));
      },
      key: () => go(Idle()),
    };
  }

  // Alarm: left/right pick hour, minute, AM/PM, on/off; up/down change it.
  function AlarmEdit() {
    const s = S.settings;
    let h12 = (s.alarm_hour % 12) || 12;
    let min = s.alarm_minute;
    let pm = s.alarm_hour >= 12;
    let on = s.alarm_enabled;
    let field = 0;
    const FIELDS = [[0, 2], [3, 2], [6, 2], [10, 3]];   // offsets inside the alarm string
    const OFFSET = 4;
    return {
      name: 'alarm',
      timeout: EDIT_TIMEOUT_MS,
      render() {
        const text = `${String(h12).padStart(2, ' ')}:${pad2(min)} ${pm ? 'PM' : 'AM'}  ${on ? 'ON ' : 'OFF'}`;
        const f = new Frame().put(0, 0, ICON.BELL).put(0, 2, 'ALARM');
        f.put(1, OFFSET, text);
        const [fo, fl] = FIELDS[field];
        for (let i = 0; i < fl; i++) f.blink.add(`1,${OFFSET + fo + i}`);
        return f.line(3, center('FUNCTION = SAVE'));
      },
      async key(k) {
        if (k === 'left') field = (field + 3) % 4;
        else if (k === 'right') field = (field + 1) % 4;
        else if (k === 'up' || k === 'down') {
          const d = k === 'up' ? 1 : -1;
          if (field === 0) h12 = ((h12 - 1 + d + 12) % 12) + 1;
          else if (field === 1) min = (min + d + 60) % 60;
          else if (field === 2) pm = !pm;
          else on = !on;
        } else if (k === 'func') {
          const hour = (h12 % 12) + (pm ? 12 : 0);
          try {
            await api('settings', { value: { alarm_enabled: on, alarm_hour: hour, alarm_minute: min } });
            go(Toast(on ? 'ALARM ON' : 'ALARM OFF', Idle));
          } catch (e) { go(Toast(e.message, Idle)); }
          return;
        } else if (k === 'read') { go(Idle()); return; }
        render();
      },
    };
  }

  // Not on the real pager (its capcode was fixed): pick which capcode this one answers to.
  function CapcodeEdit() {
    const digits = String(S.capcode || 0).padStart(7, '0').split('').map(Number);
    let pos = 0;
    const OFFSET = 6;
    const value = () => Number(digits.join(''));
    return {
      name: 'capcode',
      timeout: EDIT_TIMEOUT_MS,
      render() {
        const f = new Frame().put(0, 0, ICON.GEAR).put(0, 2, 'CAPCODE');
        f.put(1, OFFSET, digits.join(''));
        f.blink.add(`1,${OFFSET + pos}`);
        f.under.add(`1,${OFFSET + pos}`);
        const v = value();
        // HME capcode = 3-digit base ID + (pager number x 8) as 4 digits
        if (v && (v % 10000) % 8 === 0) {
          f.line(2, center(`BASE ${String(Math.floor(v / 10000)).padStart(3, '0')} PAGER ${(v % 10000) / 8}`));
        }
        return f.line(3, center('FUNCTION = SAVE'));
      },
      async key(k) {
        if (k === 'left') pos = (pos + 6) % 7;
        else if (k === 'right') pos = (pos + 1) % 7;
        else if (k === 'up') digits[pos] = (digits[pos] + 1) % 10;
        else if (k === 'down') digits[pos] = (digits[pos] + 9) % 10;
        else if (k === 'func') {
          try {
            await api('capcode', { value: value() });
            go(Toast('SAVED', Idle, 1500, `CAP ${String(value()).padStart(7, '0')}`));
          } catch (e) { go(Toast(e.message, Idle)); }
          return;
        } else if (k === 'read') { go(Idle()); return; }
        render();
      },
    };
  }

  // Holding On/Reset shows PUSH FOR OFF; Function while it shows turns the pager off.
  function PushOff() {
    return {
      name: 'pushoff',
      timeout: 3000,
      render: () => new Frame().line(1, center('PUSH FOR OFF')),
      async key(k) {
        if (k !== 'func') { go(Idle()); return; }
        stopAlert();
        setBacklight(false);
        try { await api('power', { value: false }); } catch (e) { uilog('warn', `power off: ${e.message}`); }
        go(Off());
      },
    };
  }

  async function powerOn() {
    try { await api('power', { value: true }); } catch (e) { uilog('warn', `power on: ${e.message}`); }
    go(Boot());
  }

  // ------------------------------------------------------------------ input

  function press(k) {
    uilog('debug', `key ${k} on ${screen ? screen.name : '-'}`);
    sound.unlock();
    bumpBacklight();
    if (screen.name === 'off') {
      if (k === 'power' || k === 'power-hold') powerOn();
      return;
    }
    if (alert.active) {
      // any button cancels the alert; Read also opens the newest message
      stopAlert();
      if (k !== 'read') return;
      const reg = regular();
      if (reg.length) { go(Reader([reg[reg.length - 1].id])); return; }
    }
    if (k === 'func-hold') { setBacklight(!lcd.backlight); return; }
    if (k === 'power-hold') { go(PushOff()); return; }
    if (k === 'power') { go(Idle()); return; }   // reset
    armTimeout();
    screen.key(k);
  }

  const HOLDS = { func: 'func-hold', power: 'power-hold' };
  const held = {};

  function keyDown(k) {
    if (held[k]) return;
    held[k] = { fired: false, timer: null };
    document.querySelectorAll(`[data-key="${k}"]`).forEach((el) => el.classList.add('down'));
    if (HOLDS[k]) {
      held[k].timer = setTimeout(() => { held[k].fired = true; press(HOLDS[k]); }, HOLD_MS);
    } else {
      press(k);
    }
  }

  function keyUp(k) {
    const h = held[k];
    if (!h) return;
    delete held[k];
    document.querySelectorAll(`[data-key="${k}"]`).forEach((el) => el.classList.remove('down'));
    if (HOLDS[k]) {
      clearTimeout(h.timer);
      if (!h.fired) press(k);
    }
  }

  document.querySelectorAll('[data-key]').forEach((el) => {
    const k = el.dataset.key;
    el.addEventListener('pointerdown', (e) => { e.preventDefault(); el.setPointerCapture(e.pointerId); keyDown(k); });
    el.addEventListener('pointerup', () => keyUp(k));
    el.addEventListener('pointercancel', () => keyUp(k));
    el.addEventListener('contextmenu', (e) => e.preventDefault());
  });

  const KEYMAP = {
    Enter: 'read', ' ': 'read', f: 'func', F: 'func', o: 'power', O: 'power',
    ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down',
  };
  window.addEventListener('keydown', (e) => {
    const k = KEYMAP[e.key];
    if (!k || e.repeat || e.ctrlKey || e.altKey || e.metaKey) return;
    e.preventDefault();
    keyDown(k);
  });
  window.addEventListener('keyup', (e) => {
    const k = KEYMAP[e.key];
    if (k) keyUp(k);
  });
  window.addEventListener('pointerdown', () => sound.unlock());

  // ------------------------------------------------------------------ new pages, reminders, alarm

  function onNewPage(m) {
    uilog('info', `new page id=${m.id} on screen ${screen.name}`);
    if (screen.name === 'off') return;
    startAlert(`page ${m.id}`);
    const interruptible = ['idle', 'status', 'toast', 'boot'];
    if (interruptible.includes(screen.name) || (screen.name === 'message' && !screen.manual)) go(Idle());
  }

  setInterval(() => {
    if (screen.name !== 'off' && hasUnread() && S.settings.speaker === 'audible' && !alert.active) {
      uilog('debug', 'unread reminder beep');
      sound.play('reminder');
      lamp.flash(600);
    }
  }, REMINDER_MS);

  let lastAlarm = '';
  function checkAlarm() {
    const s = S.settings;
    if (!s.alarm_enabled || screen.name === 'off') return;
    const d = new Date();
    const stamp = `${d.toDateString()} ${d.getHours()}:${d.getMinutes()}`;
    if (d.getHours() === s.alarm_hour && d.getMinutes() === s.alarm_minute && lastAlarm !== stamp) {
      lastAlarm = stamp;
      startAlert('alarm');
      go(Toast('ALARM', Idle, ALERT_MS, fmtTime(d)));
    }
  }

  // blink phase and clock
  setInterval(() => {
    lcd.blinkOn = !lcd.blinkOn;
    if (lcd.blinkOn) checkAlarm();
    render();
  }, 500);

  // ------------------------------------------------------------------ info line under the pager

  function esc(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  function renderInfo() {
    const st = S.status || {};
    const cls = (v, good) => (v === good ? 'ok' : (String(v).startsWith('error') || v === 'missing' || v === 'exited' ? 'bad' : 'warn'));
    let cap = 'capcode <span class="bad">not set</span>';
    if (S.capcode) {
      const v = S.capcode;
      cap = `capcode ${String(v).padStart(7, '0')}`;
      if ((v % 10000) % 8 === 0) cap += ` (base ${String(Math.floor(v / 10000)).padStart(3, '0')}, pager ${(v % 10000) / 8})`;
    }
    const udp = st.udp_port ? `UDP :${st.udp_port}` : 'UDP';
    const from = st.sender ? ` from ${esc(st.sender)}` : '';
    $('#status-line').innerHTML =
      `${cap} · ${udp} <span class="${cls(st.udp, 'receiving')}">${esc(st.udp || '?')}</span>${from}` +
      ` · multimon-ng <span class="${cls(st.decoder, 'running')}">${esc(st.decoder || '?')}</span>` +
      ` · ${S.power ? 'on' : '<span class="warn">off</span>'}`;
    const d = S.last_decode;
    $('#decode-line').textContent = d
      ? `last decode ${new Date(d.time).toLocaleTimeString()}: ${d.capcode} fn ${d.function} ${d.kind} "${d.text}" → ${d.verdict}`
      : 'no decodes yet';
    $('#log-line').textContent = `vpager ${S.version || '?'}` + (S.log_file ? ` · log: ${S.log_file}` : '');
  }

  // ------------------------------------------------------------------ fit to window

  function fit() {
    const W = 760;
    const H = 540;
    const avail = Math.max(320, window.innerWidth - 32);
    const availH = Math.max(260, window.innerHeight - 170);
    const s = Math.min(avail / W, availH / H, 1.5);
    const fitEl = $('#fit');
    fitEl.style.width = `${W * s}px`;
    fitEl.style.height = `${H * s}px`;
    pagerEl.style.transform = `scale(${s})`;
  }
  window.addEventListener('resize', fit);
  fit();

  // ------------------------------------------------------------------ connect

  function connect() {
    const es = new EventSource('/api/events');
    es.addEventListener('open', () => uilog('info', 'event stream connected'));
    es.addEventListener('state', (e) => applyState(JSON.parse(e.data)));
    es.addEventListener('status', (e) => { S.status = JSON.parse(e.data); renderInfo(); });
    es.addEventListener('decode', (e) => { S.last_decode = JSON.parse(e.data); renderInfo(); });
    es.addEventListener('page', (e) => {
      const d = JSON.parse(e.data);
      applyState(d.state);
      onNewPage(d.message);
    });
    es.addEventListener('error', () => {
      $('#status-line').innerHTML = '<span class="bad">lost connection to vpager — retrying…</span>';
    });
  }

  // ?keys=read,right,read&step=600 presses buttons after load (for screenshots and testing)
  function runScriptedKeys() {
    const keys = (params.get('keys') || '').split(',').filter(Boolean);
    const step = params.has('step') ? Number(params.get('step')) : 600;
    const hit = (k) => { if (k.endsWith('-hold')) press(k); else { keyDown(k); keyUp(k); } };
    if (step === 0) keys.forEach(hit);   // all at once, before the first paint
    else keys.forEach((k, i) => setTimeout(() => hit(k), step * (i + 1)));
  }

  async function start() {
    try {
      const resp = await fetch('/api/state');
      applyState(await resp.json());
    } catch (e) {
      uilog('error', `could not load state: ${e}`);
    }
    go(S.power ? Idle() : Off());
    connect();
    runScriptedKeys();
    uilog('info', `page loaded (${navigator.userAgent})`);
  }

  start();
})();
