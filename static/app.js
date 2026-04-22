/* ------------------------------------------------------------------ */
/* AI-PA CRM — Dashboard JS                                             */
/* ------------------------------------------------------------------ */
console.log('[CRM] app.js loaded');

const State = {
  currentPage: 'inbox',
  allContacts: [],
  contactTypes: [],
  activeFilter: 'all',
  pollInterval: null,
  currentApprovalId: null,
  knownApprovalIds: new Set(),
  pendingActions: new Map(), // id -> { undoTimer, payload }
  searchDebounce: null,
  lastFocus: null,
  lastSyncAt: null,
  composeContact: null,
};

// ------------------------------------------------------------------ //
// Init
// ------------------------------------------------------------------ //

document.addEventListener('DOMContentLoaded', async () => {
  initTheme();
  attachStaticListeners();
  await loadMeta();
  loadStatus();
  loadChatHistory();
  await loadContacts();
  loadApprovals({ initial: true });

  State.pollInterval = setInterval(() => {
    if (State.currentPage === 'inbox' || isDesktop()) loadApprovals();
    loadStatus();
    updateSyncLabel();
  }, 5000);

  setInterval(updateSyncLabel, 30000);
  initPullToRefresh();
});

function isDesktop() { return window.innerWidth >= 768; }

// ------------------------------------------------------------------ //
// Static listeners (replaces inline onclick attributes)
// ------------------------------------------------------------------ //

function attachStaticListeners() {
  // Mobile nav buttons
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => showPage(btn.dataset.page, btn));
  });

  // Quick questions
  document.querySelectorAll('.quick-q').forEach(btn => {
    btn.addEventListener('click', () => {
      document.getElementById('chatInput').value = btn.textContent.trim();
      sendChat();
    });
  });

  // Chat input
  document.getElementById('chatInput').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
  });
  document.getElementById('chatSend').addEventListener('click', sendChat);

  // CRM search (debounced)
  document.getElementById('crmSearch').addEventListener('input', e => {
    clearTimeout(State.searchDebounce);
    State.searchDebounce = setTimeout(() => renderContacts(e.target.value), 150);
  });

  // Panel close buttons
  document.getElementById('approvalPanelClose').addEventListener('click', () => closePanel('approval'));
  document.getElementById('contactPanelClose').addEventListener('click', () => closePanel('contact'));
  document.getElementById('approvalOverlay').addEventListener('click', () => closePanel('approval'));
  document.getElementById('contactOverlay').addEventListener('click', () => closePanel('contact'));

  // Header buttons
  document.getElementById('themeToggle').addEventListener('click', toggleTheme);
  document.getElementById('hsActivity').addEventListener('click', openActivity);
  document.getElementById('hsPending').addEventListener('click', () => {
    if (!isDesktop()) showPage('inbox', document.querySelector('.nav-btn[data-page="inbox"]'));
  });

  // Activity modal
  document.getElementById('activityClose').addEventListener('click', closeActivity);
  document.getElementById('activityOverlay').addEventListener('click', closeActivity);

  // Inbox submit modal
  const addBtn = document.getElementById('inboxAddBtn');
  if (addBtn) {
    addBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      openInboxSubmit();
    });
  }
  document.getElementById('inboxSubmitClose').addEventListener('click', closeInboxSubmit);
  document.getElementById('inboxSubmitOverlay').addEventListener('click', closeInboxSubmit);
  document.getElementById('inboxSubmitForm').addEventListener('submit', handleInboxSubmit);

  // Escape key closes panels / modals
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if (document.getElementById('inboxSubmitModal').classList.contains('open')) {
      closeInboxSubmit();
    } else if (document.getElementById('activityModal').classList.contains('open')) {
      closeActivity();
    } else if (document.getElementById('approvalPanel').classList.contains('open')) {
      closePanel('approval');
    } else if (document.getElementById('contactPanel').classList.contains('open')) {
      closePanel('contact');
    }
  });
}

// ------------------------------------------------------------------ //
// Theme (dark mode)
// ------------------------------------------------------------------ //

function initTheme() {
  const saved = localStorage.getItem('theme');
  if (saved) document.documentElement.setAttribute('data-theme', saved);
  updateThemeIcon();
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  const osDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  let next;
  if (current === 'dark') next = 'light';
  else if (current === 'light') next = 'dark';
  else next = osDark ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('theme', next);
  updateThemeIcon();
}

function updateThemeIcon() {
  const explicit = document.documentElement.getAttribute('data-theme');
  const osDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const isDark = explicit === 'dark' || (!explicit && osDark);
  document.getElementById('themeToggle').textContent = isDark ? '☀️' : '🌙';
}

// ------------------------------------------------------------------ //
// Meta / config
// ------------------------------------------------------------------ //

async function loadMeta() {
  try {
    const meta = await api('/api/meta');
    State.contactTypes = meta.contacts || [];
    if (meta.quick_questions) renderQuickQuestions(meta.quick_questions);
  } catch (_) {
    State.contactTypes = [
      { type: 'corporate',   label: 'Corporate' },
      { type: 'residential', label: 'Residential' },
      { type: 'lead',        label: 'Lead' },
    ];
  }
  renderFilterChips();
}

function renderQuickQuestions(questions) {
  const container = document.getElementById('quickQuestions');
  if (!container || !questions.length) return;
  container.innerHTML = questions.map(q =>
    `<button class="quick-q">${esc(q)}</button>`
  ).join('');
  container.querySelectorAll('.quick-q').forEach(btn => {
    btn.addEventListener('click', () => {
      document.getElementById('chatInput').value = btn.textContent.trim();
      sendChat();
    });
  });
}

function renderFilterChips() {
  const row = document.getElementById('filterRow');
  const chips = [
    { filter: 'all', label: 'All' },
    ...State.contactTypes.map(t => ({ filter: t.type, label: t.label })),
    { filter: 'urgent', label: 'Urgent' },
  ];
  row.innerHTML = chips.map((c, i) =>
    `<button class="filter-chip${i === 0 ? ' active' : ''}" data-filter="${c.filter}">${esc(c.label)}</button>`
  ).join('');
  row.querySelectorAll('.filter-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      row.querySelectorAll('.filter-chip').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      State.activeFilter = btn.dataset.filter;
      renderContacts(document.getElementById('crmSearch').value);
    });
  });
}

// ------------------------------------------------------------------ //
// Navigation
// ------------------------------------------------------------------ //

function showPage(page, btn) {
  if (isDesktop()) return;

  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(`page-${page}`).classList.add('active');
  if (btn) btn.classList.add('active');
  State.currentPage = page;

  if (page === 'inbox') loadApprovals();
  if (page === 'crm') renderContacts(document.getElementById('crmSearch').value);
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
    setBadge('inboxBadge', count);
    setBadge('inboxColBadge', count);

    // Header pending pill
    const hsPending = document.getElementById('hsPending');
    document.getElementById('hsPendingCount').textContent = count;
    hsPending.hidden = count === 0;

    State.lastSyncAt = Date.now();
    updateSyncLabel();
  } catch (_) {}
}

function setBadge(id, count) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = count;
  el.hidden = count === 0;
}

function updateSyncLabel() {
  if (!State.lastSyncAt) return;
  const diff = Math.floor((Date.now() - State.lastSyncAt) / 1000);
  let label;
  if (diff < 5) label = 'just now';
  else if (diff < 60) label = `${diff}s ago`;
  else if (diff < 3600) label = `${Math.floor(diff / 60)}m ago`;
  else label = `${Math.floor(diff / 3600)}h ago`;
  document.getElementById('hsSyncLabel').textContent = label;
}

// ------------------------------------------------------------------ //
// Inbox
// ------------------------------------------------------------------ //

async function loadApprovals(opts = {}) {
  const list = document.getElementById('approvalList');

  if (opts.initial) {
    list.innerHTML = skeletonCards(3);
  }

  try {
    const approvals = await api('/api/approvals');

    // Detect new arrivals
    const newIds = [];
    if (!opts.initial) {
      for (const a of approvals) {
        if (!State.knownApprovalIds.has(a.id)) newIds.push(a.id);
      }
      if (newIds.length > 0) signalNewArrival(newIds.length);
    }
    State.knownApprovalIds = new Set(approvals.map(a => a.id));

    if (!approvals.length) {
      list.innerHTML = `
        <div class="empty">
          <div class="icon">✅</div>
          <p>No pending approvals</p>
        </div>`;
      return;
    }

    list.innerHTML = renderApprovalGroups(approvals, newIds);
    list.querySelectorAll('.card[data-approval-id]').forEach(el => {
      el.addEventListener('click', () => openApproval(el.dataset.approvalId));
    });
    // Contact name links in inbox cards
    const nameLinks = list.querySelectorAll('.card-name-link');
    nameLinks.forEach(el => {
      el.addEventListener('click', e => {
        e.stopPropagation();
        openContact(el.dataset.contactType, el.dataset.contactSlug);
      });
    });
  } catch (e) {
    list.innerHTML = `<div class="empty"><p>Could not load approvals</p></div>`;
  }
}

function renderApprovalGroups(approvals, newIds) {
  // Bucket: stale (>1h), today (>1h ago up to today), recent (<1h fresh)
  // Triage waiting bands by minutes: fresh <15m, warm 15m–1h, stale >1h
  const groups = {
    waiting:  { label: '⏰ Waiting > 1 hour', items: [] },
    today:    { label: '📅 Today', items: [] },
    earlier:  { label: '📜 Earlier', items: [] },
  };

  for (const a of approvals) {
    const minsAgo = parseTimeAgoMins(a.time_ago);
    if (minsAgo >= 60 && minsAgo < 60 * 24) groups.waiting.items.push(a);
    else if (minsAgo >= 60 * 24) groups.earlier.items.push(a);
    else groups.today.items.push(a);
  }

  let html = '';
  for (const key of ['waiting', 'today', 'earlier']) {
    const g = groups[key];
    if (!g.items.length) continue;
    html += `<div class="group-label">${g.label}<span class="gl-count">${g.items.length}</span></div>`;
    html += g.items.map(a => approvalCard(a, newIds.includes(a.id))).join('');
  }
  return html;
}

function parseTimeAgoMins(s) {
  if (!s) return 0;
  if (s.endsWith('s ago')) return 0;
  if (s.endsWith('m ago')) return parseInt(s) || 0;
  if (s.endsWith('h ago')) return (parseInt(s) || 0) * 60;
  if (s.endsWith('d ago')) return (parseInt(s) || 0) * 60 * 24;
  return 0;
}

function digitsOnly(s) { return (s || '').replace(/\D/g, ''); }

function findContactMatch(a) {
  const ident = (a.identifier || '').toLowerCase();
  const identDigits = digitsOnly(ident);
  const name = (a.sender_name || '').toLowerCase();
  const cs = State.allContacts;

  // Pass 1: match by identifier fields (strongest signal)
  for (const c of cs) {
    const fields = [c['Phone'], c['Phone / WhatsApp'], c['Email'], c['Identifier'], c['WhatsApp']]
      .filter(Boolean);
    for (const f of fields) {
      const fl = f.toLowerCase();
      if (fl.includes(ident) || ident.includes(fl)) return c;
      const fd = digitsOnly(f);
      if (fd.length >= 7 && identDigits.length >= 7 && (fd.includes(identDigits) || identDigits.includes(fd))) return c;
    }
  }

  // Pass 2: match by contact person field (commercial clients)
  for (const c of cs) {
    const contactPerson = (c['Contact'] || '').toLowerCase();
    if (contactPerson && name && contactPerson.includes(name)) return c;
  }

  // Pass 3: match by sender name against record name
  for (const c of cs) {
    const cName = (c['Name'] || c['Company'] || c['Name / Identifier'] || '').toLowerCase();
    if (cName && name && (cName.includes(name) || name.includes(cName))) return c;
  }

  return null;
}

function approvalCard(a, isNewArrival = false) {
  const initials = (a.sender_name || '?').split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();
  const isNew = (a.analysis || '').toLowerCase().includes('new contact');
  const channelIcon = { telegram: '📱', whatsapp: '💬', email: '📧', instagram: '📸', phone: '📞', 'walk-in': '🚶', web: '🌐' }[a.channel] || '💬';

  // Triage band
  const minsAgo = parseTimeAgoMins(a.time_ago);
  let triage = 'wait-fresh';
  if (minsAgo >= 60) triage = 'wait-stale';
  else if (minsAgo >= 15) triage = 'wait-warm';

  // Ribbon
  let ribbon = '';
  if (a.kind === 'outbound') ribbon = `<span class="ribbon">COMPOSE</span>`;
  else if (isNew) ribbon = `<span class="ribbon">NEW LEAD</span>`;
  else if (minsAgo >= 60) ribbon = `<span class="ribbon urgent">WAITING</span>`;

  const channelChip = `<span class="badge" style="background:var(--bg);color:var(--muted);border:1px solid var(--border)">${channelIcon} ${esc(a.channel || '')}</span>`;
  const arrivalCls = isNewArrival ? ' new-arrival' : '';

  // Contact link on sender name
  const match = findContactMatch(a);
  let nameHTML;
  if (match) {
    const slug = (match._file || '').replace('.md', '');
    nameHTML = `<a class="card-name card-name-link" data-contact-type="${esc(match._type)}" data-contact-slug="${esc(slug)}">${esc(a.sender_name || a.identifier)}</a>`;
  } else {
    nameHTML = `<div class="card-name">${esc(a.sender_name || a.identifier)}</div>`;
  }

  return `
    <div class="card ${triage}${arrivalCls}" data-approval-id="${esc(a.id)}" tabindex="0">
      ${ribbon}
      <div class="card-header">
        <div class="avatar" style="background:${avatarColor(a.sender_name || a.identifier)}">${initials}</div>
        <div class="card-meta">
          ${nameHTML}
          <div class="card-sub">${channelChip} ${esc(a.identifier || '')}</div>
        </div>
        <div class="card-time">${esc(a.time_ago || '')}</div>
      </div>
      <div class="card-body">
        <div class="card-preview">${esc(a.original_message)}</div>
      </div>
    </div>`;
}

function signalNewArrival(count) {
  toast(`🔔 ${count} new message${count > 1 ? 's' : ''}`);
  if (navigator.vibrate) navigator.vibrate(40);
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain); gain.connect(ctx.destination);
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.08, ctx.currentTime + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.18);
    osc.start();
    osc.stop(ctx.currentTime + 0.2);
  } catch (_) {}
}

// ------------------------------------------------------------------ //
// Approval panel
// ------------------------------------------------------------------ //

async function openApproval(id) {
  State.currentApprovalId = id;
  State.lastFocus = document.activeElement;
  const content = document.getElementById('approvalPanelContent');
  const actions = document.getElementById('approvalActions');
  content.innerHTML = '<div class="spinner"></div>';
  actions.innerHTML = '';
  openPanel('approval');

  try {
    const a = await api(`/api/approvals/${id}`);
    const senderContextHTML = await buildSenderContext(a);

    const match = findContactMatch(a);
    let titleHTML;
    if (match) {
      const slug = (match._file || '').replace('.md', '');
      titleHTML = `<a class="panel-title panel-title-link" id="approvalPanelTitle" data-contact-type="${esc(match._type)}" data-contact-slug="${esc(slug)}">${esc(a.sender_name || a.identifier)}</a>`;
    } else {
      titleHTML = `<div id="approvalPanelTitle" class="panel-title">${esc(a.sender_name || a.identifier)}</div>`;
    }

    content.innerHTML = `
      ${titleHTML}
      <div class="panel-subtitle">${esc(a.identifier || '')} · ${esc(a.channel || '')} · ${esc(a.time_ago || '')}</div>

      ${senderContextHTML}

      <div class="section-label">Their message</div>
      <div class="message-bubble">${esc(a.original_message)}</div>

      <div class="section-label">AI analysis</div>
      <details>
        <summary style="cursor:pointer;font-size:0.85rem;color:var(--primary);margin-bottom:8px">Show analysis</summary>
        <div class="analysis-box">${esc(a.analysis || '')}</div>
      </details>

      <div class="section-label">Draft reply</div>
      <textarea class="draft-edit" id="draftText" aria-label="Draft reply">${escAttr(a.draft || '')}</textarea>

      <div class="section-label">Edit instructions</div>
      <input type="text" id="editInstructions" placeholder="e.g. Make it shorter, add pricing…"
        aria-label="Edit instructions"
        style="width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:8px;font-size:0.875rem;font-family:inherit;outline:none;margin-bottom:4px;background:var(--surface);color:var(--text)">
      <button class="btn btn-ghost" id="regenerateBtn" style="width:100%;margin-top:6px">✏️ Regenerate draft</button>
    `;

    actions.innerHTML = `
      <button class="btn btn-danger"  id="rejectBtn">❌ Reject</button>
      <button class="btn btn-success" id="acceptBtn" style="grid-column:span 2">✅ Approve &amp; copy</button>
    `;

    document.getElementById('rejectBtn').addEventListener('click', rejectApproval);
    document.getElementById('acceptBtn').addEventListener('click', acceptApproval);
    document.getElementById('regenerateBtn').addEventListener('click', editDraft);

    // Focus draft for quick editing
    setTimeout(() => document.getElementById('draftText')?.focus(), 100);

    // Wire up sender context link if present
    const link = content.querySelector('.sc-link');
    if (link) link.addEventListener('click', () => {
      openContact(link.dataset.type, link.dataset.slug);
    });
    // Wire up panel title link
    const titleLink = content.querySelector('.panel-title-link');
    if (titleLink) titleLink.addEventListener('click', () => {
      openContact(titleLink.dataset.contactType, titleLink.dataset.contactSlug);
    });
  } catch (e) {
    content.innerHTML = `<div class="empty"><p>Could not load approval</p></div>`;
  }
}

async function buildSenderContext(a) {
  if (!State.allContacts.length) {
    try { State.allContacts = await api('/api/contacts'); } catch (_) {}
  }
  const match = findContactMatch(a);

  if (!match) {
    return `
      <div class="sender-context">
        <div class="sc-label">Sender context</div>
        <div>🆕 New contact — contact will be created once a response is sent.</div>
      </div>`;
  }

  const name = match['Name'] || match['Company'] || match['Name / Identifier'] || match._file?.replace('.md','') || 'Unknown';
  const slug = match._file?.replace('.md','') || '';
  const status = match['Status'] || match['Next Service'] || '';
  const meta = State.contactTypes.find(t => t.type === match._type);

  return `
    <div class="sender-context">
      <div class="sc-label">Sender context</div>
      <a class="sc-link" data-type="${esc(match._type)}" data-slug="${esc(slug)}">
        ${esc(name)} (${esc(meta?.label || match._type)})
      </a>
      ${status ? `<div class="sc-snippet">${esc(status)}</div>` : ''}
    </div>`;
}

async function acceptApproval() {
  const id = State.currentApprovalId;
  const draft = document.getElementById('draftText').value.trim();
  if (!draft) { toast('Draft is empty'); return; }

  // Save edits to draft first
  try { await api(`/api/approvals/${id}/draft`, 'POST', { draft }); }
  catch (_) {}

  // Copy draft to clipboard for manual sending
  try { await navigator.clipboard.writeText(draft); }
  catch (_) {}

  // Optimistic UI: close panel, show undo toast
  closePanel('approval');
  optimisticAction(id, 'send', async () => {
    await api(`/api/approvals/${id}/accept`, 'POST');
    loadApprovals();
    loadStatus();
    toast('Approved — draft copied to clipboard');
  });
}

async function rejectApproval() {
  const id = State.currentApprovalId;
  closePanel('approval');
  optimisticAction(id, 'reject', async () => {
    await api(`/api/approvals/${id}/reject`, 'POST');
    loadApprovals();
    loadStatus();
  });
}

function optimisticAction(id, kind, commit) {
  const labelMap = { send: '✅ Sending…', reject: '❌ Rejecting…' };
  const card = document.querySelector(`.card[data-approval-id="${id}"]`);
  if (card) card.style.opacity = '0.4';

  // Remove existing if user double-actions
  if (State.pendingActions.has(id)) clearTimeout(State.pendingActions.get(id).timer);

  const undoToast = showUndoToast(`${labelMap[kind]} (tap to undo)`, () => {
    clearTimeout(State.pendingActions.get(id)?.timer);
    State.pendingActions.delete(id);
    if (card) card.style.opacity = '1';
    toast('Undone');
  });

  const timer = setTimeout(async () => {
    State.pendingActions.delete(id);
    undoToast.dismiss();
    try {
      await commit();
      toast(kind === 'send' ? '✅ Reply sent' : '❌ Rejected');
    } catch (e) {
      toast('Action failed');
      if (card) card.style.opacity = '1';
      loadApprovals();
    }
  }, 5000);

  State.pendingActions.set(id, { timer, kind });
}

async function editDraft() {
  const instructions = document.getElementById('editInstructions').value.trim();
  if (!instructions) { toast('Enter edit instructions first'); return; }

  const btn = document.getElementById('regenerateBtn');
  btn.disabled = true;
  btn.textContent = 'Thinking…';

  try {
    const result = await api(`/api/approvals/${State.currentApprovalId}/edit`, 'POST', { instructions });
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

// ------------------------------------------------------------------ //
// Chat
// ------------------------------------------------------------------ //

async function loadChatHistory() {
  try {
    const history = await api('/api/chat/history');
    if (!history || !history.length) return;
    for (const h of history) {
      appendChatMsg('user', h.question);
      appendChatMsg('ai', h.answer);
    }
  } catch (_) {}
}

async function sendChat() {
  const input = document.getElementById('chatInput');
  const text = input.value.trim();
  if (!text) return;

  input.value = '';
  document.getElementById('chatSend').disabled = true;

  appendChatMsg('user', text);
  const aiBubble = appendChatMsg('ai', '');
  const bubbleEl = aiBubble.querySelector('.chat-bubble');
  bubbleEl.innerHTML = `<div class="typing"><span></span><span></span><span></span></div>`;

  // SSE stream
  let received = '';
  try {
    await new Promise((resolve, reject) => {
      const es = new EventSource(`/api/chat/stream?message=${encodeURIComponent(text)}`);
      es.onmessage = ev => {
        try {
          const data = JSON.parse(ev.data);
          if (data.done) { es.close(); resolve(); return; }
          if (data.chunk) {
            received += data.chunk;
            bubbleEl.innerHTML = renderMarkdown(received);
            aiBubble.scrollIntoView({ behavior: 'smooth', block: 'end' });
          }
        } catch (_) {}
      };
      es.onerror = () => { es.close(); resolve(); };
    });
    if (!received) bubbleEl.innerHTML = '⚠️ Could not reach the AI.';
  } catch (e) {
    bubbleEl.innerHTML = '⚠️ Could not reach the AI.';
  } finally {
    document.getElementById('chatSend').disabled = false;
    input.focus();
  }
}

function appendChatMsg(role, text) {
  const container = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = `chat-msg ${role}`;
  div.innerHTML = `<div class="chat-bubble">${role === 'ai' ? renderMarkdown(text || '') : esc(text)}</div>`;
  container.appendChild(div);
  div.scrollIntoView({ behavior: 'smooth', block: 'end' });
  return div;
}

// ------------------------------------------------------------------ //
// CRM
// ------------------------------------------------------------------ //

async function loadContacts() {
  const list = document.getElementById('contactList');
  list.innerHTML = skeletonCards(4);
  try {
    State.allContacts = await api('/api/contacts');
    if (isDesktop() || State.currentPage === 'crm') renderContacts('');
  } catch (_) {
    list.innerHTML = `<div class="empty"><p>Could not load contacts</p></div>`;
  }
}

function renderContacts(search) {
  const list = document.getElementById('contactList');
  let filtered = State.allContacts;

  if (State.activeFilter !== 'all') {
    if (State.activeFilter === 'urgent') {
      filtered = filtered.filter(c => c._status === 'urgent');
    } else {
      filtered = filtered.filter(c => c._type === State.activeFilter);
    }
  }

  if (search && search.trim()) {
    const q = search.toLowerCase();
    filtered = filtered.filter(c => JSON.stringify(c).toLowerCase().includes(q));
  }

  if (!filtered.length) {
    list.innerHTML = `<div class="empty"><div class="icon">👤</div><p>No contacts found</p></div>`;
    return;
  }

  list.innerHTML = filtered.map(c => contactCard(c)).join('');
  list.querySelectorAll('.card[data-contact-type]').forEach(el => {
    el.addEventListener('click', e => {
      if (e.target.closest('.contact-compose-btn')) return;
      openContact(el.dataset.contactType, el.dataset.contactSlug);
    });
  });
  list.querySelectorAll('.contact-compose-btn').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      openCompose(btn.dataset.type, btn.dataset.slug, btn.dataset.name);
    });
  });
}

function contactCard(c) {
  const name = c['Name'] || c['Company'] || c['Name / Identifier'] || c._file?.replace('.md','') || 'Unknown';
  const sub  = c['Phone'] || c['Phone / WhatsApp'] || c['Identifier'] || '';
  const status = c['Status'] || c['Next Service'] || '';
  const initials = name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();

  const typeMeta = State.contactTypes.find(t => t.type === c._type);
  const typeLabel = typeMeta ? typeMeta.label : c._type;
  const typeBadge = contactTypeBadge(c._type, typeLabel);
  const urgentBadge = c._status === 'urgent' ? `<span class="badge badge-urgent">Urgent</span>` : '';

  const slug = c._file?.replace('.md', '') || '';

  return `
    <div class="card ${c._status === 'urgent' ? 'urgent' : c._status === 'warning' ? 'warning' : ''}"
         data-contact-type="${esc(c._type)}" data-contact-slug="${esc(slug)}" tabindex="0">
      <div class="card-header">
        <div class="avatar" style="background:${avatarColor(name)}">${initials}</div>
        <div class="card-meta">
          <div class="card-name">${esc(name)}</div>
          <div class="card-sub">${esc(sub)} ${typeBadge} ${urgentBadge}</div>
        </div>
      </div>
      ${status ? `<div class="card-body"><div class="card-preview">${esc(status)}</div></div>` : ''}
      <button class="contact-compose-btn" data-type="${esc(c._type)}" data-slug="${esc(slug)}" data-name="${esc(name)}" aria-label="Compose message to ${esc(name)}">
        ✉️ Compose
      </button>
    </div>`;
}

async function openContact(type, slug) {
  State.lastFocus = document.activeElement;
  const content = document.getElementById('contactPanelContent');
  content.innerHTML = '<div class="spinner"></div>';
  openPanel('contact');

  try {
    const data = await api(`/api/contacts/${type}/${slug}`);
    const collapsibleHTML = wrapContactSections(data.html);
    content.innerHTML = `<div class="contact-html">${collapsibleHTML}</div>`;
  } catch (e) {
    content.innerHTML = `<div class="empty"><p>Could not load contact</p></div>`;
  }
}

function wrapContactSections(html) {
  // Wrap each <h2>...</h2> + following content (until next h2 or end) in <details><summary>
  const tmp = document.createElement('div');
  tmp.innerHTML = html;
  const result = document.createElement('div');

  let currentDetails = null;
  let currentBody = null;
  for (const node of Array.from(tmp.childNodes)) {
    if (node.nodeType === 1 && node.tagName === 'H2') {
      currentDetails = document.createElement('details');
      currentDetails.open = true;
      const summary = document.createElement('summary');
      summary.textContent = node.textContent;
      currentDetails.appendChild(summary);
      currentBody = document.createElement('div');
      currentBody.className = 'section-content';
      currentDetails.appendChild(currentBody);
      result.appendChild(currentDetails);
    } else if (currentBody) {
      currentBody.appendChild(node.cloneNode(true));
    } else {
      result.appendChild(node.cloneNode(true));
    }
  }
  return result.innerHTML;
}

// ------------------------------------------------------------------ //
// Compose
// ------------------------------------------------------------------ //

function openCompose(type, slug, name) {
  State.composeContact = { type, slug, name };
  State.lastFocus = document.activeElement;
  const content = document.getElementById('approvalPanelContent');
  const actions = document.getElementById('approvalActions');

  content.innerHTML = `
    <div class="panel-title">✉️ Compose to ${esc(name)}</div>
    <div class="panel-subtitle">${esc(type)}</div>

    <div class="section-label">What do you want to say?</div>
    <textarea class="compose-intent" id="composeIntent"
      placeholder="e.g. Remind them about Tuesday's service appointment, ask if they're still interested in the quote, follow up on the complaint…"
      aria-label="Compose intent"></textarea>

    <p style="font-size:0.78rem;color:var(--muted);margin-top:8px">
      The AI will draft a friendly message based on this intent and the contact's history. You'll still review it before it's sent.
    </p>
  `;

  actions.innerHTML = `
    <button class="btn btn-ghost" id="composeCancelBtn">Cancel</button>
    <button class="btn btn-primary" id="composeGenBtn" style="grid-column:span 2">✨ Generate draft</button>
  `;

  document.getElementById('composeCancelBtn').addEventListener('click', () => closePanel('approval'));
  document.getElementById('composeGenBtn').addEventListener('click', generateCompose);

  openPanel('approval');
  setTimeout(() => document.getElementById('composeIntent')?.focus(), 100);
}

async function generateCompose() {
  const intent = document.getElementById('composeIntent').value.trim();
  if (!intent) { toast('Tell the AI what to write about'); return; }

  const btn = document.getElementById('composeGenBtn');
  btn.disabled = true;
  btn.textContent = 'Drafting…';

  try {
    const { type, slug } = State.composeContact;
    const result = await api('/api/compose', 'POST', { contact_type: type, slug, intent });
    closePanel('approval');
    toast('✨ Draft ready in Inbox');
    loadApprovals();
    loadStatus();
    // Auto-open the new approval
    setTimeout(() => openApproval(result.id), 350);
  } catch (e) {
    toast('Failed to generate');
    btn.disabled = false;
    btn.textContent = '✨ Generate draft';
  }
}

// ------------------------------------------------------------------ //
// Activity modal
// ------------------------------------------------------------------ //

async function openActivity() {
  State.lastFocus = document.activeElement;
  document.getElementById('activityOverlay').classList.add('open');
  document.getElementById('activityModal').classList.add('open');

  const body = document.getElementById('activityBody');
  body.innerHTML = '<div class="spinner"></div>';
  try {
    const events = await api('/api/events');
    if (!events || !events.length) {
      body.innerHTML = `<div class="empty"><div class="icon">📭</div><p>No activity yet</p></div>`;
      return;
    }
    body.innerHTML = events.map(activityEventHTML).join('');
  } catch (e) {
    body.innerHTML = `<div class="empty"><p>Could not load activity</p></div>`;
  }
  document.getElementById('activityClose').focus();
}

function closeActivity() {
  document.getElementById('activityOverlay').classList.remove('open');
  document.getElementById('activityModal').classList.remove('open');
  if (State.lastFocus) State.lastFocus.focus();
}

function activityEventHTML(ev) {
  const iconMap = {
    message_received: '📨',
    message_sent:     '📤',
    rejected:         '❌',
  };
  const icon = iconMap[ev.event_type] || '•';
  const dirLabel = ev.direction === 'in' ? 'Received' : ev.direction === 'out' ? 'Sent' : '';
  return `
    <div class="activity-event">
      <div class="ev-icon">${icon}</div>
      <div class="ev-meta">
        <div class="ev-title">${esc(dirLabel)} · ${esc(ev.channel || '')}</div>
        <div class="ev-sub">${esc(ev.identifier || '')} — ${esc(ev.note || '')}</div>
      </div>
      <div class="ev-time">${esc(timeAgoFromString(ev.created_at))}</div>
    </div>`;
}

function timeAgoFromString(s) {
  if (!s) return '';
  const d = new Date(s.replace(' ', 'T') + 'Z');
  if (isNaN(d.getTime())) return s;
  const diff = Math.floor((Date.now() - d.getTime()) / 1000);
  if (diff < 60) return `${diff}s`;
  if (diff < 3600) return `${Math.floor(diff/60)}m`;
  if (diff < 86400) return `${Math.floor(diff/3600)}h`;
  return `${Math.floor(diff/86400)}d`;
}

// ------------------------------------------------------------------ //
// Inbox submit (new external message)
// ------------------------------------------------------------------ //

function openInboxSubmit() {
  State.lastFocus = document.activeElement;
  document.getElementById('inboxSubmitOverlay').classList.add('open');
  document.getElementById('inboxSubmitModal').classList.add('open');
  document.getElementById('ixName').focus();
}

function closeInboxSubmit() {
  document.getElementById('inboxSubmitOverlay').classList.remove('open');
  document.getElementById('inboxSubmitModal').classList.remove('open');
  document.getElementById('inboxSubmitForm').reset();
  if (State.lastFocus) State.lastFocus.focus();
}

async function handleInboxSubmit(e) {
  e.preventDefault();
  const btn = document.getElementById('ixSubmitBtn');
  const name = document.getElementById('ixName').value.trim();
  const identifier = document.getElementById('ixIdentifier').value.trim();
  const channel = document.getElementById('ixChannel').value;
  const message = document.getElementById('ixMessage').value.trim();
  if (!name || !message) return;

  btn.disabled = true;
  btn.textContent = 'Analysing...';

  // Detect identifier type from value
  let identifierType = 'unknown';
  if (identifier.includes('@')) identifierType = 'email';
  else if (/[\d+\-() ]{7,}/.test(identifier)) identifierType = 'phone';

  try {
    const res = await fetch('/api/inbox/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sender_name: name,
        identifier: identifier || name,
        identifier_type: identifierType,
        channel,
        message,
      }),
    });
    if (!res.ok) throw new Error(await res.text());
    closeInboxSubmit();
    loadApprovals();
    toast('Message submitted — approval created');
  } catch (err) {
    toast('Failed: ' + (err.message || 'unknown error'));
  } finally {
    btn.disabled = false;
    btn.textContent = 'Submit to AI';
  }
}

// ------------------------------------------------------------------ //
// Pull-to-refresh (mobile)
// ------------------------------------------------------------------ //

function initPullToRefresh() {
  if (isDesktop()) return;
  const indicator = document.getElementById('ptrIndicator');
  let startY = null;
  let pulling = false;

  document.addEventListener('touchstart', e => {
    const colBody = document.querySelector('.page.active .col-body');
    if (!colBody || colBody.scrollTop > 0) return;
    startY = e.touches[0].clientY;
    pulling = true;
  }, { passive: true });

  document.addEventListener('touchmove', e => {
    if (!pulling || startY === null) return;
    const dy = e.touches[0].clientY - startY;
    if (dy > 60) indicator.classList.add('visible');
    else indicator.classList.remove('visible');
  }, { passive: true });

  document.addEventListener('touchend', () => {
    if (!pulling) return;
    pulling = false;
    if (indicator.classList.contains('visible')) {
      indicator.classList.add('spin');
      indicator.textContent = '⟳';
      Promise.all([loadApprovals(), loadContacts(), loadStatus()]).finally(() => {
        setTimeout(() => {
          indicator.classList.remove('visible', 'spin');
          indicator.textContent = '↓';
        }, 400);
      });
    }
    startY = null;
  });
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
  if (State.lastFocus && document.contains(State.lastFocus)) {
    State.lastFocus.focus();
  }
}

// ------------------------------------------------------------------ //
// Skeletons
// ------------------------------------------------------------------ //

function skeletonCards(n) {
  const one = `
    <div class="skeleton-card">
      <div class="sk-line sk-title"></div>
      <div class="sk-line sk-sub"></div>
      <div class="sk-line sk-body"></div>
    </div>`;
  return one.repeat(n);
}

// ------------------------------------------------------------------ //
// Toast + undo toast
// ------------------------------------------------------------------ //

let toastTimer;
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.onclick = null;
  el.style.cursor = 'default';
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2500);
}

function showUndoToast(msg, onUndo) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.style.cursor = 'pointer';
  el.classList.add('show');
  clearTimeout(toastTimer);
  el.onclick = () => {
    onUndo();
    el.onclick = null;
    el.classList.remove('show');
  };
  toastTimer = setTimeout(() => {
    el.classList.remove('show');
    el.onclick = null;
  }, 5000);
  return { dismiss: () => { el.classList.remove('show'); el.onclick = null; } };
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
  if (str === undefined || str === null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/\n/g, '<br>');
}

function escAttr(str) {
  if (str === undefined || str === null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function renderMarkdown(text) {
  return esc(text)
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`(.*?)`/g, '<code>$1</code>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>');
}

const BADGE_PALETTE = [
  ['#e0f2fe','#0369a1'],
  ['#dcfce7','#166534'],
  ['#ede9fe','#5b21b6'],
  ['#fef9c3','#713f12'],
  ['#fce7f3','#9d174d'],
  ['#ffedd5','#9a3412'],
];

function contactTypeBadge(type, label) {
  let hash = 0;
  for (const c of (type || '')) hash = c.charCodeAt(0) + ((hash << 5) - hash);
  const [bg, fg] = BADGE_PALETTE[Math.abs(hash) % BADGE_PALETTE.length];
  return `<span class="badge" style="background:${bg};color:${fg}">${esc(label)}</span>`;
}

function avatarColor(name) {
  const colors = ['#2563eb','#7c3aed','#db2777','#059669','#d97706','#dc2626'];
  let hash = 0;
  for (let c of (name || '')) hash = c.charCodeAt(0) + ((hash << 5) - hash);
  return colors[Math.abs(hash) % colors.length];
}
