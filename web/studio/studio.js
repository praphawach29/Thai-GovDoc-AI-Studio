// studio.js — ส่วนกลางของหน้าเว็บ Thai GovDoc AI Studio: เรียก API, เก็บร่าง, ตัวช่วยข้อความไทย
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

  // เบราว์เซอร์ส่งไฟล์ตรงเข้า Supabase Storage ด้วย URL ที่เซ็นแล้ว (ไฟล์ไม่ผ่าน Vercel)
  async function putToStorage(uploadUrl, file, failMessage) {
    const body = new FormData();
    body.append('cacheControl', '3600');
    body.append('', file);
    // ส่ง apikey (publishable key ซึ่งเปิดเผยได้) แบบเดียวกับ supabase-js; สิทธิ์อัปโหลดมาจาก token ใน URL
    const { supabase_publishable_key: apikey } = await auth.config();
    const res = await fetch(uploadUrl, { method: 'PUT', body, headers: { 'x-upsert': 'false', apikey } });
    if (!res.ok) throw new Error(failMessage);
  }

  const api = {
    profile: () => request('/studio/profile').then(r => r.json()),
    saveProfile: (fields) => sendJSON('PUT', '/org-profile', fields).then(r => r.json()),
    draft: (formData) => request('/studio/draft', { method: 'POST', body: formData }).then(r => r.json()),
    blank: (docType, unitKey) => postJSON('/studio/blank', { doc_type: docType, unit_key: unitKey || null }).then(r => r.json()),
    units: () => request('/studio/units').then(r => r.json()),
    applyUnit: (doc, unitKey) => postJSON('/studio/apply-unit', { doc, unit_key: unitKey }).then(r => r.json()),
    check: (doc) => postJSON('/studio/check', doc).then(r => r.json()),
    refine: (text, command) => postJSON('/copilot/refine', { text, command }).then(r => r.json()),
    exportDocx: (doc) => postJSON('/export/docx', doc).then(r => r.blob()),
    // ไฟล์ Word เป็นแม่แบบ: AI เสนอข้อความใหม่รายย่อหน้า → ผู้ใช้ตรวจ → สร้างไฟล์ที่คงรูปแบบเดิม
    wordTemplate: {
      propose: (fd) => request('/studio/word-template/propose', { method: 'POST', body: fd }).then(r => r.json()),
      build: (fd) => request('/studio/word-template/build', { method: 'POST', body: fd })
        .then(async (r) => { const blob = await r.blob(); blob.changed = Number(r.headers.get('X-GovDoc-Changed') || 0); return blob; }),
    },
    // PDF: เซิร์ฟเวอร์บอกจำนวนหน้าข้อกฎหมายที่แนบท้ายใน header (แจ้งผู้ใช้ได้)
    exportPdf: (doc) => postJSON('/export/pdf', doc).then(async (r) => {
      const blob = await r.blob();
      blob.legalPages = Number(r.headers.get('X-GovDoc-Legal-Pages') || 0);
      return blob;
    }),
    exportPdfBundle: (documents) => postJSON('/export/pdf-bundle', { documents }).then(r => r.blob()),
    templates: () => request('/studio/templates').then(r => r.json()),
    template: (id) => request('/studio/templates/' + encodeURIComponent(id)).then(r => r.json()),
    legal: () => request('/legal/references').then(r => r.json()),
    legalEdit: (id, fields) => sendJSON('PATCH', '/legal/references/' + encodeURIComponent(id), fields).then(r => r.json()),
    legalSuggest: (text) => postJSON('/legal/suggest', { text }).then(r => r.json()),
    // คลังกฎหมาย: นำเข้าไฟล์สแกน → AI อ่านทีละหน้า → แยกเป็นข้อ → ยืนยัน (โหมดเซิร์ฟเวอร์)
    legalImport: {
      async upload(file) {
        const { path, upload_url } = await postJSON('/legal/sources/upload-url', { filename: file.name, size_bytes: file.size }).then(r => r.json());
        await putToStorage(upload_url, file, 'อัปโหลดไฟล์กฎหมายไม่สำเร็จ');
        return postJSON('/legal/sources', { path, filename: file.name }).then(r => r.json());
      },
      ocrPage(blob, page) {
        const fd = new FormData();
        fd.append('image', blob, 'page-' + page + '.jpg');
        fd.append('page', String(page));
        return request('/legal/ocr-page', { method: 'POST', body: fd }).then(r => r.json());
      },
      sections: (sourceId, pageTexts, title) => postJSON('/legal/sources/' + encodeURIComponent(sourceId) + '/sections', { page_texts: pageTexts, title: title || '' }).then(r => r.json()),
      sources: () => request('/legal/sources').then(r => r.json()),
      fileUrl: (sourceId) => request('/legal/sources/' + encodeURIComponent(sourceId) + '/file-url').then(r => r.json()).then(r => r.url),
      addSection: (sourceId, fields) => postJSON('/legal/sources/' + encodeURIComponent(sourceId) + '/references', fields).then(r => r.json()),
      rename: (sourceId, title) => sendJSON('PATCH', '/legal/sources/' + encodeURIComponent(sourceId), { title }).then(r => r.json()),
      verify: (ids, verified = true) => sendJSON('PATCH', '/legal/references/verify', { ids, verified }).then(r => r.json()),
    },
    // คลังตัวอย่างของหน่วย (หนังสือฉบับจริง → สำนวนให้ AI) — โหมดเซิร์ฟเวอร์
    examples: {
      list: (documentId) => request('/examples' + (documentId ? '?document_id=' + encodeURIComponent(documentId) : '')).then(r => r.json()),
      // อัปโหลด + ลงทะเบียน → แถวตัวอย่าง หรือ { needs_ocr, page_count, path } (PDF สแกน: อ่านทีละหน้าแล้วเรียก register)
      async upload(file) {
        const { path, upload_url } = await postJSON('/examples/upload-url', { filename: file.name, size_bytes: file.size }).then(r => r.json());
        await putToStorage(upload_url, file, 'อัปโหลดไฟล์ตัวอย่างไม่สำเร็จ');
        return postJSON('/examples', { path, filename: file.name }).then(r => r.json());
      },
      register: (path, filename, pageTexts) => postJSON('/examples', { path, filename, page_texts: pageTexts }).then(r => r.json()),
      ocrPage(blob, page) {
        const fd = new FormData();
        fd.append('image', blob, 'page-' + page + '.jpg');
        fd.append('page', String(page));
        return request('/examples/ocr-page', { method: 'POST', body: fd }).then(r => r.json());
      },
      fromDocument: (documentId) => postJSON('/examples/from-document', { document_id: documentId }).then(r => r.json()),
      fileUrl: (id) => request('/examples/' + encodeURIComponent(id) + '/file-url').then(r => r.json()).then(r => r.url),
      remove: (id) => request('/examples/' + encodeURIComponent(id), { method: 'DELETE' }).then(r => r.json()),
    },
    // รายชื่อผู้ลงนามประจำหน่วยงาน (ใช้ร่วมกันทั้งหน่วยงาน)
    signers: {
      list: () => request('/signers').then(r => r.json()),
      create: (fields) => postJSON('/signers', fields).then(r => r.json()),
      update: (id, fields) => sendJSON('PATCH', '/signers/' + encodeURIComponent(id), fields).then(r => r.json()),
      remove: (id) => request('/signers/' + encodeURIComponent(id), { method: 'DELETE' }).then(r => r.json()),
    },
    // ผู้ใช้ของหน่วยงาน (เฉพาะผู้ดูแล): เชิญด้วยอีเมล / ยกเลิกคำเชิญ / เปลี่ยนบทบาท-ระงับ
    users: {
      list: () => request('/users').then(r => r.json()),
      invite: (fields) => postJSON('/users/invites', fields).then(r => r.json()),
      revoke: (id) => request('/users/invites/' + encodeURIComponent(id), { method: 'DELETE' }).then(r => r.json()),
      setRole: (userId, role) => sendJSON('PATCH', '/users/' + encodeURIComponent(userId), { role }).then(r => r.json()),
    },
    // แจ้งปัญหา / ความเห็น (โหมดเซิร์ฟเวอร์): ผู้ดูแลเห็นทั้งหน่วยงาน คนอื่นเห็นของตัวเอง
    feedback: {
      send: (fields) => postJSON('/feedback', fields).then(r => r.json()),
      list: (status) => request('/feedback' + (status ? '?status=' + encodeURIComponent(status) : '')).then(r => r.json()),
      setStatus: (id, status) => sendJSON('PATCH', '/feedback/' + encodeURIComponent(id), { status }).then(r => r.json()),
    },
    health: () => fetch(API + '/health').then(r => r.ok),
    me: () => request('/me').then(r => r.json()),
    // โหมดเซิร์ฟเวอร์: อัปโหลดไฟล์ต้นเรื่องตรงเข้า Supabase Storage (ไม่ผ่าน API ซึ่งรับไฟล์ใหญ่ไม่ได้)
    async uploadSource(file) {
      const { path, upload_url } = await postJSON('/sources/upload-url', { filename: file.name, size_bytes: file.size }).then(r => r.json());
      await putToStorage(upload_url, file, 'อัปโหลดไฟล์ต้นเรื่องไม่สำเร็จ');
      return path;
    },
    // ไฟล์ต้นเรื่องจริงสำหรับแสดงฝั่งซ้ายของหน้าแก้ไข → { url, filename, kind: pdf|image|text }
    factCheck: (doc, sourceText) => postJSON('/studio/fact-check', { doc, source_text: sourceText }).then(r => r.json()),
    sourceViewUrl: (sourceFileId) => request(`/sources/${encodeURIComponent(sourceFileId)}/view-url`).then(r => r.json()),
    // ฉบับจริง: ไฟล์ Word/PDF ที่แก้เสร็จแล้ว (โหมดเซิร์ฟเวอร์เท่านั้น)
    finals: {
      list: (docId) => request(`/documents/${encodeURIComponent(docId)}/finals`).then(r => r.json()),
      async upload(docId, file, note) {
        const base = `/documents/${encodeURIComponent(docId)}/finals`;
        const { path, upload_url } = await postJSON(base + '/upload-url', { filename: file.name, size_bytes: file.size }).then(r => r.json());
        await putToStorage(upload_url, file, 'อัปโหลดไฟล์ฉบับจริงไม่สำเร็จ');
        return postJSON(base, { path, filename: file.name, note: note || null }).then(r => r.json());
      },
      downloadUrl: (docId, fileId) => request(`/documents/${encodeURIComponent(docId)}/finals/${encodeURIComponent(fileId)}/download`)
        .then(r => r.json()).then(r => r.url),
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
  // ค่าสรุปสำหรับรายการงาน (เหมือนที่ API ส่งในโหมดเซิร์ฟเวอร์)
  const summarize = (x) => ({
    ...x, docType: formKey(x.doc), editStatus: x.doc?.edit_status,
    todo: (x.check?.placeholders?.length || 0) + (x.check?.lint?.issues?.length || 0) + (x.check?.facts?.length || 0),
  });
  const localStore = {
    async list({ archived = false } = {}) {
      return readAll().filter(x => !!x.archived === archived).map(summarize)
        .sort((a, b) => (b.updated || '').localeCompare(a.updated || ''));
    },
    async setArchived(id, on) {
      const entry = readAll().find(x => x.id === id);
      if (!entry) throw new Error('ไม่พบเอกสาร');
      entry.archived = on;
      if (!(await localStore.save(entry))) throw new Error('พื้นที่เก็บในเบราว์เซอร์เต็ม');
    },
    async purge(id) {
      const list = readAll();
      if (!list.some(x => x.id === id && x.archived)) throw new Error('ต้องอยู่ในถังขยะก่อนจึงลบถาวรได้');
      writeAll(list.filter(x => x.id !== id));
    },
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
    async list({ archived = false } = {}) {
      const rows = await request('/documents?limit=50' + (archived ? '&archived=true' : '')).then(r => r.json());
      return rows.map(r => ({
        id: r.id, title: r.subject, updated: r.updated_at, doc: { urgency: r.urgency }, docNumber: r.doc_number, status: r.status,
        docType: DOC_TYPE_LABEL[r.kind] ? r.kind : r.doc_type, unitKey: r.unit_key, todo: r.todo || 0, editStatus: r.edit_status, sourceName: r.source_name,
      }));
    },
    async setArchived(id, on) {
      await sendJSON('PATCH', '/documents/' + encodeURIComponent(id) + '/status', { status: on ? 'archived' : 'draft' });
    },
    // ลบถาวร: เอกสาร + ประวัติเวอร์ชัน + ไฟล์ต้นเรื่อง (เฉพาะร่างในถังขยะ)
    async purge(id) {
      return request('/documents/' + encodeURIComponent(id), { method: 'DELETE' }).then(r => r.json());
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
    list: async (opts) => (await pick()).list(opts),
    setArchived: async (id, on) => (await pick()).setArchived(id, on),
    purge: async (id) => (await pick()).purge(id),
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

  // ประเภทหนังสือ: คีย์เดียวกับ core.models.FORM_KEYS (doc_type ของ API) — ชนิดอื่นแยกด้วย doc.kind
  const DOC_TYPE_LABEL = { internal: 'บันทึกข้อความ', external: 'หนังสือภายนอก', stamp_letter: 'หนังสือประทับตรา', order: 'คำสั่ง', announcement: 'ประกาศ', regulation: 'ระเบียบ', bylaw: 'ข้อบังคับ', project: 'โครงการ' };
  const formKey = (doc) => (doc && DOC_TYPE_LABEL[doc.kind] ? doc.kind : (doc?.doc_type === 'internal' ? 'internal' : 'external'));
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

  // ---------- แจ้งปัญหา: กล่องเดียวใช้ทั้งหน้าแรกและหน้าแก้ไข ----------
  // ระบบแนบร่างที่เปิดอยู่ เวลา และข้อมูลประกอบให้เอง — ผู้ทดสอบเลือกระดับ หมวด แล้วเล่าสั้น ๆ
  const FEEDBACK_RATING = [
    ['ok', 'ใช้ได้เลย', 'fa-circle-check', 'text-emerald-700'],
    ['minor', 'แก้นิดหน่อย', 'fa-pen', 'text-amber-700'],
    ['major', 'แก้เยอะ', 'fa-triangle-exclamation', 'text-orange-700'],
    ['broken', 'ใช้ไม่ได้ / ผิดพลาด', 'fa-circle-xmark', 'text-rose-700'],
    ['idea', 'ข้อเสนอแนะ', 'fa-lightbulb', 'text-sky-700'],
  ];
  const FEEDBACK_CATEGORY = { content: 'เนื้อหาที่ AI ร่าง', layout: 'รูปแบบหน้ากระดาษ', export: 'ส่งออก Word / PDF', source: 'อ่านไฟล์ต้นเรื่อง',
    speed: 'ช้า / ค้าง', ui: 'ใช้งานหน้าเว็บ', other: 'อื่น ๆ' };
  function openFeedback({ documentId = null, page = '', context = {}, onSent = null } = {}) {
    let box = document.getElementById('feedback-modal');
    if (!box) {
      box = document.createElement('div');
      box.id = 'feedback-modal';
      box.className = 'fixed inset-0 z-[90] flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm no-print';
      box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true'); box.setAttribute('aria-labelledby', 'fb-title');
      document.body.appendChild(box);
    }
    box.innerHTML = `
      <form id="fb-form" class="bg-white w-full max-w-md rounded-2xl shadow-2xl border border-slate-200 flex flex-col max-h-[90vh] overflow-hidden animate-fadeIn text-xs" novalidate>
        <div class="px-5 py-3.5 border-b border-slate-100 flex items-center justify-between bg-slate-50/60">
          <h3 id="fb-title" class="text-sm font-semibold text-slate-900"><i class="fa-solid fa-flag text-rose-600 mr-1"></i>แจ้งปัญหา / ความเห็น</h3>
          <button type="button" data-fb-close class="w-8 h-8 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200/60" aria-label="ปิด"><i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="flex-1 overflow-y-auto p-5 space-y-3.5">
          <fieldset>
            <legend class="text-slate-600 mb-1.5">${documentId ? 'ร่างฉบับนี้เป็นอย่างไร' : 'เรื่องที่จะแจ้ง'}</legend>
            <div class="grid grid-cols-2 gap-1.5">${FEEDBACK_RATING.map(([k, label, icon, color]) => `
              <label class="flex items-center gap-2 px-2.5 py-2 rounded-lg border border-slate-200 hover:bg-slate-50 cursor-pointer" data-fb-choice>
                <input type="radio" name="fb-rating" value="${k}" class="sr-only">
                <i class="fa-solid ${icon} ${color}"></i><span class="text-slate-800">${label}</span></label>`).join('')}
            </div>
          </fieldset>
          <label class="block"><span class="text-slate-600">หมวด</span>
            <select id="fb-category" class="mt-1 block w-full border border-slate-300 rounded-lg bg-white py-1.5 pl-2.5 pr-8 text-sm focus:ring-0">
              ${Object.entries(FEEDBACK_CATEGORY).map(([k, v]) => `<option value="${k}" ${k === (documentId ? 'content' : 'other') ? 'selected' : ''}>${v}</option>`).join('')}
            </select></label>
          <label class="block"><span class="text-slate-600">เล่าสั้น ๆ ว่าเจออะไร / อยากให้เป็นอย่างไร</span>
            <textarea id="fb-message" rows="4" maxlength="4000" class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm font-body focus:outline-none focus:ring-1 focus:ring-emerald-500"
              placeholder="เช่น ภาคความประสงค์อ้างข้อ ๒ แต่ข้อพิจารณามีแค่ข้อ ๑"></textarea></label>
          <p class="text-slate-500 leading-relaxed"><i class="fa-solid fa-paperclip mr-1"></i>ระบบแนบ${documentId ? 'ร่างฉบับนี้ ' : ''}เวลา และขั้นตอนที่ระบบทำให้อัตโนมัติ — ไม่ต้องจดเอง · อย่าใส่ข้อมูลส่วนบุคคลหรือเนื้อหาชั้นลับ</p>
          <p id="fb-error" class="text-rose-700" hidden></p>
        </div>
        <div class="px-5 py-3 border-t border-slate-100 flex justify-end gap-2 bg-slate-50/60">
          <button type="button" data-fb-close class="px-3 py-1.5 rounded-lg text-slate-600 hover:bg-slate-200/60">ยกเลิก</button>
          <button type="submit" id="fb-send" class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-brand-700 disabled:bg-slate-300 text-white font-medium"><i class="fa-solid fa-paper-plane"></i><span>ส่ง</span></button>
        </div>
      </form>`;
    box.hidden = false;
    const close = () => { box.hidden = true; document.removeEventListener('keydown', onKey); };
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', onKey);
    box.onclick = (e) => { if (e.target === box || e.target.closest('[data-fb-close]')) close(); };
    box.onchange = (e) => {
      if (e.target.name !== 'fb-rating') return;
      box.querySelectorAll('[data-fb-choice]').forEach((l) => {
        const on = l.contains(e.target);
        l.classList.toggle('border-slate-800', on); l.classList.toggle('bg-slate-100', on); l.classList.toggle('border-slate-200', !on);
      });
      if (e.target.value === 'ok' && !box.querySelector('#fb-message').value) box.querySelector('#fb-category').value = 'content';
      if (e.target.value === 'idea') box.querySelector('#fb-category').value = 'other';
    };
    const err = box.querySelector('#fb-error');
    box.querySelector('#fb-form').onsubmit = async (e) => {
      e.preventDefault();
      const rating = box.querySelector('input[name="fb-rating"]:checked')?.value;
      const message = box.querySelector('#fb-message').value.trim();
      if (!rating) { err.textContent = 'เลือกก่อนว่าเป็นแบบไหน'; err.hidden = false; return; }
      if (rating !== 'ok' && !message) { err.textContent = 'เล่าสั้น ๆ ก่อนส่ง'; err.hidden = false; box.querySelector('#fb-message').focus(); return; }
      err.hidden = true;
      const send = box.querySelector('#fb-send');
      send.disabled = true;
      try {
        await api.feedback.send({
          rating, category: box.querySelector('#fb-category').value, message, document_id: documentId, page,
          context: { ...context, url: location.pathname + location.search, viewport: `${innerWidth}x${innerHeight}`,
            user_agent: navigator.userAgent, sent_at: new Date().toISOString() },
        });
        close();
        toast('ส่งแล้ว ขอบคุณครับ');
        if (onSent) onSent();
      } catch (ex) { err.textContent = ex.message; err.hidden = false; }
      finally { send.disabled = false; }
    };
    setTimeout(() => box.querySelector('input[name="fb-rating"]')?.focus(), 0);
  }

  window.GovDoc = { api, store, auth, toThai, esc, PH_RE, hasPlaceholder, relTime, download, toast, DOC_TYPE_LABEL, formKey, URGENCY, SECRET,
    openFeedback, FEEDBACK_RATING, FEEDBACK_CATEGORY };
})();
