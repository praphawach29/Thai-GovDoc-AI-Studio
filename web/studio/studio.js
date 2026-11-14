// studio.js — ส่วนกลางของหน้าเว็บ GovDoc Studio: เรียก API, เก็บร่าง, ตัวช่วยข้อความไทย
// ต้องโหลด auth.js ก่อนไฟล์นี้
(function () {
  const API = '/api/v1';
  const auth = window.GovDocAuth;

  async function request(path, options = {}) {
    const token = await auth.token();
    const headers = { ...(options.headers || {}) };
    if (token) headers.Authorization = `Bearer ${token}`;
    const res = await fetch(API + path, { ...options, headers });
    if (res.status === 401 && token !== null) { auth.signOut(); throw new Error('หมดเวลาเข้าสู่ระบบ'); }
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (_) { /* ไม่ใช่ JSON */ }
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return res;
  }
  const sendJSON = (method, path, body) => request(path, {
    method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const postJSON = (path, body) => sendJSON('POST', path, body);

  const api = {
    profile: () => request('/studio/profile').then(r => r.json()),
    draft: (formData) => request('/studio/draft', { method: 'POST', body: formData }).then(r => r.json()),
    blank: (docType) => postJSON('/studio/blank', { doc_type: docType }).then(r => r.json()),
    check: (doc) => postJSON('/studio/check', doc).then(r => r.json()),
    refine: (text, command) => postJSON('/copilot/refine', { text, command }).then(r => r.json()),
    exportDocx: (doc) => postJSON('/export/docx', doc).then(r => r.blob()),
    exportPdf: (doc) => postJSON('/export/pdf', doc).then(r => r.blob()),
    templates: () => request('/studio/templates').then(r => r.json()),
    template: (id) => request('/studio/templates/' + encodeURIComponent(id)).then(r => r.json()),
    legal: () => request('/legal/references').then(r => r.json()),
    health: () => fetch(API + '/health').then(r => r.ok),
    me: () => request('/me').then(r => r.json()),
    // โหมดเซิร์ฟเวอร์: อัปโหลดไฟล์ต้นเรื่องตรงเข้า Supabase Storage (ไม่ผ่าน API ซึ่งรับไฟล์ใหญ่ไม่ได้)
    async uploadSource(file) {
      const { path, upload_url } = await postJSON('/sources/upload-url', { filename: file.name, size_bytes: file.size }).then(r => r.json());
      const body = new FormData();
      body.append('cacheControl', '3600');
      body.append('', file);
      // ส่ง apikey (publishable key ซึ่งเปิดเผยได้) แบบเดียวกับ supabase-js; สิทธิ์อัปโหลดมาจาก token ใน URL
      const { supabase_publishable_key: apikey } = await auth.config();
      const res = await fetch(upload_url, { method: 'PUT', body, headers: { 'x-upsert': 'false', apikey } });
      if (!res.ok) throw new Error('อัปโหลดไฟล์ต้นเรื่องไม่สำเร็จ');
      return path;
    },
  };

  // ---------- ที่เก็บร่าง ----------
  // โหมดเครื่องเดียว: localStorage ของเบราว์เซอร์นี้
  // โหมดเซิร์ฟเวอร์ (Supabase): ร่างที่กำลังแก้เก็บที่ documents.workspace, จุดบันทึกที่ document_versions
  const KEY = 'govdoc.studio.docs.v1';
  function readAll() {
    try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch (_) { return []; }
  }
  function writeAll(list) {
    try { localStorage.setItem(KEY, JSON.stringify(list.slice(0, 30))); return true; } catch (_) { return false; }
  }
  const localStore = {
    async list() { return readAll().sort((a, b) => (b.updated || '').localeCompare(a.updated || '')); },
    async get(id) { return readAll().find(x => x.id === id) || null; },
    async save(entry) {
      const list = readAll().filter(x => x.id !== entry.id);
      entry.updated = new Date().toISOString();
      list.unshift(entry);
      return writeAll(list);
    },
    async create(entry) {
      entry.id = 'd' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
      if (!(await localStore.save(entry))) throw new Error('พื้นที่เก็บในเบราว์เซอร์เต็ม — ลบเอกสารเก่าก่อน');
      return entry.id;
    },
    async snapshot() { /* โหมดเครื่องเดียวเก็บประวัติใน entry.versions อยู่แล้ว */ },
    where: 'ในเครื่องนี้',
  };
  const split = (entry) => {
    const { id, title, updated, doc, ...workspace } = entry;
    return { doc, workspace };
  };
  const serverStore = {
    async list() {
      const rows = await request('/documents?limit=50').then(r => r.json());
      return rows.map(r => ({ id: r.id, title: r.subject, updated: r.updated_at, doc: { urgency: r.urgency }, docNumber: r.doc_number, status: r.status }));
    },
    async get(id) {
      try {
        const r = await request('/documents/' + encodeURIComponent(id)).then(x => x.json());
        return { ...(r.workspace || {}), id: r.id, title: r.subject, updated: r.updated_at, status: r.status };
      } catch (_) { return null; }
    },
    async save(entry) {
      const r = await sendJSON('PATCH', '/documents/' + encodeURIComponent(entry.id), split(entry)).then(x => x.json());
      entry.updated = r.updated_at || new Date().toISOString();
      return true;
    },
    async create(entry) {
      const r = await postJSON('/documents', split(entry)).then(x => x.json());
      entry.id = r.id;
      return r.id;
    },
    async snapshot(id, doc, note) {
      await postJSON('/documents/' + encodeURIComponent(id) + '/versions', { doc, note });
    },
    where: 'บนเซิร์ฟเวอร์',
  };
  // เลือกที่เก็บตามโหมดของเซิร์ฟเวอร์ (รู้หลังโหลด /config)
  const pick = async () => ((await auth.serverMode()) ? serverStore : localStore);
  const store = {
    list: async () => (await pick()).list(),
    get: async (id) => (await pick()).get(id),
    save: async (entry) => (await pick()).save(entry),
    create: async (entry) => (await pick()).create(entry),
    snapshot: async (id, doc, note) => (await pick()).snapshot(id, doc, note),
    where: async () => (await pick()).where,
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

  window.GovDoc = { api, store, auth, toThai, esc, PH_RE, hasPlaceholder, relTime, download, toast, DOC_TYPE_LABEL, URGENCY, SECRET };
})();
