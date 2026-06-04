// State
let sessionsData = [];
let eventsData = [];
let failedLoginsData = [];
let refreshTimer = null;
let thumbTimer = null;
let msgTargetSession = null;
let msgAllMode = false;
let thumbsData = {};
let currentGridSize = 'medium';

// Tab switching
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('pane-' + tab.dataset.tab).classList.add('active');
    if (tab.dataset.tab === 'events') loadEvents();
    if (tab.dataset.tab === 'alerts') loadAlerts();
    if (tab.dataset.tab === 'recordings') loadRecordings();
  });
});

// Init
function init() {
  refreshAll();
  refreshTimer = setInterval(refreshAll, 5000);
  thumbTimer = setInterval(refreshThumbs, 3000);
  loadEvents();
  loadAlerts();
}

async function refreshAll() {
  await loadSessions();
  await loadStats();
  await loadSummary();
}

async function injectAgents() {
  toast('Injecting screenshot agents into all sessions...');
  try {
    const r = await fetch('/api/inject');
    const d = await r.json();
    toast('Injected ' + (d.launched ? d.launched.length : 0) + ' agents. Thumbnails will appear in ~10 seconds.');
  } catch (e) {
    toast('Injection failed. Make sure PsExec is in C:\\Users\\Administrator\\psexec.exe');
  }
}

async function refreshThumbs() {
  // With MJPEG streams, the browser handles continuous updates.
  // We only check if NEW sessions got agents so we can flip NO SIGNAL -> stream.
  try {
    const r = await fetch('/api/thumbs');
    const list = await r.json();
    thumbsData = {};
    list.forEach(t => { thumbsData[t.username.toLowerCase()] = t; });
    document.querySelectorAll('.cam-card').forEach(card => {
      const user = card.dataset.user.toLowerCase();
      const img = card.querySelector('.cam-thumb');
      const fallback = card.querySelector('.no-signal');
      if (img && thumbsData[user] && img.src.indexOf('/stream/') === -1) {
        // First time we see a thumb for this user, switch to MJPEG stream
        img.src = '/stream/' + card.dataset.user;
        img.style.display = 'block';
        if (fallback) fallback.style.display = 'none';
      }
    });
  } catch (e) {}
}

// Sessions
async function loadSessions() {
  try {
    const r = await fetch('/api/sessions');
    const newData = await r.json();
    const needsRebuild = needsGridRebuild(sessionsData, newData);
    sessionsData = newData;
    if (needsRebuild) {
      renderGrid(sessionsData);
    } else {
      updateGrid(sessionsData);
    }
    renderConnections(sessionsData);
    document.getElementById('stat-sessions').textContent = sessionsData.length;
    document.getElementById('tab-count-conn').textContent = sessionsData.length;
  } catch (e) {
    console.error('loadSessions error', e);
  }
}

function needsGridRebuild(oldList, newList) {
  if (oldList.length !== newList.length) return true;
  const oldIds = oldList.map(s => s.session_id).sort().join(',');
  const newIds = newList.map(s => s.session_id).sort().join(',');
  return oldIds !== newIds;
}

function renderGrid(list) {
  const container = document.getElementById('cctv-grid');
  const q = document.getElementById('grid-search').value.toLowerCase();
  const f = document.getElementById('grid-filter').value;
  const filtered = list.filter(s => {
    if (f !== 'all' && s.state !== f) return false;
    if (q) {
      const hay = (s.username + ' ' + s.session_id + ' ' + s.state).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  if (!filtered.length) {
    container.innerHTML = '<div class="empty">No sessions match filter.</div>';
    return;
  }

  container.innerHTML = filtered.map(s => buildCard(s)).join('');
  // Immediately try to load thumbs after render
  refreshThumbs();
}

function updateGrid(list) {
  const q = document.getElementById('grid-search').value.toLowerCase();
  const f = document.getElementById('grid-filter').value;
  list.forEach(s => {
    const card = document.querySelector(`.cam-card[data-sid="${s.session_id}"]`);
    if (!card) return;
    // Update text fields in place
    const dur = card.querySelector('.meta-duration');
    const idle = card.querySelector('.meta-idle');
    const ip = card.querySelector('.meta-ip');
    const state = card.querySelector('.session-id');
    const statusDot = card.querySelector('.cam-status');
    if (dur) dur.textContent = s.duration || '--';
    if (idle) idle.textContent = s.idle_time || '--';
    if (ip) ip.textContent = s.client_ip || 'N/A';
    if (state) state.textContent = s.state;
    if (statusDot) {
      statusDot.className = 'cam-status ' + s.state;
    }
  });
}

function buildCard(s) {
  const isLive = s.state === 'Active' || s.state === 'Idle';
  const hasThumb = thumbsData[s.username.toLowerCase()];
  const imgSrc = hasThumb ? `/stream/${s.username}` : '';
  return `
    <div class="cam-card ${isLive ? 'live' : 'offline'}" data-sid="${s.session_id}" data-user="${s.username}">
      <div class="cam-header">
        <div class="cam-user">
          <span class="cam-status ${s.state}"></span>
          ${s.username}
        </div>
        <div style="font-size:11px;color:var(--muted);font-family:var(--mono)">#${s.session_id}</div>
      </div>
      <div class="cam-body">
        <div class="cam-preview" onclick="openLightbox('${s.username}', '${s.session_id}')" style="cursor:pointer">
          <img class="cam-thumb" src="${imgSrc}" alt="" style="width:100%;height:100%;object-fit:cover;display:${hasThumb ? 'block' : 'none'};" onload="this.style.display='block';if(this.nextElementSibling)this.nextElementSibling.style.display='none';">
          <div class="no-signal" style="display:${hasThumb ? 'none' : 'flex'};flex-direction:column;align-items:center;justify-content:center;width:100%;height:100%;">
            <div>NO SIGNAL</div>
            <div style="font-size:10px;margin-top:4px;color:var(--muted)">Click Inject Agents</div>
          </div>
          ${isLive ? '<div class="live-tag">LIVE</div>' : ''}
          <div class="session-id">${s.state}</div>
        </div>
        <div class="cam-meta">
          <div>Duration: <span class="mono meta-duration">${s.duration || '--'}</span></div>
          <div>Idle: <span class="mono meta-idle">${s.idle_time || '--'}</span></div>
        </div>
        <div class="cam-meta">
          <div>Logon: <span class="mono">${s.logon_time || '--'}</span></div>
          <div>IP: <span class="mono meta-ip">${s.client_ip || 'N/A'}</span></div>
        </div>
        <div class="cam-actions">
          <button class="btn btn-primary" onclick="event.stopPropagation();shadowSession('${s.session_id}')" title="Take remote control">▶ Control</button>
          <button class="btn btn-info" onclick="event.stopPropagation();openMsg('${s.session_id}')" title="Send message">✉</button>
          <button class="btn btn-warn" onclick="event.stopPropagation();disconnectSession('${s.session_id}')" title="Disconnect">⏏</button>
          <button class="btn btn-danger" onclick="event.stopPropagation();logoffSession('${s.session_id}')" title="Logoff">✕</button>
        </div>
        <div class="cam-actions" style="margin-top:4px">
          <button class="btn" style="font-size:11px;background:var(--danger-dim);color:var(--danger);border-color:var(--danger)" onclick="event.stopPropagation();startRecording('${s.session_id}','${s.username}')">● Record</button>
          <button class="btn" style="font-size:11px" onclick="event.stopPropagation();disableUser('${s.username}')">Disable Account</button>
          <button class="btn" style="font-size:11px" onclick="event.stopPropagation();openNotes('${s.username}')">Notes</button>
        </div>
      </div>
    </div>
  `;
}

// Lightbox / Enlarged view
function openLightbox(username, sessionId) {
  const overlay = document.createElement('div');
  overlay.className = 'lightbox-overlay';
  overlay.innerHTML = `
    <div class="lightbox" onclick="event.stopPropagation()">
      <div class="lightbox-header">
        <strong>${username}</strong> — Session #${sessionId}
        <button class="btn btn-danger" onclick="this.closest('.lightbox-overlay').remove()" style="margin-left:auto">✕ Close</button>
      </div>
      <div class="lightbox-body">
        <img src="/preview/${username}" class="lightbox-img" onload="this.style.opacity=1" style="opacity:0;transition:opacity .3s">
      </div>
      <div class="lightbox-footer">
        <button class="btn btn-primary" onclick="shadowSession('${sessionId}')">▶ Take Control</button>
        <button class="btn btn-warn" onclick="disconnectSession('${sessionId}')">⏏ Disconnect</button>
        <button class="btn btn-danger" onclick="logoffSession('${sessionId}')">✕ Logoff</button>
        <button class="btn btn-info" onclick="openMsg('${sessionId}')">✉ Message</button>
      </div>
    </div>
  `;
  overlay.onclick = () => overlay.remove();
  document.body.appendChild(overlay);
}

function setGridSize(size) {
  currentGridSize = size;
  const container = document.getElementById('cctv-grid');
  container.classList.remove('size-small', 'size-medium', 'size-large');
  container.classList.add('size-' + size);
  // Re-render to apply new sizing
  renderGrid(sessionsData);
}

function renderConnections(list) {
  const tbody = document.querySelector('#connections-table tbody');
  const q = document.getElementById('conn-search').value.toLowerCase();
  const filtered = list.filter(s => {
    if (!q) return true;
    return (s.username + ' ' + s.state + ' ' + s.client_ip).toLowerCase().includes(q);
  });
  tbody.innerHTML = filtered.map(s => {
    const dot = s.state === 'Active' ? 'green' : (s.state === 'Idle' ? 'yellow' : 'gray');
    return `
      <tr>
        <td><span class="dot ${dot}"></span>${s.state}</td>
        <td><strong>${s.username}</strong></td>
        <td>${s.session_id}</td>
        <td>${s.logon_time || '--'}</td>
        <td>${s.duration || '--'}</td>
        <td>${s.idle_time || '--'}</td>
        <td>${s.client_ip || 'N/A'}</td>
        <td>
          <button class="btn btn-primary" onclick="shadowSession('${s.session_id}')">Control</button>
          <button class="btn btn-warn" onclick="disconnectSession('${s.session_id}')">Disc</button>
          <button class="btn btn-danger" onclick="logoffSession('${s.session_id}')">Logoff</button>
        </td>
      </tr>
    `;
  }).join('');
}

// Stats
async function loadStats() {
  try {
    const r = await fetch('/api/stats');
    const d = await r.json();
    document.getElementById('stat-cpu').textContent = (d.cpu || 0).toFixed(1) + '%';
    document.getElementById('stat-mem').textContent = (d.memory || 0).toFixed(1) + '%';
    document.getElementById('stat-disk').textContent = (d.disk || 0).toFixed(1) + '%';
    document.getElementById('stat-uptime').textContent = d.uptime || '--';
  } catch (e) {}
}

async function loadSummary() {
  try {
    const r = await fetch('/api/summary');
    const d = await r.json();
    const banner = document.getElementById('alert-banner');
    const txt = document.getElementById('alert-text');
    if (d.failed_logins > 0) {
      banner.classList.add('show');
      txt.textContent = `${d.failed_logins} failed login(s) in last 24h — ${d.connections} connections / ${d.disconnections} disconnections`;
    } else {
      banner.classList.remove('show');
    }
  } catch (e) {}
}

// Actions
const shadowing = new Set();
async function shadowSession(id) {
  if (shadowing.has(id)) { toast('Shadow already active for session ' + id); return; }
  shadowing.add(id);
  await fetch('/api/shadow/' + id);
  toast('Control window opened for session ' + id);
  setTimeout(() => shadowing.delete(id), 5000);
}
async function logoffSession(id) {
  if (!confirm('Logoff session ' + id + '?')) return;
  await fetch('/api/logoff/' + id);
  toast('Session logged off');
  loadSessions();
}
async function disconnectSession(id) {
  if (!confirm('Disconnect session ' + id + '?')) return;
  await fetch('/api/disconnect/' + id);
  toast('Session disconnected');
  loadSessions();
}
async function disableUser(user) {
  if (!confirm('DISABLE account ' + user + '?')) return;
  await fetch('/api/disable-user/' + user);
  toast('User ' + user + ' disabled');
}
async function enableUser(user) {
  await fetch('/api/enable-user/' + user);
  toast('User ' + user + ' enabled');
}

// Recording
async function startRecording(sessionId, username) {
  toast('Starting H.264 recording for ' + username + '...');
  try {
    const r = await fetch('/api/record/start/' + sessionId + '?username=' + encodeURIComponent(username));
    const d = await r.json();
    if (d.status === 'ok') {
      toast('Recording started: ' + d.filename);
    }
  } catch (e) {
    toast('Failed to start recording');
  }
}
async function stopRecording(username) {
  await fetch('/api/record/stop/' + username);
  toast('Recording stopped for ' + username);
}
async function loadRecordings() {
  try {
    const r = await fetch('/api/recordings');
    const list = await r.json();
    document.getElementById('tab-count-rec').textContent = list.length;
    const sizeR = await fetch('/api/recordings/size');
    const sizeD = await sizeR.json();
    document.getElementById('rec-size').textContent = sizeD.gb + ' GB';
    renderRecordings(list);
  } catch (e) { console.error(e); }
}
function renderRecordings(list) {
  const container = document.getElementById('recordings-list');
  if (!list.length) { container.innerHTML = '<div class="empty">No recordings yet. Click Inject Agents to auto-record all sessions.</div>'; return; }
  container.innerHTML = list.map(r => `
    <div class="event-row">
      <div class="event-time">${r.mtime}</div>
      <div class="event-badge login">MP4</div>
      <div style="min-width:100px"><strong>${r.username}</strong></div>
      <div style="min-width:80px;color:var(--muted)">${r.size_mb} MB</div>
      <div style="flex:1">
        <a href="/recording/${r.filename}" class="btn btn-primary" style="text-decoration:none" download>⬇ Download</a>
      </div>
    </div>
  `).join('');
}
async function runRetention() {
  if (!confirm('Delete all recordings and thumbs older than 7 days?')) return;
  try {
    const r = await fetch('/api/retention', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ days: 7 }) });
    const d = await r.json();
    toast(`Retention complete: freed ${d.deleted.mb_freed} MB (${d.deleted.recordings} recordings, ${d.deleted.thumbs} thumbs)`);
    loadRecordings();
  } catch (e) { toast('Retention failed'); }
}

// Messaging
function openMsg(sessionId) {
  msgTargetSession = sessionId;
  msgAllMode = false;
  document.getElementById('msg-title').textContent = 'Send Message to Session ' + sessionId;
  document.getElementById('msg-body').value = '';
  document.getElementById('msg-modal').classList.add('show');
}
function openMsgAll() {
  msgTargetSession = null;
  msgAllMode = true;
  document.getElementById('msg-title').textContent = 'Send Message to ALL Sessions';
  document.getElementById('msg-body').value = '';
  document.getElementById('msg-modal').classList.add('show');
}
function closeModal() {
  document.getElementById('msg-modal').classList.remove('show');
}
async function sendMsgConfirm() {
  const body = document.getElementById('msg-body').value;
  if (!body) return;
  if (msgAllMode) {
    await fetch('/api/msg-all', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: body }) });
    toast('Message sent to all sessions');
  } else {
    await fetch('/api/msg/' + msgTargetSession, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: body }) });
    toast('Message sent to session ' + msgTargetSession);
  }
  closeModal();
}

// Mass actions
async function massLogoffDisc() {
  const disc = sessionsData.filter(s => s.state === 'Disc' || s.state === 'Disconnected');
  if (!disc.length) { toast('No disconnected sessions'); return; }
  if (!confirm('Logoff ' + disc.length + ' disconnected session(s)?')) return;
  for (const s of disc) {
    await fetch('/api/logoff/' + s.session_id);
  }
  toast('Logged off ' + disc.length + ' sessions');
  loadSessions();
}

// Events
async function loadEvents() {
  const days = document.getElementById('log-days').value || 1;
  try {
    const r = await fetch('/api/logs?days=' + days);
    eventsData = await r.json();
    renderEvents(eventsData);
  } catch (e) { console.error(e); }
}
function renderEvents(list) {
  const q = document.getElementById('log-search').value.toLowerCase();
  const container = document.getElementById('events-list');
  const filtered = list.filter(e => {
    if (!q) return true;
    const hay = (e.Username + ' ' + e.IpAddress + ' ' + e.EventType).toLowerCase();
    return hay.includes(q);
  });
  if (!filtered.length) { container.innerHTML = '<div class="empty">No events.</div>'; return; }
  container.innerHTML = filtered.map(e => {
    const cls = e.EventType && e.EventType.includes('Login') ? 'login' :
                e.EventType && e.EventType.includes('Logoff') ? 'logoff' :
                e.EventType && e.EventType.includes('Disconnect') ? 'disconnect' : 'logoff';
    return `
      <div class="event-row">
        <div class="event-time">${e.TimeCreated}</div>
        <div class="event-badge ${cls}">${e.EventType || 'Event'}</div>
        <div style="min-width:100px"><strong>${e.Username || 'N/A'}</strong></div>
        <div style="min-width:120px;color:var(--muted)">${e.IpAddress || 'N/A'}</div>
        <div style="flex:1;color:var(--muted);font-size:12px">${e.Message ? e.Message.substring(0,120) : ''}</div>
      </div>
    `;
  }).join('');
}

// Alerts / Failed Logins
async function loadAlerts() {
  const days = document.getElementById('alert-days').value || 1;
  try {
    const r = await fetch('/api/failed-logins?days=' + days);
    failedLoginsData = await r.json();
    renderAlerts(failedLoginsData);
    document.getElementById('tab-count-alerts').textContent = failedLoginsData.length;
  } catch (e) { console.error(e); }
}
function renderAlerts(list) {
  const container = document.getElementById('alerts-list');
  if (!list.length) { container.innerHTML = '<div class="empty">No failed logins.</div>'; return; }
  container.innerHTML = list.map(a => `
    <div class="event-row">
      <div class="event-time">${a.TimeCreated}</div>
      <div class="event-badge failed">FAILED</div>
      <div style="min-width:100px"><strong>${a.Username || 'N/A'}</strong></div>
      <div style="min-width:120px;color:var(--muted)">${a.IpAddress || 'N/A'}</div>
      <div style="flex:1;color:var(--muted);font-size:12px">Reason: ${a.FailureReason || 'Unknown'}</div>
    </div>
  `).join('');
}

// Notes (mem0)
async function loadNotes() {
  const user = document.getElementById('note-username').value.trim();
  if (!user) { toast('Enter a username'); return; }
  try {
    const r = await fetch('/api/notes/' + user);
    const d = await r.json();
    const container = document.getElementById('notes-display');
    if (!d.notes || !d.notes.length) {
      container.innerHTML = '<div class="empty">No notes for ' + user + '</div>';
    } else {
      container.innerHTML = d.notes.map(n => `<div style="padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:6px;margin-bottom:8px;font-size:13px">${n}</div>`).join('');
    }
  } catch (e) { toast('Error loading notes'); }
}
async function saveNote() {
  const user = document.getElementById('note-username').value.trim();
  const note = document.getElementById('note-input').value.trim();
  if (!user || !note) { toast('Username and note required'); return; }
  try {
    await fetch('/api/notes/' + user, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note })
    });
    toast('Note saved to mem0');
    document.getElementById('note-input').value = '';
    loadNotes();
  } catch (e) { toast('Error saving note'); }
}
function openNotes(user) {
  document.getElementById('note-username').value = user;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelector('[data-tab="users"]').classList.add('active');
  document.getElementById('pane-users').classList.add('active');
  loadNotes();
}

// CSV Export
function exportConnectionsCSV() {
  const rows = sessionsData.map(s => [s.state, s.username, s.session_id, s.logon_time, s.duration, s.idle_time, s.client_ip].join(','));
  const csv = 'State,Username,SessionID,LogonTime,Duration,Idle,ClientIP\n' + rows.join('\n');
  downloadCSV(csv, 'rdp-sessions.csv');
}
function exportEventsCSV() {
  const rows = eventsData.map(e => [e.TimeCreated, e.EventType, e.Username, e.IpAddress, e.SessionId].join(','));
  const csv = 'Time,EventType,Username,IpAddress,SessionId\n' + rows.join('\n');
  downloadCSV(csv, 'rdp-events.csv');
}
function downloadCSV(csv, filename) {
  const blob = new Blob([csv], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
}

// Toast
function toast(msg) {
  const t = document.createElement('div');
  t.textContent = msg;
  t.style.cssText = 'position:fixed;bottom:18px;right:18px;background:var(--panel);color:var(--text);border:1px solid var(--border);padding:10px 14px;border-radius:8px;z-index:2000;font-size:13px;';
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3000);
}

// Search handlers
document.getElementById('grid-search').addEventListener('input', () => renderGrid(sessionsData));
document.getElementById('grid-filter').addEventListener('change', () => renderGrid(sessionsData));
document.getElementById('conn-search').addEventListener('input', () => renderConnections(sessionsData));
document.getElementById('log-search').addEventListener('input', () => renderEvents(eventsData));

// Start
init();
