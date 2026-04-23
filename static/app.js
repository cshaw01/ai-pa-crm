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
  calWeekStart: null,
  calEvents: [],
  waPollTimer: null,
  waLastState: null,
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
  State.calWeekStart = getMonday(new Date());
  loadCalendar();

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

  // Calendar
  document.getElementById('calPrev').addEventListener('click', () => calNavigate(-7));
  document.getElementById('calNext').addEventListener('click', () => calNavigate(7));
  document.getElementById('calToday').addEventListener('click', () => { State.calWeekStart = getMonday(new Date()); loadCalendar(); });
  document.getElementById('calAddBtn').addEventListener('click', () => openCalEventModal());
  document.getElementById('calPanelClose').addEventListener('click', () => closePanel('cal'));
  document.getElementById('calOverlay').addEventListener('click', () => closePanel('cal'));
  document.getElementById('calEventClose').addEventListener('click', closeCalEventModal);
  document.getElementById('calEventOverlay').addEventListener('click', closeCalEventModal);
  document.getElementById('calEventForm').addEventListener('submit', handleCalEventSubmit);

  // Feedback modal
  document.getElementById('hsFeedback').addEventListener('click', openFeedback);
  document.getElementById('feedbackClose').addEventListener('click', closeFeedback);
  document.getElementById('feedbackOverlay').addEventListener('click', closeFeedback);
  document.getElementById('feedbackForm').addEventListener('submit', handleFeedbackSubmit);

  // WhatsApp connect modal
  document.getElementById('hsWhatsApp').addEventListener('click', openWaModal);
  document.getElementById('waClose').addEventListener('click', closeWaModal);
  document.getElementById('waOverlay').addEventListener('click', closeWaModal);

  // Channels (Meta) connect modal
  document.getElementById('hsChannels').addEventListener('click', openChannelsModal);
  document.getElementById('channelsClose').addEventListener('click', closeChannelsModal);
  document.getElementById('channelsOverlay').addEventListener('click', closeChannelsModal);

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
    if (document.getElementById('calEventModal').classList.contains('open')) {
      closeCalEventModal();
    } else if (document.getElementById('channelsModal').classList.contains('open')) {
      closeChannelsModal();
    } else if (document.getElementById('waModal').classList.contains('open')) {
      closeWaModal();
    } else if (document.getElementById('feedbackModal').classList.contains('open')) {
      closeFeedback();
    } else if (document.getElementById('inboxSubmitModal').classList.contains('open')) {
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
  if (page === 'calendar') loadCalendar();
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

  const winBadge = formatWindowRemaining(a.last_inbound_at, a.channel);
  const badgeHTML = winBadge
    ? `<span class="win-badge ${winBadge.cls}" data-window-badge data-last-inbound="${escAttr(a.last_inbound_at)}" data-channel="${esc(a.channel)}">${esc(winBadge.label)}</span>`
    : '';

  return `
    <div class="card ${triage}${arrivalCls}" data-approval-id="${esc(a.id)}" tabindex="0">
      ${ribbon}
      <div class="card-header">
        <div class="avatar" style="background:${avatarColor(a.sender_name || a.identifier)}">${initials}</div>
        <div class="card-meta">
          ${nameHTML}
          <div class="card-sub">
            ${channelChip}
            <span class="card-identifier">${esc(a.identifier || '')}</span>
            ${badgeHTML}
          </div>
        </div>
        <div class="card-time">${esc(fmtLocalDate(a.created_at))}</div>
      </div>
      <div class="card-body">
        <div class="card-preview">${esc(a.original_message)}</div>
      </div>
    </div>`;
}

// Format a server-sent UTC timestamp as 'DD/MM HH:MM' in the viewer's
// local timezone. Handles three shapes the backend produces:
//   - 'YYYY-MM-DD HH:MM:SS'           (SQLite default, naive UTC)
//   - 'YYYY-MM-DDTHH:MM:SS.ffffff+00:00' (ISO 8601 w/ tz)
//   - 'YYYY-MM-DDTHH:MM:SSZ'          (ISO 8601 UTC)
function fmtLocalDate(utc_str) {
  if (!utc_str) return '';
  let s = String(utc_str).trim();
  // If there's no timezone indicator AND no 'T', treat as naive UTC
  const hasTz = /([zZ]|[+-]\d{2}:?\d{2})$/.test(s);
  const hasT = s.includes('T');
  if (!hasTz) {
    if (!hasT) s = s.replace(' ', 'T');
    s += 'Z';
  }
  const t = Date.parse(s);
  if (isNaN(t)) return utc_str;
  const d = new Date(t);
  const pad = n => String(n).padStart(2, '0');
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// Re-compute all visible window badges every 30s so the countdown ticks
function refreshWindowBadges() {
  document.querySelectorAll('[data-window-badge]').forEach(el => {
    const last = el.getAttribute('data-last-inbound');
    const ch = el.getAttribute('data-channel');
    const r = formatWindowRemaining(last, ch);
    if (!r) return;
    el.textContent = r.label;
    el.classList.remove('win-ok', 'win-warn', 'win-urgent', 'win-expired');
    el.classList.add(r.cls);
  });
}
setInterval(refreshWindowBadges, 30000);

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

    const badge = formatWindowRemaining(a.last_inbound_at, a.channel);
    const badgeHTML = badge
      ? `<span class="win-badge ${badge.cls}" title="Time left to reply">${esc(badge.label)}</span>`
      : '';

    const awaitingDone = a.manual_send_state === 'awaiting_done';
    const awaitingBanner = awaitingDone ? `
      <div class="awaiting-done-banner">
        <strong>Waiting for you to send this in ${esc(channelDisplay(a.channel))}.</strong><br>
        Paste the copied draft into the conversation, then click <em>Done</em> to log it here.
      </div>` : '';

    content.innerHTML = `
      ${titleHTML}
      <div class="panel-subtitle">${esc(a.identifier || '')} · ${esc(channelDisplay(a.channel))} · ${esc(fmtLocalDate(a.created_at))} ${badgeHTML}</div>

      ${senderContextHTML}
      ${awaitingBanner}

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

    // Choose action buttons based on state
    const acceptLabel = getAcceptLabel(a);
    if (awaitingDone) {
      actions.innerHTML = `
        <button class="btn btn-danger"  id="rejectBtn">❌ Reject</button>
        <button class="btn btn-success" id="doneBtn" style="grid-column:span 2">✅ Done — mark as sent</button>
      `;
      document.getElementById('doneBtn').addEventListener('click', markDone);
    } else {
      actions.innerHTML = `
        <button class="btn btn-danger"  id="rejectBtn">❌ Reject</button>
        <button class="btn btn-success" id="acceptBtn" style="grid-column:span 2">${acceptLabel}</button>
      `;
      document.getElementById('acceptBtn').addEventListener('click', acceptApproval);
    }

    document.getElementById('rejectBtn').addEventListener('click', rejectApproval);
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

  // Save edits first so whichever send path we take uses the latest text
  try { await api(`/api/approvals/${id}/draft`, 'POST', { draft }); }
  catch (_) {}

  // Fetch fresh state to know channel + window status
  let a;
  try { a = await api(`/api/approvals/${id}`); }
  catch (e) { toast('Failed to reload approval: ' + e.message); return; }

  const needsEscape = isMetaChannel(a.channel) && !withinWindow(a.last_inbound_at);

  if (needsEscape) {
    return acceptViaEscapeHatch(id, a, draft);
  }

  // Copy to clipboard — useful for web/whatsapp channels; harmless otherwise
  try { await navigator.clipboard.writeText(draft); }
  catch (_) {}

  closePanel('approval');
  optimisticAction(id, 'send', async () => {
    try {
      await api(`/api/approvals/${id}/accept`, 'POST');
    } catch (e) {
      // Server-side window check may disagree with the client — fall back
      if (e.message === 'outside_window') {
        toast('Window just closed — opening platform to send manually');
        return acceptViaEscapeHatch(id, a, draft);
      }
      throw e;
    }
    loadApprovals();
    loadStatus();
    toast('Approved');
  });
}

async function acceptViaEscapeHatch(id, a, draft) {
  // 1) Copy draft to clipboard
  try { await navigator.clipboard.writeText(draft); }
  catch (_) { toast('Copy the draft manually — clipboard was blocked'); }

  // 2) Open the platform in a new tab
  const url = getPlatformDeepLink(a);
  window.open(url, '_blank', 'noopener,noreferrer');

  // 3) Mark server-side so card flips to Done state
  try {
    await api(`/api/approvals/${id}/mark-awaiting-done`, 'POST');
  } catch (e) {
    toast('Failed to flag as awaiting-done: ' + e.message);
    return;
  }

  // 4) Refresh the approval panel so the banner + Done button render
  loadApprovals();
  openApproval(id);
  toast('Draft copied. Paste in the thread, then click Done.');
}

async function markDone() {
  const id = State.currentApprovalId;
  closePanel('approval');
  optimisticAction(id, 'send', async () => {
    await api(`/api/approvals/${id}/done`, 'POST');
    loadApprovals();
    loadStatus();
    toast('Marked as sent ✓');
  });
}

// ------------------------------------------------------------------ //
// Channel helpers
// ------------------------------------------------------------------ //

function isMetaChannel(ch) {
  return ch === 'messenger' || ch === 'instagram';
}

function channelDisplay(ch) {
  return {
    whatsapp: 'WhatsApp',
    messenger: 'Messenger',
    instagram: 'Instagram',
    telegram: 'Telegram',
    web: 'Web',
    email: 'Email',
  }[ch] || ch || '';
}

function getAcceptLabel(a) {
  if (a.channel === 'whatsapp') return '✅ Send via WhatsApp';
  if (isMetaChannel(a.channel)) {
    return withinWindow(a.last_inbound_at)
      ? `✅ Send via ${channelDisplay(a.channel)}`
      : `📋 Copy &amp; open ${channelDisplay(a.channel)}`;
  }
  return '✅ Approve &amp; copy';
}

function withinWindow(last_inbound_at) {
  if (!last_inbound_at) return false;
  // last_inbound_at is stored as 'YYYY-MM-DD HH:MM:SS' UTC. Normalise to Date.
  const t = Date.parse(last_inbound_at.replace(' ', 'T') + 'Z');
  if (isNaN(t)) return false;
  return (Date.now() - t) < 24 * 60 * 60 * 1000;
}

function formatWindowRemaining(last_inbound_at, channel) {
  // Show on any channel where a 24h window is relevant. We show it on
  // WhatsApp too because "how long since they messaged me" is a useful
  // signal even when Baileys doesn't enforce the window.
  if (!last_inbound_at) return null;
  if (!['whatsapp', 'messenger', 'instagram'].includes(channel)) return null;
  const t = Date.parse(last_inbound_at.replace(' ', 'T') + 'Z');
  if (isNaN(t)) return null;
  const elapsedMs = Date.now() - t;
  const remainingMs = 24 * 60 * 60 * 1000 - elapsedMs;
  if (remainingMs <= 0) return { label: 'expired', cls: 'win-expired' };
  const totalMin = Math.floor(remainingMs / 60000);
  const hours = Math.floor(totalMin / 60);
  const mins = totalMin % 60;
  const label = hours > 0 ? `${hours}h ${mins}m left` : `${mins}m left`;
  let cls;
  if (remainingMs > 6 * 3600 * 1000) cls = 'win-ok';
  else if (remainingMs > 2 * 3600 * 1000) cls = 'win-warn';
  else cls = 'win-urgent';
  return { label, cls };
}

function getPlatformDeepLink(a) {
  // Best-available link into the thread. Messenger/Instagram do not support
  // prefill URLs — user lands on Business Suite inbox with clipboard primed.
  if (a.channel === 'messenger') {
    return 'https://business.facebook.com/latest/inbox';
  }
  if (a.channel === 'instagram') {
    if (a.thread_id) return `https://www.instagram.com/direct/t/${encodeURIComponent(a.thread_id)}/`;
    return 'https://www.instagram.com/direct/inbox/';
  }
  if (a.channel === 'whatsapp') {
    // Baileys sends directly — but if this ever gets called, wa.me prefills text
    const phone = (a.identifier || '').replace(/[^0-9]/g, '');
    const text = encodeURIComponent(document.getElementById('draftText')?.value || '');
    return `https://wa.me/${phone}?text=${text}`;
  }
  return 'https://business.facebook.com/latest/inbox';
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
      toast(`Send failed: ${e.message || 'unknown error'}`);
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
// Feedback modal
// ------------------------------------------------------------------ //

function openFeedback() {
  State.lastFocus = document.activeElement;
  document.getElementById('feedbackOverlay').classList.add('open');
  document.getElementById('feedbackModal').classList.add('open');
  document.getElementById('fbRequest').focus();
}

function closeFeedback() {
  document.getElementById('feedbackOverlay').classList.remove('open');
  document.getElementById('feedbackModal').classList.remove('open');
  document.getElementById('feedbackForm').reset();
  if (State.lastFocus) State.lastFocus.focus();
}

async function handleFeedbackSubmit(e) {
  e.preventDefault();
  const btn = document.getElementById('fbSubmitBtn');
  const request = document.getElementById('fbRequest').value.trim();
  if (!request) return;

  btn.disabled = true;
  btn.textContent = 'Submitting...';

  try {
    const res = await fetch('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        request,
        workaround: document.getElementById('fbWorkaround').value.trim(),
        frequency: document.getElementById('fbFrequency').value,
        importance: document.getElementById('fbImportance').value,
        contact: document.getElementById('fbContact').value.trim(),
      }),
    });
    if (!res.ok) throw new Error(await res.text());
    closeFeedback();
    toast('Thanks for the feedback!');
  } catch (err) {
    toast('Failed: ' + (err.message || 'unknown error'));
  } finally {
    btn.disabled = false;
    btn.textContent = 'Submit Feedback';
  }
}

// ------------------------------------------------------------------ //
// Calendar
// ------------------------------------------------------------------ //

function getMonday(d) {
  const dt = new Date(d);
  const day = dt.getDay();
  const diff = dt.getDate() - day + (day === 0 ? -6 : 1);
  dt.setDate(diff);
  dt.setHours(0, 0, 0, 0);
  return dt;
}

function fmtDate(d) { return d.toISOString().slice(0, 10); }

function calNavigate(days) {
  State.calWeekStart = new Date(State.calWeekStart.getTime() + days * 86400000);
  loadCalendar();
}

async function loadCalendar() {
  const from = fmtDate(State.calWeekStart);
  const to = fmtDate(new Date(State.calWeekStart.getTime() + 7 * 86400000));

  // Update label
  const endDate = new Date(State.calWeekStart.getTime() + 6 * 86400000);
  const opts = { month: 'short', day: 'numeric' };
  document.getElementById('calLabel').textContent =
    `${State.calWeekStart.toLocaleDateString('en', opts)} – ${endDate.toLocaleDateString('en', opts)}`;

  const body = document.getElementById('calendarBody');

  try {
    const events = await api(`/api/calendar?from_date=${from}&to_date=${to}`);
    State.calEvents = events;
    renderCalendar(events);
  } catch (e) {
    body.innerHTML = '<div class="cal-empty">Could not load calendar</div>';
  }
}

function renderCalendar(events) {
  const body = document.getElementById('calendarBody');
  const today = fmtDate(new Date());
  const days = [];

  for (let i = 0; i < 7; i++) {
    const d = new Date(State.calWeekStart.getTime() + i * 86400000);
    const dateStr = fmtDate(d);
    const dayEvents = events.filter(e => e.start_at && e.start_at.startsWith(dateStr));
    days.push({ date: d, dateStr, events: dayEvents });
  }

  if (events.length === 0) {
    body.innerHTML = '<div class="cal-empty">No events this week</div>';
    return;
  }

  body.innerHTML = days.map(day => {
    if (day.events.length === 0) return '';
    const isToday = day.dateStr === today;
    const dayLabel = day.date.toLocaleDateString('en', { weekday: 'short', month: 'short', day: 'numeric' });

    const eventsHtml = day.events.map(ev => {
      const time = ev.start_at.length > 10 ? ev.start_at.slice(11, 16) : '';
      const meta = [ev.client_name, ev.location].filter(Boolean).join(' · ');
      const statusClass = ev.status === 'completed' ? ' status-completed' : '';
      return `
        <div class="cal-event type-${esc(ev.event_type)}${statusClass}" onclick="openCalEvent('${esc(ev.id)}')">
          ${time ? `<div class="cal-event-time">${esc(time)}</div>` : ''}
          <div class="cal-event-title">${esc(ev.title)}</div>
          ${meta ? `<div class="cal-event-meta">${esc(meta)}</div>` : ''}
        </div>`;
    }).join('');

    return `
      <div class="cal-day">
        <div class="cal-day-header${isToday ? ' today' : ''}">
          ${isToday ? '● ' : ''}${dayLabel}
          <span class="cal-day-count">${day.events.length}</span>
        </div>
        ${eventsHtml}
      </div>`;
  }).join('');
}

function openCalEvent(eventId) {
  const ev = State.calEvents.find(e => e.id === eventId);
  if (!ev) return;

  State.lastFocus = document.activeElement;
  const content = document.getElementById('calPanelContent');
  const time = ev.start_at.length > 10 ? ev.start_at.slice(11, 16) : '';
  const date = ev.start_at.slice(0, 10);
  const dateLabel = new Date(date + 'T00:00:00').toLocaleDateString('en', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
  const typeLabel = ev.event_type.charAt(0).toUpperCase() + ev.event_type.slice(1).replace('-', ' ');
  const statusLabel = ev.status.charAt(0).toUpperCase() + ev.status.slice(1);

  content.innerHTML = `
    <div class="panel-title">${esc(ev.title)}</div>
    <div class="panel-subtitle">${esc(typeLabel)} · ${esc(statusLabel)}</div>
    <div class="section-label">When</div>
    <div class="message-bubble">${esc(dateLabel)}${time ? ' at ' + esc(time) : ''}</div>
    ${ev.client_name ? `<div class="section-label">Client</div><div class="message-bubble">${esc(ev.client_name)}</div>` : ''}
    ${ev.location ? `<div class="section-label">Location</div><div class="message-bubble">${esc(ev.location)}</div>` : ''}
    ${ev.notes ? `<div class="section-label">Notes</div><div class="message-bubble">${esc(ev.notes)}</div>` : ''}
  `;

  const actions = document.getElementById('calPanelActions');
  const isCompleted = ev.status === 'completed';
  actions.innerHTML = `
    <button class="btn btn-ghost" onclick="editCalEvent('${esc(ev.id)}')">✏️ Edit</button>
    ${isCompleted
      ? `<button class="btn btn-warning" onclick="updateCalEventStatus('${esc(ev.id)}','scheduled')">↩️ Reopen</button>`
      : `<button class="btn btn-success" onclick="updateCalEventStatus('${esc(ev.id)}','completed')">✅ Done</button>`
    }
    <button class="btn btn-danger" onclick="deleteCalEvent('${esc(ev.id)}')">🗑 Cancel</button>
  `;
  actions.className = 'btn-row btn-row-3';

  openPanel('cal');
}

function openCalEventModal(editEvent) {
  State.lastFocus = document.activeElement;
  const form = document.getElementById('calEventForm');
  form.reset();

  if (editEvent) {
    document.getElementById('calEventTitle').textContent = '📅 Edit Event';
    document.getElementById('ceEditId').value = editEvent.id;
    document.getElementById('ceTitle').value = editEvent.title || '';
    document.getElementById('ceDate').value = editEvent.start_at ? editEvent.start_at.slice(0, 10) : '';
    document.getElementById('ceTime').value = editEvent.start_at && editEvent.start_at.length > 10 ? editEvent.start_at.slice(11, 16) : '09:00';
    document.getElementById('ceType').value = editEvent.event_type || 'meeting';
    document.getElementById('ceClient').value = editEvent.client_name || '';
    document.getElementById('ceLocation').value = editEvent.location || '';
    document.getElementById('ceNotes').value = editEvent.notes || '';
    document.getElementById('ceSubmitBtn').textContent = 'Update Event';
  } else {
    document.getElementById('calEventTitle').textContent = '📅 New Event';
    document.getElementById('ceEditId').value = '';
    document.getElementById('ceSubmitBtn').textContent = 'Create Event';
    // Default date to today
    document.getElementById('ceDate').value = fmtDate(new Date());
  }

  document.getElementById('calEventOverlay').classList.add('open');
  document.getElementById('calEventModal').classList.add('open');
  document.getElementById('ceTitle').focus();
}

function closeCalEventModal() {
  document.getElementById('calEventOverlay').classList.remove('open');
  document.getElementById('calEventModal').classList.remove('open');
  document.getElementById('calEventForm').reset();
  if (State.lastFocus) State.lastFocus.focus();
}

async function handleCalEventSubmit(e) {
  e.preventDefault();
  const btn = document.getElementById('ceSubmitBtn');
  const editId = document.getElementById('ceEditId').value;
  const title = document.getElementById('ceTitle').value.trim();
  const date = document.getElementById('ceDate').value;
  const time = document.getElementById('ceTime').value || '09:00';
  if (!title || !date) return;

  const payload = {
    title,
    start_at: `${date} ${time}`,
    event_type: document.getElementById('ceType').value,
    client_name: document.getElementById('ceClient').value.trim(),
    location: document.getElementById('ceLocation').value.trim(),
    notes: document.getElementById('ceNotes').value.trim(),
  };

  btn.disabled = true;
  btn.textContent = editId ? 'Updating...' : 'Creating...';

  try {
    if (editId) {
      const res = await fetch(`/api/calendar/${editId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());
      toast('Event updated');
    } else {
      const res = await fetch('/api/calendar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());
      toast('Event created');
    }
    closeCalEventModal();
    closePanel('cal');
    loadCalendar();
  } catch (err) {
    toast('Failed: ' + (err.message || 'unknown error'));
  } finally {
    btn.disabled = false;
    btn.textContent = editId ? 'Update Event' : 'Create Event';
  }
}

function editCalEvent(eventId) {
  const ev = State.calEvents.find(e => e.id === eventId);
  if (!ev) return;
  closePanel('cal');
  openCalEventModal(ev);
}

async function updateCalEventStatus(eventId, newStatus) {
  try {
    const res = await fetch(`/api/calendar/${eventId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus }),
    });
    if (!res.ok) throw new Error(await res.text());
    closePanel('cal');
    loadCalendar();
    toast(newStatus === 'completed' ? 'Marked as done' : 'Reopened');
  } catch (err) {
    toast('Failed: ' + (err.message || 'unknown error'));
  }
}

async function deleteCalEvent(eventId) {
  try {
    const res = await fetch(`/api/calendar/${eventId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(await res.text());
    closePanel('cal');
    loadCalendar();
    toast('Event cancelled');
  } catch (err) {
    toast('Failed: ' + (err.message || 'unknown error'));
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
  if (!res.ok) {
    // Try to extract FastAPI's {detail: "..."} for a useful message
    let detail = `HTTP ${res.status}`;
    try {
      const err = await res.json();
      if (err && err.detail) detail = err.detail;
    } catch (_) {}
    throw new Error(detail);
  }
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

// ------------------------------------------------------------------ //
// WhatsApp connect modal
// ------------------------------------------------------------------ //

async function openWaModal() {
  State.lastFocus = document.activeElement;
  document.getElementById('waOverlay').classList.add('open');
  document.getElementById('waModal').classList.add('open');
  renderWaModal({ state: 'loading' });
  await waRefresh();
  // Poll while open — every 2s catches QR updates and the moment of connection
  if (State.waPollTimer) clearInterval(State.waPollTimer);
  State.waPollTimer = setInterval(waRefresh, 2000);
}

function closeWaModal() {
  document.getElementById('waOverlay').classList.remove('open');
  document.getElementById('waModal').classList.remove('open');
  if (State.waPollTimer) { clearInterval(State.waPollTimer); State.waPollTimer = null; }
  if (State.lastFocus) State.lastFocus.focus();
}

async function waRefresh() {
  try {
    const res = await fetch('/api/whatsapp/qr');
    const data = await res.json();
    // data: { state, qr_data_url, phone, error? }
    State.waLastState = data.state;
    updateWaHeaderPill(data.state, data.phone);
    renderWaModal(data);
  } catch (e) {
    renderWaModal({ state: 'unreachable', error: e.message });
  }
}

function updateWaHeaderPill(state, phone) {
  const icon = document.getElementById('hsWaIcon');
  const label = document.getElementById('hsWaLabel');
  if (!icon || !label) return;
  if (state === 'connected') {
    icon.textContent = '✅';
    label.textContent = phone ? ('+' + phone) : 'Connected';
  } else if (state === 'qr' || state === 'connecting') {
    icon.textContent = '🟡';
    label.textContent = 'Connecting';
  } else {
    icon.textContent = '💬';
    label.textContent = 'WhatsApp';
  }
}

function renderWaModal(data) {
  const body = document.getElementById('waBody');
  if (!body) return;
  const state = data.state || 'disconnected';

  if (state === 'loading') {
    body.innerHTML = `<div class="text-center py-6 text-[var(--muted)]">Loading...</div>`;
    return;
  }

  if (state === 'unreachable') {
    body.innerHTML = `
      <div class="text-center py-6">
        <div class="text-lg mb-2">⚠️ Service unreachable</div>
        <div class="text-sm text-[var(--muted)] mb-4">
          The WhatsApp service isn't running in this tenant. Contact support.
        </div>
        <div class="text-xs text-[var(--muted)]">${data.error || ''}</div>
      </div>`;
    return;
  }

  if (state === 'connected') {
    const phone = data.phone ? ('+' + data.phone) : '(unknown)';
    body.innerHTML = `
      <div class="text-center py-4">
        <div style="font-size:3rem">✅</div>
        <div class="text-lg font-semibold mt-2">WhatsApp connected</div>
        <div class="text-sm text-[var(--muted)] mt-1">Linked as <strong>${phone}</strong></div>
        <div class="text-xs text-[var(--muted)] mt-4 mb-6">
          Incoming messages will appear in the Inbox for your approval.
        </div>
        <button class="btn" id="waDisconnectBtn">Disconnect</button>
      </div>`;
    document.getElementById('waDisconnectBtn').addEventListener('click', waDisconnect);
    return;
  }

  if (state === 'qr' && data.qr_data_url) {
    body.innerHTML = `
      <div class="text-center">
        <div class="text-sm text-[var(--muted)] mb-3">
          On your phone: <strong>WhatsApp → Settings → Linked Devices → Link a Device</strong>,
          then scan this code:
        </div>
        <img src="${data.qr_data_url}" alt="WhatsApp QR code"
             style="width:260px;height:260px;margin:0 auto;display:block;background:white;padding:8px;border-radius:8px;">
        <div class="text-xs text-[var(--muted)] mt-3">
          QR refreshes automatically. Keep this window open until connection succeeds.
        </div>
      </div>`;
    return;
  }

  if (state === 'connecting') {
    body.innerHTML = `
      <div class="text-center py-6">
        <div style="font-size:2.5rem">🟡</div>
        <div class="text-sm text-[var(--muted)] mt-3">Preparing connection, waiting for QR...</div>
      </div>`;
    return;
  }

  // disconnected (or error)
  const errMsg = data.error ? `<div class="text-xs" style="color:var(--danger);margin-top:8px">${data.error}</div>` : '';
  body.innerHTML = `
    <div class="text-center py-4">
      <div style="font-size:2.5rem">💬</div>
      <div class="text-lg font-semibold mt-2">Connect your WhatsApp</div>
      <div class="text-sm text-[var(--muted)] mt-2 mb-5">
        Links your WhatsApp as a companion device — same mechanism as WhatsApp Web.
        Your phone does <em>not</em> need to stay online after setup.
      </div>
      <button class="btn btn-primary" id="waConnectBtn">Show QR code</button>
      ${errMsg}
    </div>`;
  document.getElementById('waConnectBtn').addEventListener('click', waConnect);
}

async function waConnect() {
  try {
    await fetch('/api/whatsapp/connect', { method: 'POST' });
    // QR will appear on the next poll tick
    await waRefresh();
  } catch (e) {
    toast('Failed to start connection: ' + e.message);
  }
}

async function waDisconnect() {
  if (!confirm('Disconnect WhatsApp? You will need to scan a new QR to reconnect.')) return;
  try {
    await fetch('/api/whatsapp/disconnect', { method: 'POST' });
    await waRefresh();
    toast('WhatsApp disconnected');
  } catch (e) {
    toast('Disconnect failed: ' + e.message);
  }
}

// On page load, do a single silent status check so the header pill reflects reality
(async function waInitialStatus() {
  try {
    const res = await fetch('/api/whatsapp/status');
    if (!res.ok) return;
    const d = await res.json();
    updateWaHeaderPill(d.state, d.phone);
  } catch (e) { /* ignore */ }
})();

// ------------------------------------------------------------------ //
// Channels (Meta: Messenger + Instagram) connect modal
// ------------------------------------------------------------------ //

async function openChannelsModal() {
  State.lastFocus = document.activeElement;
  document.getElementById('channelsOverlay').classList.add('open');
  document.getElementById('channelsModal').classList.add('open');
  renderChannelsModal({ loading: true });
  await refreshChannelsModal();
}

function closeChannelsModal() {
  document.getElementById('channelsOverlay').classList.remove('open');
  document.getElementById('channelsModal').classList.remove('open');
  if (State.lastFocus) State.lastFocus.focus();
}

async function refreshChannelsModal() {
  try {
    const status = await api('/api/channels/meta/status');
    renderChannelsModal(status);
    updateChannelsHeaderPill(status);
  } catch (e) {
    renderChannelsModal({ error: e.message });
  }
}

function updateChannelsHeaderPill(status) {
  const label = document.getElementById('hsChannelsLabel');
  if (!label) return;
  const count = (status.connections || []).filter(c => c.status === 'connected').length;
  label.textContent = count > 0 ? `Channels (${count})` : 'Channels';
}

function renderChannelsModal(data) {
  const body = document.getElementById('channelsBody');
  if (!body) return;

  if (data.loading) {
    body.innerHTML = '<div class="text-center py-6 text-[var(--muted)]">Loading…</div>';
    return;
  }
  if (data.error) {
    body.innerHTML = `<div class="text-center py-6" style="color:var(--danger)">${esc(data.error)}</div>`;
    return;
  }

  const configured = data.configured;
  const conns = Object.fromEntries((data.connections || []).map(c => [c.channel, c]));
  const mess = conns['messenger'];
  const ig = conns['instagram'];

  const row = (channel, label, icon, conn) => {
    if (!configured) {
      return `
        <div class="ch-row">
          <div class="ch-icon">${icon}</div>
          <div class="ch-meta">
            <div class="ch-name">${label}</div>
            <div class="ch-status text-[var(--muted)]">Not configured yet</div>
          </div>
        </div>`;
    }
    if (conn && conn.status === 'connected') {
      const name = conn.page_name || conn.page_id;
      return `
        <div class="ch-row">
          <div class="ch-icon">${icon}</div>
          <div class="ch-meta">
            <div class="ch-name">${label}</div>
            <div class="ch-status" style="color:#059669">✓ Connected as ${esc(name)}</div>
          </div>
          <button class="btn btn-ghost" data-disconnect="${channel}">Disconnect</button>
        </div>`;
    }
    if (conn && conn.status === 'needs_reconnect') {
      return `
        <div class="ch-row">
          <div class="ch-icon">${icon}</div>
          <div class="ch-meta">
            <div class="ch-name">${label}</div>
            <div class="ch-status" style="color:#b91c1c">⚠ Token expired — reconnect needed</div>
          </div>
          <button class="btn btn-primary" data-connect="${channel}">Reconnect</button>
        </div>`;
    }
    return `
      <div class="ch-row">
        <div class="ch-icon">${icon}</div>
        <div class="ch-meta">
          <div class="ch-name">${label}</div>
          <div class="ch-status text-[var(--muted)]">Not connected</div>
        </div>
        <button class="btn btn-primary" data-connect="${channel}">Connect</button>
      </div>`;
  };

  const configNote = !configured ? `
    <div class="ch-note">
      Your Meta App isn't configured on this tenant yet. An admin needs to set
      <code>META_APP_ID</code>, <code>META_APP_SECRET</code>, <code>META_VERIFY_TOKEN</code>,
      and <code>META_REDIRECT_URI</code> before Messenger/Instagram can be connected.
      See <code>docs/meta-app-setup.md</code>.
    </div>` : '';

  body.innerHTML = `
    <div class="ch-list">
      ${row('messenger', 'Facebook Messenger', '💬', mess)}
      ${row('instagram', 'Instagram Direct', '📸', ig)}
    </div>
    ${configNote}
    <div class="text-xs text-[var(--muted)] mt-4">
      WhatsApp is managed separately — see the WhatsApp button.
    </div>`;

  body.querySelectorAll('[data-connect]').forEach(btn => {
    btn.addEventListener('click', () => startMetaConnect(btn.dataset.connect));
  });
  body.querySelectorAll('[data-disconnect]').forEach(btn => {
    btn.addEventListener('click', () => disconnectMeta(btn.dataset.disconnect));
  });
}

async function startMetaConnect(_channel) {
  try {
    const r = await api('/api/channels/meta/login-url');
    // Open the Facebook OAuth dialog in a popup. After they complete it,
    // the callback redirects back to /?meta_connected=1. We poll every 2s
    // to catch the state change.
    const popup = window.open(r.url, 'meta_oauth', 'width=600,height=700');
    if (!popup) {
      toast('Popup blocked — please allow popups and try again');
      return;
    }
    const poll = setInterval(async () => {
      try {
        if (popup.closed) {
          clearInterval(poll);
          await refreshChannelsModal();
          return;
        }
      } catch (_) { /* cross-origin during OAuth is fine */ }
    }, 2000);
  } catch (e) {
    toast('Failed to start: ' + e.message);
  }
}

async function disconnectMeta(channel) {
  if (!confirm(`Disconnect ${channel}? Inbound messages will stop arriving until you reconnect.`)) return;
  try {
    await api('/api/channels/meta/disconnect', 'POST', { channel });
    await refreshChannelsModal();
    toast('Disconnected');
  } catch (e) {
    toast('Disconnect failed: ' + e.message);
  }
}

// Initial status check on page load — updates the header pill silently
(async function channelsInitialStatus() {
  try {
    const r = await fetch('/api/channels/meta/status');
    if (!r.ok) return;
    const d = await r.json();
    updateChannelsHeaderPill(d);
  } catch (_) { /* ignore */ }
})();

// Detect OAuth callback redirect: ?meta_connected=1 or ?meta_error=...
(function detectOAuthReturn() {
  const params = new URLSearchParams(location.search);
  if (params.has('meta_connected')) {
    toast('✓ Channel connected');
    // Strip the query param so reload doesn't re-toast
    history.replaceState({}, '', location.pathname);
    setTimeout(refreshChannelsModal, 500);
  } else if (params.has('meta_error')) {
    toast('Connection failed: ' + params.get('meta_error'));
    history.replaceState({}, '', location.pathname);
  }
})();
