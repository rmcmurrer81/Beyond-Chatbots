'use strict';
const $ = id => document.getElementById(id);
const storageKey = 'aster.remote.outbox.v1';
let token = '', timer = null, busy = false, generation = 0, controller = null;
const now = () => Date.now() / 1000;
function load() {
  try {
    const data = JSON.parse(localStorage.getItem(storageKey) || '[]');
    return Array.isArray(data) ? data.filter(x => x && /^[a-f0-9]{32}$/.test(x.id) && typeof x.body === 'string' && new TextEncoder().encode(x.body).length <= 4096 && Number.isFinite(x.expires) && x.expires > now() && x.expires <= now() + 86400).slice(0, 50) : [];
  } catch { return []; }
}
let outbox = load();
function save() {
  localStorage.setItem(storageKey, JSON.stringify(outbox));
  $('queue').textContent = `${outbox.length} message(s) waiting to reach the relay.`;
}
async function call(path, body, signal) {
  const r = await fetch(path, {method: body ? 'POST' : 'GET', headers: {'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined, signal, credentials: 'omit', redirect: 'error', cache: 'no-store'});
  if (!r.ok) { const e = new Error(`Relay returned ${r.status}`); e.status = r.status; throw e; }
  return r.json();
}
function stop() {
  token = ''; generation++; clearInterval(timer); timer = null;
  if (controller) controller.abort();
  $('key').value = '';
  $('status').textContent = 'Disconnected. Delivery stopped; unsent messages remain on this device.';
}
async function sync() {
  if (busy || !token) return;
  busy = true; const active = generation; controller = new AbortController();
  const timeout = setTimeout(() => controller?.abort(), 10000);
  try {
    outbox = outbox.filter(x => x.expires > now()); save();
    for (const item of [...outbox]) {
      await call('/v1/messages', item, controller.signal);
      if (active !== generation) return;
      outbox = outbox.filter(x => x.id !== item.id); save();
    }
    const data = await call('/v1/inbox', undefined, controller.signal);
    if (active !== generation) return;
    if (!Array.isArray(data.messages) || data.messages.length > 50) throw new Error('Invalid relay inbox');
    for (const item of data.messages) {
      if (!item || !/^[a-f0-9]{32}$/.test(item.id) || typeof item.body !== 'string' || new TextEncoder().encode(item.body).length > 4096) throw new Error('Invalid receipt');
      if (!document.getElementById(`receipt-${item.id}`)) {
        const li = document.createElement('li'); li.id = `receipt-${item.id}`;
        li.textContent = item.body; $('receipts').prepend(li);
        while ($('receipts').children.length > 100) $('receipts').lastChild.remove();
      }
      await call('/v1/ack', {id: item.id}, controller.signal);
      if (active !== generation) return;
    }
    $('status').textContent = 'Relay connected. Workstation delivery is confirmed only by a receipt below.';
  } catch (e) {
    if (active !== generation) return;
    if (e.status === 401) { stop(); $('status').textContent = 'Pairing missing, invalid or expired. Ask the owner to renew it.'; }
    else $('status').textContent = 'Delivery paused. Will retry while connected; unsent messages stay on this device.';
  } finally { clearTimeout(timeout); busy = false; }
}
$('connect').addEventListener('click', () => {
  if (!window.isSecureContext) { $('status').textContent = 'HTTPS required outside localhost.'; return; }
  const key = $('key').value.trim();
  if (key.length < 32 || key.length > 256) { $('status').textContent = 'Enter your owner-provisioned companion key.'; return; }
  stop(); token = key; timer = setInterval(sync, 10000); sync();
});
$('stop').addEventListener('click', stop);
$('clear').addEventListener('click', () => { stop(); outbox = []; save(); $('receipts').replaceChildren(); $('status').textContent = 'Saved messages cleared. Disconnected; already sent messages cannot be recalled.'; });
$('compose').addEventListener('submit', e => {
  e.preventDefault(); const body = $('prompt').value.trim();
  if (!body || new TextEncoder().encode(body).length > 4096 || outbox.length >= 50) { $('queue').textContent = 'Use 1–4096 UTF-8 bytes. Queue limit is 50 messages.'; return; }
  const item = {id: crypto.randomUUID().replaceAll('-', ''), body, expires: now() + 86400};
  outbox.push(item);
  try { save(); $('prompt').value = ''; sync(); } catch { outbox.pop(); $('queue').textContent = 'Device storage unavailable. Message was not queued.'; }
});
try { save(); } catch { $('queue').textContent = 'Device storage unavailable.'; }
if ('serviceWorker' in navigator && window.isSecureContext) navigator.serviceWorker.register('/sw.js').catch(() => {});
