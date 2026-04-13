/* ------------------------------------------------------------------ */
/* AI-PA CRM — Dashboard JS                                             */
/* ------------------------------------------------------------------ */

let currentPage = 'inbox';
let allContacts = [];
let contactTypes = []; // loaded from /api/meta
let activeFilter = 'all';
let pollInterval = null;
let currentApprovalId = null;

// ------------------------------------------------------------------ //
// Init
// ------------------------------------------------------------------ //

document.addEventListener('DOMContentLoaded', async () => {
  await loadMeta();   // types must be ready before contacts render
  loadStatus();
  loadApprovals();
  loadContacts();

  // Poll inbox every 5s
  pollInterval = setInterval(() => {
    if (currentPage === 'inbox') loadApprovals();
    loadStatus();
  }, 5000);

  // Chat input: send on Enter
  document.getElementById('chatInput').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
  });

  // CRM search
  document.getElementById('crmSearch').addEventListener('input', e => {
    renderContacts(e.target.value);
  });
});

// ------------------------------------------------------------------ //
// Meta / config
// ------------------------------------------------------------------ //

async function loadMeta() {
  try {
    const meta = await api('/api/meta');
    contactTypes = meta.contacts || [];
  } catch (_) {
    contactTypes = [
      { type: 'corporate',   label: 'Corporate' },
      { type: 'residential', label: 'Residential' },
      { type: 'lead',        label: 'Lead' },
    ];
  }
  renderFilterChips();
}

function renderFilterChips() {
  const row = document.getElementById('filterRow');
  const chips = [
    { filter: 'all', label: 'All' },
    ...contactTypes.map(t => ({ filter: t.type, label: t.label })),
    { filter: 'urgent', label: 'Urgent' },
  ];
  row.innerHTML = chips.map((c, i) =>
    `<button class="filter-chip${i === 0 ? ' active' : ''}" data-filter="${c.filter}">${esc(c.label)}</button>`
  ).join('');
  row.querySelectorAll('.filter-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      row.querySelectorAll('.filter-chip').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeFilter = btn.dataset.filter;
      renderContacts(document.getElementById('crmSearch').value);
    });
  });
}

// ------------------------------------------------------------------ //
// Navigation
// ------------------------------------------------------------------ //

function showPage(page, btn) {
  // Desktop shows all 3 columns simultaneously — nav is hidden
  if (window.innerWidth >= 768) return;

  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(`page-${page}`).classList.add('active');
  btn.classList.add('active');
  currentPage = page;

  if (page === 'inbox') loadApprovals();
  if (page === 'crm') renderContacts('');
}

// ------------------------------------------------------------------ //
// Status
// ------------------------------------------------------------------ //

async function loadStatus() {
  try {
    const data = await api('/api/status');
    const dot = document.getElementById('statusDot');
    dot.className = 'status-dot ' + (data.bridge === 'running' ? 'running' : 'stopped');
    document.getElementById('businessName').textContent = data.business || 'Dashboard';
    const count = data.pending_approvals || 0;
    // Mobile nav badge
    const badge = document.getElementById('inboxBadge');
    badge.textContent = count;
    badge.style.display = count > 0 ? 'inline' : 'none';
    // Desktop column badge
    const colBadge = document.getElementById('inboxColBadge');
    colBadge.textContent = count;
    colBadge.style.display = count > 0 ? 'inline' : 'none';
  } catch (_) {}
}

// ------------------------------------------------------------------ //
// Inbox
// ------------------------------------------------------------------ //

async function loadApprovals() {
  const list = document.getElementById('approvalList');
  try {
    const approvals = await api('/api/approvals');
    if (!approvals.length) {
      list.innerHTML = `
        <div class="empty">
          <div class="icon">✅</div>
          <p>No pending approvals</p>
        </div>`;
      return;
    }
    list.innerHTML = approvals.map(a => approvalCard(a)).join('');
  } catch (e) {
    list.innerHTML = `<div class="empty"><p>Could not load approvals</p></div>`;
  }
}

function approvalCard(a) {
  const initials = (a.sender_name || '?').split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();
  const isNew = (a.analysis || '').includes('New contact') || (a.analysis || '').includes('new contact');
  const badge = isNew
    ? `<span class="badge badge-new">New Lead</span>`
    : `<span class="badge badge-client">Known</span>`;
  const channelIcon = { telegram: '📱', whatsapp: '💬', email: '📧' }[a.channel] || '💬';

  return `
    <div class="card ${isNew ? 'warning' : ''}" onclick="openApproval('${a.id}')">
      <div class="card-header">
        <div class="avatar">${initials}</div>
        <div class="card-meta">
          <div class="card-name">${esc(a.sender_name || a.identifier)}</div>
          <div class="card-sub">${channelIcon} ${esc(a.identifier)} ${badge}</div>
        </div>
        <div class="card-time">${a.time_ago}</div>
      </div>
      <div class="card-body">
        <div class="card-preview">${esc(a.original_message)}</div>
      </div>
    </div>`;
}

async function openApproval(id) {
  currentApprovalId = id;
  const a = await api(`/api/approvals/${id}`);
  const content = document.getElementById('approvalPanelContent');
  const actions = document.getElementById('approvalActions');

  content.innerHTML = `
    <div class="panel-title">${esc(a.sender_name || a.identifier)}</div>
    <div class="panel-subtitle">${esc(a.identifier)} · ${esc(a.channel)} · ${a.time_ago}</div>

    <div class="section-label">Their message</div>
    <div class="message-bubble">${esc(a.original_message)}</div>

    <div class="section-label">AI analysis <span style="font-weight:400;text-transform:none;letter-spacing:0">(tap to expand)</span></div>
    <details>
      <summary style="cursor:pointer;font-size:0.85rem;color:var(--primary);margin-bottom:8px">Show analysis</summary>
      <div class="analysis-box">${esc(a.analysis)}</div>
    </details>

    <div class="section-label">Draft reply</div>
    <textarea class="draft-edit" id="draftText">${esc(a.draft)}</textarea>

    <div class="section-label">Edit instructions</div>
    <input type="text" id="editInstructions" placeholder="e.g. Make it shorter, add pricing…"
      style="width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:8px;font-size:0.875rem;font-family:inherit;outline:none;margin-bottom:4px">
    <button class="btn btn-ghost" style="width:100%;margin-top:6px" onclick="editDraft()">✏️ Regenerate draft</button>
  `;

  actions.innerHTML = `
    <button class="btn btn-danger"  onclick="rejectApproval()">❌ Reject</button>
    <button class="btn btn-success" onclick="acceptApproval()" style="grid-column:span 2">✅ Send reply</button>
  `;

  openPanel('approval');
}

async function acceptApproval() {
  const draft = document.getElementById('draftText').value.trim();
  if (!draft) { toast('Draft is empty'); return; }

  // Save any edits to draft first
  await api(`/api/approvals/${currentApprovalId}/draft`, 'POST', { draft });

  setActionsLoading(true);
  try {
    await api(`/api/approvals/${currentApprovalId}/accept`, 'POST');
    toast('✅ Reply sent!');
    closePanel('approval');
    loadApprovals();
  } catch (e) {
    toast('Failed to send — check logs');
  } finally {
    setActionsLoading(false);
  }
}

async function rejectApproval() {
  await api(`/api/approvals/${currentApprovalId}/reject`, 'POST');
  toast('Rejected');
  closePanel('approval');
  loadApprovals();
}

async function editDraft() {
  const instructions = document.getElementById('editInstructions').value.trim();
  if (!instructions) { toast('Enter edit instructions first'); return; }

  const btn = event.target;
  btn.disabled = true;
  btn.textContent = 'Thinking…';

  try {
    const result = await api(`/api/approvals/${currentApprovalId}/edit`, 'POST', { instructions });
    document.getElementById('draftText').value = result.draft;
    document.getElementById('editInstructions').value = '';
    toast('Draft updated');
  } catch (e) {
    toast('Failed to regenerate');
  } finally {
    btn.disabled = false;
    btn.textContent = '✏️ Regenerate draft';
  }
}

function setActionsLoading(loading) {
  document.querySelectorAll('#approvalActions .btn').forEach(b => b.disabled = loading);
}

// ------------------------------------------------------------------ //
// Chat
// ------------------------------------------------------------------ //

function quickAsk(btn) {
  document.getElementById('chatInput').value = btn.textContent.trim();
  sendChat();
}

async function sendChat() {
  const input = document.getElementById('chatInput');
  const text = input.value.trim();
  if (!text) return;

  input.value = '';
  document.getElementById('chatSend').disabled = true;

  appendChatMsg('user', text);
  const typingId = appendTyping();

  try {
    const result = await api('/api/chat', 'POST', { message: text });
    removeTyping(typingId);
    appendChatMsg('ai', result.response);
  } catch (e) {
    removeTyping(typingId);
    appendChatMsg('ai', '⚠️ Could not reach the AI. Try again.');
  } finally {
    document.getElementById('chatSend').disabled = false;
    input.focus();
  }
}

function appendChatMsg(role, text) {
  const container = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = `chat-msg ${role}`;
  div.innerHTML = `<div class="chat-bubble">${role === 'ai' ? renderMarkdown(text) : esc(text)}</div>`;
  container.appendChild(div);
  div.scrollIntoView({ behavior: 'smooth', block: 'end' });
  return div.id = `msg-${Date.now()}`;
}

function appendTyping() {
  const container = document.getElementById('chatMessages');
  const id = `typing-${Date.now()}`;
  const div = document.createElement('div');
  div.className = 'chat-msg ai';
  div.id = id;
  div.innerHTML = `<div class="chat-bubble"><div class="typing"><span></span><span></span><span></span></div></div>`;
  container.appendChild(div);
  div.scrollIntoView({ behavior: 'smooth', block: 'end' });
  return id;
}

function removeTyping(id) {
  document.getElementById(id)?.remove();
}

// ------------------------------------------------------------------ //
// CRM
// ------------------------------------------------------------------ //

async function loadContacts() {
  try {
    allContacts = await api('/api/contacts');
    // On desktop all columns are visible; on mobile only render if on CRM page
    if (window.innerWidth >= 768 || currentPage === 'crm') renderContacts('');
  } catch (_) {}
}

function renderContacts(search) {
  const list = document.getElementById('contactList');
  let filtered = allContacts;

  if (activeFilter !== 'all') {
    if (activeFilter === 'urgent') {
      filtered = filtered.filter(c => c._status === 'urgent');
    } else {
      filtered = filtered.filter(c => c._type === activeFilter);
    }
  }

  if (search.trim()) {
    const q = search.toLowerCase();
    filtered = filtered.filter(c =>
      JSON.stringify(c).toLowerCase().includes(q)
    );
  }

  if (!filtered.length) {
    list.innerHTML = `<div class="empty"><div class="icon">👤</div><p>No contacts found</p></div>`;
    return;
  }

  list.innerHTML = filtered.map(c => contactCard(c)).join('');
}

function contactCard(c) {
  const name = c['Name'] || c['Company'] || c['Name / Identifier'] || c._file?.replace('.md','') || 'Unknown';
  const sub  = c['Phone'] || c['Phone / WhatsApp'] || c['Identifier'] || '';
  const status = c['Status'] || c['Next Service'] || '';
  const initials = name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();

  const typeMeta = contactTypes.find(t => t.type === c._type);
  const typeLabel = typeMeta ? typeMeta.label : c._type;
  const typeBadge = contactTypeBadge(c._type, typeLabel);
  const urgentBadge = c._status === 'urgent' ? `<span class="badge badge-urgent">Urgent</span>` : '';

  const slug = c._file?.replace('.md', '') || '';

  return `
    <div class="card ${c._status === 'urgent' ? 'urgent' : c._status === 'warning' ? 'warning' : ''}"
         onclick="openContact('${c._type}', '${slug}')">
      <div class="card-header">
        <div class="avatar" style="background:${avatarColor(name)}">${initials}</div>
        <div class="card-meta">
          <div class="card-name">${esc(name)}</div>
          <div class="card-sub">${esc(sub)} ${typeBadge} ${urgentBadge}</div>
        </div>
      </div>
      ${status ? `<div class="card-body"><div class="card-preview">${esc(status)}</div></div>` : ''}
    </div>`;
}

async function openContact(type, slug) {
  const content = document.getElementById('contactPanelContent');
  content.innerHTML = '<div class="spinner"></div>';
  openPanel('contact');

  try {
    const data = await api(`/api/contacts/${type}/${slug}`);
    content.innerHTML = `<div class="contact-html">${data.html}</div>`;
  } catch (e) {
    content.innerHTML = `<div class="empty"><p>Could not load contact</p></div>`;
  }
}

// ------------------------------------------------------------------ //
// Panels
// ------------------------------------------------------------------ //

function openPanel(name) {
  document.getElementById(`${name}Overlay`).classList.add('open');
  document.getElementById(`${name}Panel`).classList.add('open');
}

function closePanel(name) {
  document.getElementById(`${name}Overlay`).classList.remove('open');
  document.getElementById(`${name}Panel`).classList.remove('open');
}

// ------------------------------------------------------------------ //
// Utilities
// ------------------------------------------------------------------ //

async function api(url, method = 'GET', body = null) {
  const opts = { method, headers: {} };
  if (body) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function esc(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/\n/g, '<br>');
}

function renderMarkdown(text) {
  // Basic markdown: bold, italic, code, headers, line breaks
  return esc(text)
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`(.*?)`/g, '<code>$1</code>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>');
}

// Auto-assign a badge color palette by hashing the type name
const BADGE_PALETTE = [
  ['#e0f2fe','#0369a1'], // blue
  ['#dcfce7','#166534'], // green
  ['#ede9fe','#5b21b6'], // purple
  ['#fef9c3','#713f12'], // yellow
  ['#fce7f3','#9d174d'], // pink
  ['#ffedd5','#9a3412'], // orange
];

function contactTypeBadge(type, label) {
  let hash = 0;
  for (const c of type) hash = c.charCodeAt(0) + ((hash << 5) - hash);
  const [bg, fg] = BADGE_PALETTE[Math.abs(hash) % BADGE_PALETTE.length];
  return `<span class="badge" style="background:${bg};color:${fg}">${esc(label)}</span>`;
}

function avatarColor(name) {
  const colors = ['#2563eb','#7c3aed','#db2777','#059669','#d97706','#dc2626'];
  let hash = 0;
  for (let c of name) hash = c.charCodeAt(0) + ((hash << 5) - hash);
  return colors[Math.abs(hash) % colors.length];
}

let toastTimer;
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2500);
}
