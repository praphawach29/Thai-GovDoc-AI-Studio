// studio.js — ส่วนกลางของหน้าเว็บ GovDoc Studio: เรียก API, เก็บร่างในเครื่อง, ตัวช่วยข้อความไทย
(function () {
  const API = '/api/v1';

  async function request(path, options = {}) {
    const res = await fetch(API + path, options);
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (_) { /* ไม่ใช่ JSON */ }
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return res;
  }
  const postJSON = (path, body) => request(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });

  const api = {
    profile: () => request('/studio/profile').then(r => r.json()),
    draft: (formData) => request('/studio/draft', { method: 'POST', body: formData }).then(r => r.json()),
    blank: (docType) => postJSON('/studio/blank', { doc_type: docType }).then(r => r.json()),
    check: (doc) => postJSON('/studio/check', doc).then(r => r.json()),
    refine: (text, command) => postJSON('/copilot/refine', { text, command }).then(r => r.json()),
    exportDocx: (doc) => postJSON('/export/docx', doc).then(r => r.blob()),
    exportPdf: (doc) => postJSON('/export/pdf', doc).then(r => r.blob()),
  };

  // ---------- ร่างที่เก็บในเบราว์เซอร์นี้ (ยังไม่มีฐานข้อมูลกลาง) ----------
  const KEY = 'govdoc.studio.docs.v1';
  function readAll() {
    try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch (_) { return []; }
  }
  function writeAll(list) {
    try { localStorage.setItem(KEY, JSON.stringify(list.slice(0, 30))); return true; } catch (_) { return false; }
  }
  const store = {
    list: () => readAll().sort((a, b) => (b.updated || '').localeCompare(a.updated || '')),
    get: (id) => readAll().find(x => x.id === id) || null,
    save(entry) {
      const list = readAll().filter(x => x.id !== entry.id);
      entry.updated = new Date().toISOString();
      list.unshift(entry);
      return writeAll(list);
    },
    remove(id) { writeAll(readAll().filter(x => x.id !== id)); },
    newId: () => 'd' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
  };

  // ---------- ตัวช่วยข้อความ ----------
  const THAI = '๐๑๒๓๔๕๖๗๘๙';
  const toThai = (s) => String(s).replace(/[0-9]/g, d => THAI[+d]);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const PH_RE = /\[(?:✏️\s*)?ระบุ[^\]]*\]|\{\{[^}]+\}\}/g;
  const hasPlaceholder = (s) => { PH_RE.lastIndex = 0; return PH_RE.test(String(s || '')); };
  function relTime(iso) {
    if (!iso) return '';
    const sec = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
    if (sec < 45) return 'เมื่อสักครู่';
    if (sec < 3600) return toThai(Math.round(sec / 60)) + ' นาทีที่แล้ว';
    if (sec < 86400) return toThai(Math.round(sec / 3600)) + ' ชั่วโมงที่แล้ว';
    return toThai(Math.round(sec / 86400)) + ' วันที่แล้ว';
  }
  function download(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement('a'), { href: url, download: filename });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }
  function toast(message, tone = 'ok') {
    const el = document.createElement('div');
    const color = tone === 'error' ? 'bg-rose-600' : tone === 'warn' ? 'bg-amber-600' : 'bg-slate-900';
    el.className = `fixed bottom-6 left-1/2 -translate-x-1/2 z-[100] px-4 py-2.5 rounded-xl text-white text-xs shadow-lg animate-fadeIn ${color}`;
    el.setAttribute('role', 'status');
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3600);
  }

  const DOC_TYPE_LABEL = { internal: 'บันทึกข้อความ', external: 'หนังสือภายนอก' };
  const URGENCY = {
    normal: { label: 'ปกติ', cls: 'bg-slate-100 text-slate-600 border-slate-200' },
    urgent: { label: 'ด่วน', cls: 'bg-amber-50 text-amber-700 border-amber-200' },
    very_urgent: { label: 'ด่วนมาก', cls: 'bg-rose-50 text-rose-600 border-rose-200' },
    most_urgent: { label: 'ด่วนที่สุด', cls: 'bg-rose-600 text-white border-rose-600' },
  };
  const SECRET = {
    normal: { label: 'ปกติ', cls: 'bg-slate-100 text-slate-600 border-slate-200' },
    secret: { label: 'ลับ', cls: 'bg-amber-50 text-amber-800 border-amber-200' },
    very_secret: { label: 'ลับมาก', cls: 'bg-rose-50 text-rose-700 border-rose-200' },
    top_secret: { label: 'ลับที่สุด', cls: 'bg-rose-600 text-white border-rose-600' },
  };

  window.GovDoc = { api, store, toThai, esc, PH_RE, hasPlaceholder, relTime, download, toast, DOC_TYPE_LABEL, URGENCY, SECRET };
})();
GovDoc.api.templates = () => fetch('/api/v1/studio/templates').then(r => r.json());
GovDoc.api.template = (id) => fetch('/api/v1/studio/templates/' + encodeURIComponent(id)).then(r => { if (!r.ok) throw new Error('ไม่พบแม่แบบ'); return r.json(); });
GovDoc.api.legal = () => fetch('/api/v1/legal/references').then(r => r.json());
GovDoc.api.health = () => fetch('/api/v1/health').then(r => r.ok);
