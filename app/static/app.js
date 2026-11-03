let lastPack = "";

function err(msg){
  const el = document.getElementById('err');
  if(!msg){ el.classList.add('hidden'); return; }
  el.textContent = msg; el.classList.remove('hidden');
}
async function api(path, opts={}){
  const r = await fetch(path, {headers:{'Content-Type':'application/json'}, ...opts});
  if (r.status === 401){ location.href = '/'; throw new Error('signed out'); }
  const data = await r.json().catch(()=>({}));
  if (!r.ok) throw new Error(data.detail || 'Something went wrong.');
  return data;
}
function esc(s){ return (s||'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

function show(view){
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.view === view));
  ['memory','inbox','add','use','settings'].forEach(v => document.getElementById('view-'+v).classList.toggle('hidden', v !== view));
  if (view === 'memory') loadMemories();
  if (view === 'inbox') loadInbox();
  if (view === 'settings') loadKeys();
}

async function refreshMe(){
  const me = await api('/api/me');
  document.getElementById('who').textContent = me.email;
  document.getElementById('planbadge').textContent = me.plan === 'pro' ? 'Pro plan' : 'Free plan';
  document.getElementById('upgradeBtn').classList.toggle('hidden', me.plan === 'pro');
  const u = me.usage;
  document.getElementById('inboxcount').textContent = u.pending ? u.pending + ' waiting' : '';
  const bar = document.getElementById('usagebar');
  if (me.plan === 'free'){
    bar.classList.remove('hidden');
    bar.textContent = `Free plan: ${u.active_memories} of ${u.active_limit} understandings used, ${u.packs_this_month} of ${u.packs_limit} assembled contexts used this month. Pro removes both limits.`;
  } else bar.classList.add('hidden');
  const cov = document.getElementById('coverage');
  if (me.coverage && me.coverage.length) {
    cov.classList.remove('hidden');
    cov.innerHTML = '<strong>Understanding coverage:</strong> ' +
      me.coverage.map(c => `${c.covered ? '✓' : '✗'} ${esc(c.label)}`).join(' · ');
  }
}

async function loadMemories(){
  try{
    const q = document.getElementById('search').value || '';
    const data = await api('/api/memories?status=active&q=' + encodeURIComponent(q));
    const el = document.getElementById('memlist');
    if (!data.memories.length){ el.innerHTML = '<div class="card"><p>Nothing here yet. Teach it something in the Teach it tab, or check your inbox.</p></div>'; return; }
    el.innerHTML = data.memories.map(m => `
      <div class="mem">
        <div class="spread"><span class="meta">${esc(m.kind)}${m.project ? ' · ' + esc(m.project) : ''}${m.pinned ? ' · pinned' : ''}${m.expires_at ? ' · expires ' + esc(m.expires_at) : ''}</span>
        <span class="meta">from ${esc(m.source)}</span></div>
        <div class="body"><strong>${esc(m.title)}:</strong> ${esc(m.body)}</div>
        <div class="row">
          <button class="btn ghost small" onclick="togglePin(${m.id}, ${m.pinned ? 0 : 1})">${m.pinned ? 'Unpin' : 'Pin to every pack'}</button>
          <button class="btn ghost small" onclick="archiveMem(${m.id})">Archive</button>
        </div>
      </div>`).join('');
    err('');
  }catch(e){ err(e.message); }
}

async function loadInbox(){
  try{
    const data = await api('/api/memories?status=pending');
    const el = document.getElementById('inboxlist');
    if (!data.memories.length){ el.innerHTML = '<div class="card"><p>Your inbox is clear. Import an export or paste a conversation in Add memory and new understandings will land here.</p></div>'; return; }
    el.innerHTML = data.memories.map(m => `
      <div class="mem" id="mem-${m.id}">
        <div class="meta">${esc(m.kind)} · found in ${esc(m.source)}${m.support_count >= 2 ? ` · noticed independently by ${m.support_count} extractors` : ''}</div>
        <div class="body"><strong>${esc(m.title)}:</strong> ${esc(m.body)}</div>
        ${m.kind === 'unknown' ? '<div class="quote">An open question, not a claim. Approve to keep it as a known gap an assistant should not guess at, or reject it.</div>' : (m.source_quote ? `<div class="quote">Evidence: "${esc(m.source_quote)}"</div>` : '')}
        ${m.replaces ? `<div class="replaces">This replaces what your memory says now: "${esc(m.replaces)}"</div>` : ''}
        <div class="row">
          <button class="btn small" onclick="approve(${m.id})">Approve</button>
          <button class="btn danger small" onclick="reject(${m.id})">Reject</button>
        </div>
      </div>`).join('');
    err('');
  }catch(e){ err(e.message); }
}

async function approve(id){
  try{
    await api(`/api/memories/${id}/approve`, {method:'POST'});
    refreshMe();
    const card = document.getElementById('mem-' + id);
    if (card) {
      card.innerHTML = `<div class="body">Approved.</div>
        <div class="quote">One quick question, it makes the importer better: how surprised were you that we figured this out?</div>
        <div class="row">
          <button class="btn small" onclick="rateSurprise(${id}, 0)">Not surprised</button>
          <button class="btn small" onclick="rateSurprise(${id}, 1)">A little surprised</button>
          <button class="btn small" onclick="rateSurprise(${id}, 2)">Very surprised</button>
        </div>`;
    } else loadInbox();
  }catch(e){ err(e.message); }
}
async function rateSurprise(id, level){
  try{ await api(`/api/memories/${id}/surprise`, {method:'POST', body: JSON.stringify({level})}); }catch(e){ /* the rating is a bonus, never block the flow */ }
  loadInbox();
}
async function reject(id){ try{ await api(`/api/memories/${id}/reject`, {method:'POST'}); loadInbox(); refreshMe(); }catch(e){ err(e.message); } }
async function archiveMem(id){ try{ await api(`/api/memories/${id}/archive`, {method:'POST'}); loadMemories(); refreshMe(); }catch(e){ err(e.message); } }
async function togglePin(id, pinned){ try{ await api(`/api/memories/${id}`, {method:'PATCH', body: JSON.stringify({pinned: !!pinned})}); loadMemories(); }catch(e){ err(e.message); } }

async function quickAdd(){
  try{
    const body = document.getElementById('qa-body').value.trim();
    if(!body) return;
    await api('/api/memories', {method:'POST', body: JSON.stringify({
      kind: document.getElementById('qa-kind').value,
      title: document.getElementById('qa-title').value.trim() || 'Memory',
      body, project: document.getElementById('qa-project').value.trim()})});
    document.getElementById('qa-msg').textContent = 'Saved. It is in your assembled context from now on.';
    document.getElementById('qa-body').value = '';
    refreshMe();
  }catch(e){ err(e.message); }
}

async function extractPaste(){
  try{
    const text = document.getElementById('paste-text').value;
    const data = await api('/api/extract', {method:'POST', body: JSON.stringify({text, source:'pasted text'})});
    document.getElementById('paste-msg').textContent = data.added
      ? `Found ${data.added} new proposed understandings. Review them in your inbox.`
      : 'No durable understandings found in that text. Try the starter questions, or add one at a time.';
    refreshMe();
  }catch(e){ err(e.message); }
}

async function importFile(){
  const input = document.getElementById('import-file');
  if (!input.files.length) return;
  const fd = new FormData(); fd.append('file', input.files[0]);
  document.getElementById('import-msg').textContent =
    'Reading your conversations and building understandings. This usually takes under a minute.';
  try{
    const r = await fetch('/api/import', {method:'POST', body: fd});
    const data = await r.json().catch(()=>({}));
    if (!r.ok) throw new Error(data.detail || 'Import failed.');
    const el = document.getElementById('import-msg');
    let html = `Read ${data.messages_scanned} of your messages across ${data.conversations_scanned} conversations and proposed ${data.added} understandings. Review them in your inbox.`;
    if (data.top_insights && data.top_insights.length) {
      html += '<br><br><strong>It already knows things like:</strong>' +
        data.top_insights.map(t => `<br>· ${esc(t.body)}`).join('');
    }
    el.innerHTML = html;
    refreshMe();
  }catch(e){ err(e.message); }
}

async function starter(){
  const answers = {};
  ['name_role','work','projects','preferences','tools_style','people'].forEach(k => answers[k] = document.getElementById('st-'+k).value);
  try{
    const data = await api('/api/starter', {method:'POST', body: JSON.stringify({answers})});
    document.getElementById('st-msg').textContent = data.added
      ? `${data.added} starter understandings are waiting in your inbox for approval.`
      : 'Those answers matched what you already have. Nothing new to approve.';
    refreshMe();
  }catch(e){ err(e.message); }
}

async function makePack(){
  try{
    const data = await api('/api/packs', {method:'POST', body: JSON.stringify({
      target: document.getElementById('pack-target').value,
      project: document.getElementById('pack-project').value.trim()})});
    lastPack = data.pack.body;
    const out = document.getElementById('packout');
    out.textContent = lastPack; out.classList.remove('hidden');
    document.getElementById('copyBtn').classList.remove('hidden');
    refreshMe();
  }catch(e){ err(e.message); }
}
async function copyPack(){ try{ await navigator.clipboard.writeText(lastPack); }catch(e){ err('Copy failed in this browser. Select the text and copy it manually.'); } }

async function upgrade(){
  try{ const data = await api('/api/upgrade', {method:'POST'}); alert(data.note); refreshMe(); }
  catch(e){ err(e.message); }
}
async function createKey(){
  try{
    const name = document.getElementById('key-name').value.trim() || 'My assistants';
    const data = await api('/api/keys', {method:'POST', body: JSON.stringify({name})});
    document.getElementById('newkey').classList.remove('hidden');
    document.getElementById('newkey-value').textContent = data.key;
    document.getElementById('newkey-config').textContent =
      'Server URL: ' + location.origin + '/mcp\nAuthorization header: Bearer ' + data.key;
    loadKeys();
  }catch(e){ err(e.message); }
}
async function loadKeys(){
  try{
    const data = await api('/api/keys');
    const el = document.getElementById('keylist');
    el.innerHTML = data.keys.length ? data.keys.map(k => `
      <div class="mem"><div class="spread"><span><strong>${esc(k.name)}</strong> · ${esc(k.prefix)}...</span>
      <button class="btn danger small" onclick="revokeKey(${k.id})">Revoke</button></div>
      <div class="meta">created ${esc(k.created_at)}${k.last_used_at ? ' · last used ' + esc(k.last_used_at) : ' · never used'}</div></div>`).join('')
      : '<p class="sub">No API keys yet.</p>';
  }catch(e){ err(e.message); }
}
async function revokeKey(id){ try{ await api('/api/keys/' + id, {method:'DELETE'}); loadKeys(); }catch(e){ err(e.message); } }

function exportData(){ window.location = '/api/export'; }

async function deleteAccount(){
  const password = document.getElementById('delete-password').value;
  if (!password) { err('Enter your password to confirm deletion.'); return; }
  if (!confirm('Delete your account and ALL of your data? This cannot be undone.')) return;
  try{
    const r = await fetch('/api/account', {method:'DELETE', headers:{'Content-Type':'application/json'}, body: JSON.stringify({password})});
    const data = await r.json().catch(()=>({}));
    if (!r.ok) throw new Error(data.detail || 'Deletion failed.');
    alert('Your account and all of its data are deleted.');
    location.href = '/';
  }catch(e){ err(e.message); }
}

async function logout(){ await fetch('/api/logout', {method:'POST'}); location.href = '/'; }

refreshMe().then(() => loadMemories()).catch(e => err(e.message));
