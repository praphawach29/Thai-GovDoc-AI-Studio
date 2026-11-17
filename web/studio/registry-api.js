// registry-api.js — เรียก API ทะเบียนรับ-ส่ง (โหลดหลัง auth.js) ใช้ทั้งหน้าแก้ไขและหน้าทะเบียน
// เลขที่หนังสือออกจากฐานข้อมูลเสมอ — ไฟล์นี้ไม่คำนวณเลขเอง
(function () {
  const API = '/api/v1/registry';
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
      const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
      err.status = res.status;
      throw err;
    }
    return res;
  }
  const json = (path) => request(path).then(r => r.json());
  const post = (path, body) => request(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
  }).then(r => r.json());
  const qs = (params) => {
    const p = new URLSearchParams();
    Object.entries(params || {}).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') p.set(k, v); });
    const s = p.toString();
    return s ? '?' + s : '';
  };
  const enc = encodeURIComponent;

  window.GovDocRegistry = {
    // หน้าแก้ไข
    forDocument: (docId) => json(`/documents/${enc(docId)}`),
    issueForDocument: (docId, body) => post(`/documents/${enc(docId)}/issue`, body),
    cancel: (entryId, reason) => post(`/outgoing/${enc(entryId)}/cancel`, { reason }),
    incomingBySource: (sourceFileId) => json(`/incoming/by-source/${enc(sourceFileId)}`),
    receive: (body) => post('/incoming', body),
    // หน้าทะเบียน
    years: () => json('/years'),
    outgoing: (params) => json('/outgoing' + qs({ limit: 5000, ...params })),
    incoming: (params) => json('/incoming' + qs({ limit: 5000, ...params })),
    reserve: (body) => post('/reserve', body),
    audit: (entity, entityId) => json('/audit' + qs({ entity, entity_id: entityId })),
    async exportFile(kind, format, params) {
      const res = await request(`/${enc(kind)}/export` + qs({ format, ...params }));
      const cd = res.headers.get('content-disposition') || '';
      const m = cd.match(/filename\*=UTF-8''([^;]+)/);
      return { blob: await res.blob(), filename: m ? decodeURIComponent(m[1]) : `${kind}.${format}`,
               rows: Number(res.headers.get('x-govdoc-rows') || 0) };
    },
  };
})();
