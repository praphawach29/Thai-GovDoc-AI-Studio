// editor.js — หน้าแก้ไขเอกสาร: กระดาษ A4 แก้ไขได้โดยตรง + บทสนทนา/ต้นเรื่อง/ผลตรวจ + ส่งออก
(async function () {
  const { api, store, esc, toThai, PH_RE, hasPlaceholder, relTime, download, toast, URGENCY, SECRET, DOC_TYPE_LABEL } = window.GovDoc;
  const $ = (id) => document.getElementById(id);

  await window.GovDoc.auth.ready;
  const id = new URLSearchParams(location.search).get('id');
  const entry = id && await store.get(id);
  if (!entry) {
    document.body.innerHTML = `<div class="m-auto text-center p-8"><p class="text-slate-700 mb-3">ไม่พบเอกสารนี้ หรือไม่มีสิทธิ์เปิด</p><a href="./" class="text-emerald-700 underline">กลับหน้าแรก</a></div>`;
    return;
  }
  const storeWhere = await store.where();
  // เก็บจุดบันทึก (เวอร์ชัน) บนเซิร์ฟเวอร์ — โหมดเครื่องเดียวไม่ทำอะไร
  const snapshot = (note) => store.snapshot(entry.id, st.doc, note)
    .catch(err => toast('เก็บเวอร์ชันบนเซิร์ฟเวอร์ไม่สำเร็จ: ' + err.message, 'warn'));

  const st = {
    doc: entry.doc,
    check: entry.check || null,
    versions: entry.versions || [],
    editOn: true,
    undo: [], redo: [],
    stash: {},          // ค่าหัวข้อเสริมที่ปิดไว้ (เปิดกลับมาจะได้ค่าเดิม)
    savedAt: entry.updated,
    refine: null,
  };
  const isMemo = () => st.doc.doc_type === 'internal';
  const num = (s) => st.doc.use_thai_numerals ? toThai(s) : String(s ?? '');

  // ---------- บันทึก ----------
  let saveTimer = null, checkTimer = null;
  // บันทึกทีละครั้ง: ถ้ามีการแก้ระหว่างกำลังบันทึก จะบันทึกซ้ำอีกรอบหลังเสร็จ (เครือข่ายช้าก็ไม่ทับกัน)
  let saving = false, savePending = false;
  async function persist() {
    if (saving) { savePending = true; return; }
    saving = true;
    entry.doc = st.doc; entry.check = st.check; entry.versions = st.versions.slice(-20);
    entry.title = st.doc.subject;
    let ok = false;
    try { ok = await store.save(entry); } catch (err) { st.saveError = err.message; }
    if (ok) st.savedAt = entry.updated;
    saving = false;
    renderSaveState(ok ? 'saved' : 'error');
    if (savePending) { savePending = false; persist(); }
  }
  function scheduleSave() {
    renderSaveState('saving');
    clearTimeout(saveTimer); saveTimer = setTimeout(persist, 500);
    clearTimeout(checkTimer); checkTimer = setTimeout(runCheck, 900);
  }
  function renderSaveState(state) {
    const el = $('save-indicator');
    el.innerHTML = state === 'saving' ? '<i class="fa-solid fa-circle-notch fa-spin text-slate-400"></i><span>กำลังบันทึก...</span>'
      : state === 'error' ? `<i class="fa-solid fa-triangle-exclamation text-rose-600"></i><span>บันทึกไม่สำเร็จ${st.saveError ? ' — ' + esc(st.saveError) : ' (พื้นที่เต็ม)'}</span>`
      : `<i class="fa-solid fa-check text-emerald-600"></i><span>บันทึกอัตโนมัติ${storeWhere}แล้ว</span>`;
    $('footer-saved').textContent = st.savedAt ? 'บันทึกล่าสุด' + relTime(st.savedAt) : '';
  }

  // ---------- เปลี่ยนค่า + undo ----------
  function commit(mutator, { rerender = true } = {}) {
    st.undo.push(JSON.stringify(st.doc));
    if (st.undo.length > 100) st.undo.shift();
    st.redo = [];
    mutator(st.doc);
    st.doc.edit_status = 'editing';
    st.doc.last_edited_at = new Date().toISOString();
    if (rerender) renderAll(); else renderChrome();
    scheduleSave();
  }
  function undoRedo(from, to) {
    if (!from.length) return;
    to.push(JSON.stringify(st.doc));
    st.doc = JSON.parse(from.pop());
    renderAll(); scheduleSave();
  }
  $('btn-undo').addEventListener('click', () => undoRedo(st.undo, st.redo));
  $('btn-redo').addEventListener('click', () => undoRedo(st.redo, st.undo));
  document.addEventListener('keydown', (e) => {
    const inField = e.target.closest?.('[contenteditable="true"], textarea, input');
    if (inField || !(e.ctrlKey || e.metaKey)) return;
    if (e.key === 'z') { e.preventDefault(); undoRedo(st.undo, st.redo); }
    if (e.key === 'y') { e.preventDefault(); undoRedo(st.redo, st.undo); }
  });

  // ---------- ช่องแก้ไขบนกระดาษ ----------
  // ค่าของแต่ละช่อง: getter/setter ผูกกับฟิลด์ใน GovDocumentSchema
  const SAL_RE = /^(กราบเรียน|เรียน)\s*/;
  const FIELDS = {
    doc_number: { get: d => d.doc_number, set: (d, v) => { d.doc_number = v; } },
    doc_date: { get: d => d.doc_date, set: (d, v) => { d.doc_date = v.replace(/^วันที่\s*/, ''); } },
    dept_name: { get: d => d.dept_name, set: (d, v) => { d.dept_name = v; } },
    subject: { get: d => d.subject, set: (d, v) => { d.subject = v.replace(/\s*\n\s*/g, ' '); } },
    salutation_to: {
      get: d => (d.salutation || '').replace(SAL_RE, ''),
      set: (d, v) => { const pre = (d.salutation || '').match(SAL_RE)?.[1] || 'เรียน'; d.salutation = `${pre}  ${v.trim()}`; },
    },
    references: { get: d => (d.references || []).join('\n'), set: (d, v) => { d.references = v.split('\n').map(s => s.trim()).filter(Boolean); } },
    attachments: { get: d => (d.attachments || []).join('\n'), set: (d, v) => { d.attachments = v.split('\n').map(s => s.trim()).filter(Boolean); } },
    paragraph_reason: { get: d => d.paragraph_reason, set: (d, v) => { d.paragraph_reason = v; } },
    paragraph_details: { get: d => d.paragraph_details || '', set: (d, v) => { d.paragraph_details = v || null; } },
    paragraph_purpose: { get: d => d.paragraph_purpose, set: (d, v) => { d.paragraph_purpose = v; } },
    memo_intro: { get: d => d.memo_intro || '', set: (d, v) => { d.memo_intro = v; d.paragraph_reason = v; } },
    memo_law: { get: d => d.memo_law || '', set: (d, v) => { d.memo_law = v || null; } },
    memo_facts: { get: d => d.memo_facts || '', set: (d, v) => { d.memo_facts = v; d.paragraph_details = v || null; } },
    memo_consideration: { get: d => d.memo_consideration || '', set: (d, v) => { d.memo_consideration = v; d.paragraph_purpose = [v, d.memo_request].filter(Boolean).join('\n\n'); } },
    memo_request: { get: d => d.memo_request || '', set: (d, v) => { d.memo_request = v; d.paragraph_purpose = [d.memo_consideration, v].filter(Boolean).join('\n\n'); } },
    closing: { get: d => d.closing, set: (d, v) => { d.closing = v; } },
    signatory_name: { get: d => d.signatory_name, set: (d, v) => { d.signatory_name = v; } },
    signatory_position: { get: d => d.signatory_position, set: (d, v) => { d.signatory_position = v; } },
    contact_dept: { get: d => d.contact_dept, set: (d, v) => { d.contact_dept = v; } },
    contact_tel: { get: d => d.contact_tel || '', set: (d, v) => { d.contact_tel = v || null; } },
    contact_fax: { get: d => d.contact_fax || '', set: (d, v) => { d.contact_fax = v || null; } },
    contact_email: { get: d => d.contact_email || '', set: (d, v) => { d.contact_email = v || null; } },
  };
  // ผู้ลงนามเพิ่มเติมของบันทึกข้อความ (เช่น หัวหน้ากลุ่มงานลงนามต่อจากผู้เสนอ) — สูงสุด 3 คน
  for (let i = 0; i < 3; i++) {
    for (const [suffix, prop] of [['name', 'name'], ['pos', 'position']]) {
      FIELDS[`co_${suffix}_${i}`] = {
        get: d => d.co_signers?.[i]?.[prop] || '',
        set: (d, v) => { if (d.co_signers?.[i]) d.co_signers[i][prop] = v; },
      };
    }
  }
  const FIELD_LABEL = {
    doc_number: 'ที่', doc_date: 'วันที่', dept_name: 'ส่วนราชการ', subject: 'เรื่อง', salutation_to: 'เรียน',
    references: 'อ้างถึง', attachments: 'สิ่งที่ส่งมาด้วย', paragraph_reason: 'ภาคเหตุ', paragraph_details: 'ภาคข้อเท็จจริง',
    paragraph_purpose: 'ภาคความประสงค์', memo_intro: 'ต้นเรื่อง', memo_law: 'ข้อกฎหมาย', memo_facts: 'ข้อเท็จจริง',
    memo_consideration: 'ข้อพิจารณาและเสนอแนะ', memo_request: 'ภาคความประสงค์', closing: 'คำลงท้าย',
    signatory_name: 'ชื่อผู้ลงนาม', signatory_position: 'ตำแหน่ง', contact_dept: 'ส่วนราชการเจ้าของเรื่อง',
    contact_tel: 'โทร.', contact_fax: 'โทรสาร', contact_email: 'อีเมล',
    co_name_0: 'ชื่อผู้ลงนามถัดไป', co_pos_0: 'ตำแหน่งผู้ลงนามถัดไป', co_name_1: 'ชื่อผู้ลงนามถัดไป', co_pos_1: 'ตำแหน่งผู้ลงนามถัดไป',
    co_name_2: 'ชื่อผู้ลงนามถัดไป', co_pos_2: 'ตำแหน่งผู้ลงนามถัดไป',
  };
  const REFINABLE = new Set(['paragraph_reason', 'paragraph_details', 'paragraph_purpose', 'memo_intro', 'memo_facts', 'memo_consideration', 'memo_request', 'subject']);

  // แสดงข้อความ: แปลงเลขไทย + เน้น placeholder เป็นชิป
  function displayHTML(text) {
    const s = num(text);
    let out = '', last = 0;
    PH_RE.lastIndex = 0;
    for (const m of s.matchAll(PH_RE)) {
      out += esc(s.slice(last, m.index)) + `<span class="ph-chip" contenteditable="false">${esc(m[0])}</span>`;
      last = m.index + m[0].length;
    }
    return out + esc(s.slice(last));
  }
  const field = (key, cls = '', empty = '') =>
    `<span class="editable ${cls}" data-field="${key}" data-empty="${esc(empty || '[คลิกเพื่อพิมพ์ ' + (FIELD_LABEL[key] || '') + ']')}"></span>`;
  const block = (key, cls = '') =>
    `<div class="group relative">${field(key, 'block ' + cls)}${REFINABLE.has(key) ? refineBtn(key) : ''}</div>`;
  const refineBtn = (key) => `<button type="button" data-refine="${key}" class="no-print absolute -right-[1.7cm] top-0 w-7 h-7 rounded-full bg-white border border-emerald-200 text-emerald-600 shadow-xs opacity-0 group-hover:opacity-100 focus:opacity-100 hover:bg-emerald-50 transition font-sans text-xs" title="เกลาสำนวน ${FIELD_LABEL[key]}"><i class="fa-solid fa-wand-magic-sparkles"></i></button>`;
  const labelRow = (label, key, extra = '') =>
    `<div class="flex items-baseline gap-2 ${extra}"><span class="doc-bold shrink-0">${label}</span>${field(key, 'flex-1 dotted-fill')}</div>`;

  function stamps() {
    const out = [];
    // ชั้นความลับ: กลางหน้าทั้งบนและล่าง / ชั้นความเร็ว: แดง 32 pt (ตรงกับไฟล์ที่ส่งออก)
    if (st.doc.secret !== 'normal') {
      const label = SECRET[st.doc.secret].label;
      out.push(`<div class="absolute top-[0.9cm] left-0 right-0 text-center text-red-600 font-bold" style="font-size:20pt">${label}</div>`);
      out.push(`<div class="absolute bottom-[0.6cm] left-0 right-0 text-center text-red-600 font-bold" style="font-size:20pt">${label}</div>`);
    }
    if (st.doc.urgency !== 'normal') out.push(`<div class="absolute top-[1.3cm] left-[3cm] text-red-600 font-bold leading-tight" style="font-size:32pt">${URGENCY[st.doc.urgency].label}</div>`);
    return out.join('');
  }
  function signature() {
    return `<div class="mt-[1.2cm] ml-auto w-[9cm] text-center space-y-0.5">
      ${isMemo() ? '' : `<div>${field('closing')}</div><div class="h-[1.6cm]"></div>`}
      <div>${field('signatory_name')}</div>
      <div>${field('signatory_position')}</div>
      ${isMemo() ? (st.doc.co_signers || []).slice(0, 3).map((_, i) =>
        `<div class="h-[1.2cm]"></div><div>${field('co_name_' + i)}</div><div>${field('co_pos_' + i)}</div>`).join('') : ''}
    </div>`;
  }

  function sheetHTML() {
    const d = st.doc;
    const refs = d.references != null, atts = d.attachments != null;
    if (isMemo()) {
      const law = d.memo_law != null;
      let secNo = 0;
      const sec = (key, title) => `
        <div class="${secNo++ ? 'gap-6pt' : ''}">
          <div><span class="doc-bold underline underline-offset-4">${title}</span></div>
          ${block(key, 'indent-25 justify-thai')}
        </div>`;
      return `${stamps()}
        <div class="relative flex items-end h-[1.5cm] mb-2">
          <img src="/assets/garuda.svg" alt="ตราครุฑ" class="garuda-int absolute left-0 bottom-0">
          <div class="memo-title w-full text-center">บันทึกข้อความ</div>
        </div>
        <div class="space-y-1">
          <div class="flex items-baseline gap-2"><span class="doc-bold shrink-0">ส่วนราชการ</span>${field('dept_name', 'flex-1 dotted-fill one-line min-w-0 overflow-hidden whitespace-nowrap')}</div>
          <div class="flex items-baseline gap-4">
            <div class="flex items-baseline gap-2 flex-1 min-w-0"><span class="doc-bold">ที่</span>${field('doc_number', 'flex-1 dotted-fill')}</div>
            <div class="flex items-baseline gap-2 flex-1 min-w-0"><span class="doc-bold">วันที่</span>${field('doc_date', 'flex-1 dotted-fill')}</div>
          </div>
          <div class="flex items-baseline gap-2"><span class="doc-bold shrink-0">เรื่อง</span><div class="group relative flex-1">${field('subject', 'block dotted-fill')}</div></div>
        </div>
        <div class="gap-6pt flex items-baseline gap-2"><span class="doc-bold">${esc((d.salutation || '').match(SAL_RE)?.[1] || 'เรียน')}</span>${field('salutation_to', 'flex-1')}</div>
        ${refs ? `<div class="mt-1 flex items-baseline gap-2"><span class="doc-bold shrink-0">อ้างถึง</span>${field('references', 'flex-1')}</div>` : ''}
        ${atts ? `<div class="mt-1 flex items-baseline gap-2"><span class="doc-bold shrink-0">สิ่งที่ส่งมาด้วย</span>${field('attachments', 'flex-1')}</div>` : ''}
        <div>
          ${sec('memo_intro', 'ต้นเรื่อง')}
          ${law ? sec('memo_law', 'ข้อกฎหมาย') : ''}
          ${sec('memo_facts', 'ข้อเท็จจริง')}
          ${sec('memo_consideration', 'ข้อพิจารณาและเสนอแนะ')}
          <div class="gap-6pt">${block('memo_request', 'indent-25 justify-thai')}</div>
        </div>
        ${signature()}`;
    }
    return `${stamps()}
      <div class="flex justify-center mb-3"><img src="/assets/garuda.svg" alt="ตราครุฑ" class="garuda-ext"></div>
      <div class="flex items-start justify-between gap-6 -mt-[1.6cm]">
        <div class="flex items-baseline gap-2 w-[6.5cm]"><span class="doc-bold">ที่</span>${field('doc_number', 'flex-1')}</div>
        <div class="w-[6.5cm]">${field('dept_name', 'block')}</div>
      </div>
      <div class="mt-3 ml-[7.5cm]">${field('doc_date', 'block')}</div>
      <div class="mt-3 flex items-baseline gap-2"><span class="doc-bold shrink-0">เรื่อง</span><div class="flex-1">${field('subject', 'block')}</div></div>
      <div class="mt-1 flex items-baseline gap-2"><span class="doc-bold">${esc((d.salutation || '').match(SAL_RE)?.[1] || 'เรียน')}</span>${field('salutation_to', 'flex-1')}</div>
      ${refs ? `<div class="mt-1 flex items-baseline gap-2"><span class="doc-bold shrink-0">อ้างถึง</span>${field('references', 'flex-1')}</div>` : ''}
      ${atts ? `<div class="mt-1 flex items-baseline gap-2"><span class="doc-bold shrink-0">สิ่งที่ส่งมาด้วย</span>${field('attachments', 'flex-1')}</div>` : ''}
      <div class="mt-3 space-y-2">
        ${block('paragraph_reason', 'indent-25 justify-thai')}
        ${d.paragraph_details != null ? block('paragraph_details', 'indent-25 justify-thai') : ''}
        ${block('paragraph_purpose', 'indent-25 justify-thai')}
      </div>
      ${signature()}
      <div class="mt-[1.2cm] text-[15pt] leading-tight">
        <div>${field('contact_dept')}</div>
        <div class="flex gap-1"><span>โทร.</span>${field('contact_tel', 'flex-1')}</div>
        <div class="flex gap-1"><span>โทรสาร</span>${field('contact_fax', 'flex-1')}</div>
        <div class="flex gap-1"><span>ไปรษณีย์อิเล็กทรอนิกส์</span>${field('contact_email', 'flex-1')}</div>
      </div>`;
  }

  function fillFields() {
    $('sheet').querySelectorAll('[data-field]').forEach((el) => {
      if (el === document.activeElement) return;
      el.innerHTML = displayHTML(FIELDS[el.dataset.field].get(st.doc));
      el.contentEditable = st.editOn ? 'true' : 'false';
      el.spellcheck = false;
      el.setAttribute('role', 'textbox');
      el.setAttribute('aria-label', FIELD_LABEL[el.dataset.field] || el.dataset.field);
      if (el.classList.contains('block')) el.setAttribute('aria-multiline', 'true');
    });
    fitOneLine();
  }

  // "ส่วนราชการ" อยู่บรรทัดเดียวเสมอ: ยาวเกินให้บีบแนวนอนแบบเดียวกับไฟล์ PDF/Word
  function fitOneLine() {
    $('sheet').querySelectorAll('.one-line').forEach((el) => {
      el.style.whiteSpace = 'nowrap'; el.style.overflow = 'hidden'; el.style.minWidth = '0';
      el.style.transform = ''; el.style.width = ''; el.style.flex = '';
      const room = el.clientWidth, need = el.scrollWidth;
      if (need > room + 1) {
        el.style.flex = 'none';
        el.style.width = need + 'px';
        el.style.transformOrigin = 'left';
        el.style.transform = `scaleX(${room / need})`;
      }
    });
  }

  const sheet = $('sheet');
  sheet.addEventListener('focusin', (e) => {
    const el = e.target.closest('[data-field]');
    if (!el || !st.editOn) return;
    // ระหว่างพิมพ์ แสดงข้อความดิบ (ไม่มีชิป) เพื่อให้แก้ placeholder ได้ตรง ๆ
    el.textContent = FIELDS[el.dataset.field].get(st.doc);
    // ถ้าทั้งช่องเป็น placeholder ให้เลือกทั้งหมดเพื่อพิมพ์ทับได้ทันที
    if (hasPlaceholder(el.textContent)) {
      const m = el.textContent.match(PH_RE);
      const node = el.firstChild;
      if (node && m) {
        const start = el.textContent.indexOf(m[0]);
        const r = document.createRange(); r.setStart(node, start); r.setEnd(node, start + m[0].length);
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
      }
    }
  });
  sheet.addEventListener('focusout', (e) => {
    const el = e.target.closest('[data-field]');
    if (!el) return;
    const key = el.dataset.field;
    const value = el.innerText.replace(/ /g, ' ').replace(/\n{3,}/g, '\n\n').trimEnd();
    if (value !== FIELDS[key].get(st.doc)) {
      commit(d => FIELDS[key].set(d, value), { rerender: false });
    }
    el.innerHTML = displayHTML(FIELDS[key].get(st.doc));
    if (el.classList.contains('one-line')) fitOneLine();
  });
  sheet.addEventListener('keydown', (e) => {
    const el = e.target.closest('[data-field]');
    if (!el) return;
    if (e.key === 'Enter' && !el.classList.contains('block') && !['references', 'attachments'].includes(el.dataset.field)) { e.preventDefault(); el.blur(); }
    if (e.key === 'Escape') { el.blur(); }
  });
  // วางข้อความเป็น plain text เท่านั้น
  sheet.addEventListener('paste', (e) => {
    if (!e.target.closest('[data-field]')) return;
    e.preventDefault();
    document.execCommand('insertText', false, e.clipboardData.getData('text/plain'));
  });
  sheet.addEventListener('click', (e) => {
    const b = e.target.closest('[data-refine]');
    if (b) openRefine(b.dataset.refine, b);
  });

  // ---------- โหมดแก้ไข ----------
  function renderEditMode() {
    const b = $('btn-edit-mode');
    b.setAttribute('aria-pressed', String(st.editOn));
    b.className = 'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium transition ' +
      (st.editOn ? 'border-emerald-300 bg-emerald-50 text-emerald-800 hover:bg-emerald-100' : 'border-slate-300 bg-white text-slate-600 hover:bg-slate-50');
    b.innerHTML = st.editOn
      ? '<span class="relative flex h-2 w-2"><span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span><span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-600"></span></span><i class="fa-solid fa-pen"></i><span class="hidden md:inline">โหมดพิมพ์บนกระดาษ (เปิด)</span>'
      : '<i class="fa-regular fa-eye"></i><span class="hidden md:inline">โหมดอ่านอย่างเดียว</span>';
    sheet.classList.toggle('edit-on', st.editOn);
  }
  $('btn-edit-mode').addEventListener('click', () => { st.editOn = !st.editOn; renderEditMode(); fillFields(); });

  // ---------- หัวข้อเสริม ----------
  const OPTIONAL = [
    { key: 'references', label: 'อ้างถึง', placeholder: ['[✏️ ระบุหนังสือที่อ้างถึง]'] },
    { key: 'attachments', label: 'สิ่งที่ส่งมาด้วย', placeholder: ['[✏️ ระบุสิ่งที่ส่งมาด้วย]'] },
    { key: 'memo_law', label: 'ข้อกฎหมาย', memoOnly: true, placeholder: '[✏️ ระบุข้อกฎหมายจากคลังที่ยืนยันแล้ว]' },
  ];
  function renderToggles() {
    const items = OPTIONAL.filter(o => !o.memoOnly || isMemo());
    $('section-toggles').innerHTML = items.map((o, i) => `
      ${i ? '<span class="text-slate-300">|</span>' : ''}
      <label class="inline-flex items-center gap-1.5 cursor-pointer text-slate-700 hover:text-slate-900">
        <input type="checkbox" data-opt="${o.key}" ${st.doc[o.key] != null ? 'checked' : ''} class="rounded border-slate-300 text-brand-600 focus:ring-0 w-3.5 h-3.5">
        <span class="text-[11px] font-medium">${o.label}</span>
      </label>`).join('');
    const on = items.filter(o => st.doc[o.key] != null).length;
    $('section-count').textContent = `${toThai(on)}/${toThai(items.length)} หัวข้อเปิดใช้งาน`;
  }
  $('section-toggles').addEventListener('change', (e) => {
    const key = e.target.dataset.opt; if (!key) return;
    const opt = OPTIONAL.find(o => o.key === key);
    commit((d) => {
      if (e.target.checked) d[key] = st.stash[key] ?? opt.placeholder;
      else { st.stash[key] = d[key]; d[key] = null; }
    });
  });
  $('toggle-thai-num').addEventListener('change', (e) => commit(d => { d.use_thai_numerals = e.target.checked; }));
  $('font-select').addEventListener('change', (e) => commit(d => { d.font_family = e.target.value; }));
  const FONT_LABEL = { it9: 'TH SarabunIT๙', psk: 'TH SarabunPSK', sarabun_new: 'TH Sarabun New' };

  // ---------- หน่วยออกหนังสือ / สายการเสนอ (บันทึกข้อความ) ----------
  // ค่าที่เปลี่ยนตามหน่วย: ส่วนราชการ เลขที่ วันที่ ผู้ประสาน ผู้รับ ผู้ลงนาม ผู้พิจารณา และภาคความประสงค์มาตรฐาน
  const UNIT_FIELDS = ['dept_name', 'doc_number', 'doc_date', 'contact_dept', 'contact_tel', 'contact_fax',
    'salutation', 'signatory_name', 'signatory_position', 'co_signers', 'memo_consideration', 'memo_request', 'paragraph_purpose'];
  let units = [];
  const unitIndex = (key) => units.findIndex(u => u.key === key);
  const currentUnitKey = () => entry.unitKey || units.find(u => u.is_default)?.key || units[0]?.key;
  // ทุกฉบับในสายการเสนอเดียวกัน (เรียงจากขั้นแรก) — ฉบับเดี่ยวคือสายที่มีฉบับเดียว
  const chainIds = () => entry.chainIds?.length ? entry.chainIds : [entry.id];
  function renderChainButtons() {
    const memo = isMemo() && units.length > 0;
    const next = memo ? units[unitIndex(currentUnitKey()) + 1] : null;
    $('btn-next-level').hidden = !next;
    if (next) $('next-level-label').textContent = 'เสนอขั้นถัดไป: ' + next.label;
    $('btn-chain-pdf').hidden = !(memo && chainIds().length > 1);
  }
  api.units().then((list) => {
    units = list;
    const current = currentUnitKey();
    $('unit-select').innerHTML = units.map(u =>
      `<option value="${esc(u.key)}" ${u.key === current ? 'selected' : ''}>${esc(u.label)}</option>`).join('');
    renderChainButtons();
  }).catch(() => { $('unit-wrap').hidden = true; });
  $('unit-select').addEventListener('change', async (e) => {
    const key = e.target.value;
    try {
      const updated = await api.applyUnit(st.doc, key);
      commit(d => { UNIT_FIELDS.forEach(f => { d[f] = updated[f]; }); });
      entry.unitKey = key;
      renderChainButtons();
      toast('เปลี่ยนส่วนราชการ เลขที่ ผู้รับ และผู้ลงนามตามหน่วยแล้ว');
    } catch (err) { toast(err.message, 'error'); }
  });

  // สร้างฉบับเสนอขั้นถัดไป: คัดลอกเนื้อหา แล้วเปลี่ยนหัวหนังสือ ผู้รับ ผู้ลงนาม ตามหน่วยขั้นถัดไป
  $('btn-next-level').addEventListener('click', async (e) => {
    const next = units[unitIndex(currentUnitKey()) + 1];
    if (!next) return;
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      await persist();
      const doc = await api.applyUnit(st.doc, next.key);
      doc.edit_status = 'editing';
      const ids = chainIds();
      const child = { title: doc.subject, doc, unitKey: next.key, context: entry.context, prompt: entry.prompt, chainIds: ids };
      const newId = await store.create(child);
      child.chainIds = [...ids, newId];
      await store.save(child);
      entry.chainIds = child.chainIds;
      await persist();
      // ฉบับก่อนหน้าในสายรู้จักฉบับใหม่ด้วย (กดชุดเสนอจากฉบับไหนก็ได้ครบ)
      for (const cid of ids.filter(x => x !== entry.id)) {
        const m = await store.get(cid);
        if (m) { m.chainIds = child.chainIds; await store.save(m); }
      }
      location.href = `editor.html?id=${encodeURIComponent(newId)}`;
    } catch (err) { toast('สร้างฉบับขั้นถัดไปไม่สำเร็จ: ' + err.message, 'error'); btn.disabled = false; }
  });

  // ชุดเสนอ PDF: ฉบับขั้นสูงสุดอยู่หน้าแรก ไล่ลงไปถึงฉบับต้นเรื่อง (แบบแฟ้มเสนอจริง)
  $('btn-chain-pdf').addEventListener('click', async (e) => {
    const btn = e.currentTarget, html = btn.innerHTML;
    btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i><span>กำลังรวม...</span>';
    try {
      await persist();
      const members = [];
      for (const cid of chainIds()) {
        const m = cid === entry.id ? { ...entry, doc: st.doc } : await store.get(cid);
        if (m?.doc) members.push(m);
      }
      members.sort((a, b) => unitIndex(b.unitKey) - unitIndex(a.unitKey));
      const blob = await api.exportPdfBundle(members.map(m => m.doc));
      download(blob, `ชุดเสนอ_${safeName()}.pdf`);
    } catch (err) { toast('รวม PDF ไม่สำเร็จ: ' + err.message, 'error'); }
    finally { btn.disabled = false; btn.innerHTML = html; }
  });

  // ---------- สถานะ / ผลตรวจ ----------
  async function runCheck() {
    try {
      st.check = await api.check(st.doc);
      renderChrome(); renderChecks();
      persist();
    } catch (err) { /* ตรวจไม่สำเร็จ: คงผลเดิม */ }
  }
  function counts() {
    const ph = st.check?.placeholders?.length ?? 0;
    const issues = st.check?.lint?.issues || [];
    return { ph, errors: issues.filter(i => i.severity === 'error').length, warnings: issues.filter(i => i.severity !== 'error').length };
  }
  function renderChrome() {
    const d = st.doc, c = counts();
    $('type-label').textContent = DOC_TYPE_LABEL[d.doc_type] || 'เอกสาร';
    $('doc-title').textContent = d.subject || 'ไม่มีชื่อเรื่อง';
    $('doc-title').title = d.subject || '';
    document.title = `${d.subject || 'เอกสาร'} — GovDoc Studio`;
    const chip = $('status-chip');
    if (c.ph === 0 && c.errors === 0) {
      chip.className = 'inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-medium border text-emerald-700 bg-emerald-50 border-emerald-300';
      chip.innerHTML = '<i class="fa-solid fa-check text-[9px]"></i>ร่างสมบูรณ์';
    } else {
      chip.className = 'inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-medium border text-amber-800 bg-amber-50 border-amber-300';
      chip.innerHTML = `<i class="fa-solid fa-pen text-[9px]"></i>ต้องระบุ ${toThai(c.ph)} จุด`;
    }
    $('left-status').textContent = c.ph ? `เหลือ ${toThai(c.ph)} จุดที่ต้องระบุ` : 'เอกสารพร้อมตรวจ';
    $('left-status').className = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs border ' + (c.ph ? 'text-amber-800 bg-amber-50 border-amber-300' : 'text-emerald-700 bg-emerald-50 border-emerald-300');
    const lint = $('btn-lint');
    const n = c.errors + c.warnings;
    lint.innerHTML = n === 0
      ? '<i class="fa-solid fa-circle-check text-brand-600"></i><span class="font-medium text-emerald-800">ตรวจระเบียบผ่าน</span>'
      : `<i class="fa-solid fa-triangle-exclamation ${c.errors ? 'text-rose-600' : 'text-amber-600'}"></i><span class="font-medium ${c.errors ? 'text-rose-700' : 'text-amber-800'}">พบข้อควรแก้ ${toThai(n)} จุด</span>`;
    $('checks-count').textContent = toThai(c.ph + n);
    $('btn-undo').disabled = !st.undo.length; $('btn-redo').disabled = !st.redo.length;
    $('toggle-thai-num').checked = !!d.use_thai_numerals;
    $('font-select').value = d.font_family || 'it9';
    $('sheet').dataset.font = d.font_family || 'it9';
    $('unit-wrap').hidden = !isMemo();
    $('version-count').textContent = toThai(st.versions.length + 1);
    const words = [d.subject, d.paragraph_reason, d.paragraph_details, d.paragraph_purpose, d.memo_law].filter(Boolean).join(' ');
    $('footer-words').textContent = `ความยาว ${toThai(words.replace(/\s+/g, '').length)} ตัวอักษร`;
    $('footer-format').textContent = `A4 · ${FONT_LABEL[d.font_family || 'it9']} ๑๖ pt · ครุฑ ${isMemo() ? '๑.๕ ซม. มุมซ้าย' : '๓ ซม. กึ่งกลาง'}`;
    renderSaveState('saved');
  }

  function renderChecks() {
    const ph = st.check?.placeholders || [];
    const issues = st.check?.lint?.issues || [];
    const phItems = ph.map(p => {
      const [label, ...rest] = p.split(':');
      return `<button type="button" data-jump="${esc(rest.join(':').trim())}" class="w-full text-left flex items-start gap-2.5 p-3 rounded-xl bg-white border border-amber-200 hover:border-amber-400">
        <i class="fa-solid fa-pen text-amber-600 text-xs mt-0.5"></i>
        <span class="text-xs"><span class="font-medium text-slate-800">${esc(label)}</span><span class="block text-slate-500">${esc(rest.join(':').trim())}</span></span></button>`;
    });
    const lintItems = issues.map(i => `
      <div class="flex items-start gap-2.5 p-3 rounded-xl bg-white border ${i.severity === 'error' ? 'border-rose-200' : 'border-slate-200'}">
        <i class="fa-solid ${i.severity === 'error' ? 'fa-circle-xmark text-rose-600' : 'fa-circle-exclamation text-amber-600'} text-xs mt-0.5"></i>
        <span class="text-xs"><span class="font-medium text-slate-800">${esc(i.message)}</span><span class="block text-slate-500 mt-0.5">${esc(i.suggestion)}</span></span>
      </div>`);
    $('tab-checks').innerHTML = (phItems.length ? `<h3 class="text-[11px] font-semibold text-slate-400 tracking-wider">จุดที่ต้องระบุ (${toThai(ph.length)})</h3>${phItems.join('')}` : '')
      + (lintItems.length ? `<h3 class="text-[11px] font-semibold text-slate-400 tracking-wider pt-2">ระเบียบงานสารบรรณ (${toThai(issues.length)})</h3>${lintItems.join('')}` : '')
      || '<p class="text-xs text-emerald-700"><i class="fa-solid fa-circle-check mr-1"></i>ไม่พบจุดที่ต้องแก้ไข</p>';
  }
  $('tab-checks').addEventListener('click', (e) => { const b = e.target.closest('[data-jump]'); if (b) jumpToPlaceholder(b.dataset.jump); });

  function jumpToPlaceholder(text) {
    const chips = [...sheet.querySelectorAll('.ph-chip')];
    const chip = chips.find(c => !text || c.textContent === text || c.textContent === num(text)) || chips[0];
    if (!chip) { toast('ไม่มีจุดที่ต้องระบุแล้ว'); return; }
    const el = chip.closest('[data-field]');
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    if (st.editOn) setTimeout(() => el.focus(), 250);
  }

  // ---------- ฉบับจริง (ไฟล์ Word/PDF ที่แก้เสร็จแล้วอัปโหลดกลับ) ----------
  const fmtSize = (n) => n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';
  const plainText = (s) => String(s || '').replace(/[​\s]+/g, '');
  const fmtTime = (iso) => { try { return num(new Date(iso).toLocaleString('th-TH', { dateStyle: 'medium', timeStyle: 'short' })); } catch (_) { return iso; } };
  const finalsEnabled = (await window.GovDoc.auth.serverMode()) === true;
  async function loadFinals() {
    if (!finalsEnabled) {
      $('finals-local').classList.remove('hidden');
      $('finals-form').querySelectorAll('input,button').forEach(el => { el.disabled = true; });
      return;
    }
    try {
      const rows = await api.finals.list(entry.id);
      $('finals-count').textContent = toThai(rows.length);
      $('finals-list').innerHTML = rows.length ? rows.map((r) => {
        const subjectDiffers = r.subject && plainText(r.subject) !== plainText(st.doc.subject);
        return `<li class="bg-white border border-slate-200 rounded-xl p-3 space-y-1">
          <div class="flex items-center gap-2">
            <span class="px-2 py-0.5 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-800 font-medium shrink-0">ฉบับที่ ${toThai(r.revision)}</span>
            <span class="truncate font-medium text-slate-800" title="${esc(r.filename)}">${esc(r.filename)}</span>
            <button type="button" data-final="${esc(r.id)}" class="ml-auto shrink-0 inline-flex items-center gap-1 px-2 py-0.5 rounded-md border border-slate-300 hover:bg-slate-50 text-slate-700"><i class="fa-solid fa-download"></i>ดาวน์โหลด</button>
          </div>
          <div class="text-slate-500">${fmtTime(r.created_at)} · ${fmtSize(r.size_bytes)} · SHA-256 <code title="${esc(r.sha256)}">${esc(r.sha256.slice(0, 12))}…</code></div>
          ${r.doc_number || r.subject ? `<div class="text-slate-600">${r.doc_number ? `ที่ ${esc(r.doc_number)}` : ''}${r.doc_number && r.subject ? ' · ' : ''}${r.subject ? `เรื่อง ${esc(r.subject)}` : ''}</div>` : ''}
          ${subjectDiffers ? '<div class="text-amber-700"><i class="fa-solid fa-triangle-exclamation"></i> เรื่องในไฟล์ไม่ตรงกับร่างในระบบ — ตรวจว่าอัปโหลดถูกไฟล์</div>' : ''}
          ${r.note ? `<div class="text-slate-600">หมายเหตุ: ${esc(r.note)}</div>` : ''}
        </li>`;
      }).join('') : '<li class="text-slate-400 text-center py-4">ยังไม่มีฉบับจริง</li>';
    } catch (err) { $('finals-list').innerHTML = `<li class="text-rose-600">${esc(err.message)}</li>`; }
  }
  $('finals-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const file = $('finals-file').files[0];
    if (!file) { toast('เลือกไฟล์ Word หรือ PDF ก่อน', 'warn'); return; }
    if (!/\.(docx|pdf)$/i.test(file.name)) { toast('รับเฉพาะไฟล์ .docx หรือ .pdf (ไฟล์ .doc รุ่นเก่าให้บันทึกเป็น .docx ก่อน)', 'error'); return; }
    if (file.size > 50 * 1024 * 1024) { toast('ไฟล์ใหญ่เกิน 50 MB', 'error'); return; }
    const btn = $('finals-submit'), html = btn.innerHTML;
    btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i><span>กำลังอัปโหลด...</span>';
    try {
      await persist();
      const row = await api.finals.upload(entry.id, file, $('finals-note').value.trim());
      $('finals-file').value = ''; $('finals-note').value = '';
      toast(`เก็บเป็นฉบับจริงฉบับที่ ${toThai(row.revision)} แล้ว`);
      loadFinals();
    } catch (err) { toast('อัปโหลดไม่สำเร็จ: ' + err.message, 'error'); }
    finally { btn.disabled = false; btn.innerHTML = html; }
  });
  $('finals-list').addEventListener('click', async (e) => {
    const b = e.target.closest('[data-final]');
    if (!b) return;
    try { location.href = await api.finals.downloadUrl(entry.id, b.dataset.final); }
    catch (err) { toast('ดาวน์โหลดไม่สำเร็จ: ' + err.message, 'error'); }
  });
  loadFinals();

  // ---------- แท็บซ้าย ----------
  function selectTab(name) {
    document.querySelectorAll('[data-tab]').forEach(t => {
      const on = t.dataset.tab === name;
      t.setAttribute('aria-selected', String(on));
      t.className = 'pb-2 border-b-2 ' + (on ? 'border-brand-600 text-slate-900 font-medium' : 'border-transparent text-slate-500 hover:text-slate-800');
    });
    ['chat', 'source', 'checks', 'finals'].forEach(n => { $('tab-' + n).hidden = n !== name; });
  }
  document.querySelectorAll('[data-tab]').forEach(t => t.addEventListener('click', () => selectTab(t.dataset.tab)));
  $('btn-lint').addEventListener('click', () => { showLeft(); selectTab('checks'); });
  $('rail-source').addEventListener('click', () => { showLeft(); selectTab('source'); });
  function showLeft() { $('left-pane').classList.remove('max-lg:hidden'); }
  $('btn-left-toggle').addEventListener('click', () => $('left-pane').classList.toggle('max-lg:hidden'));

  // บทสนทนา: สร้างจากขั้นตอนที่ระบบทำจริง (ไม่ใช่ข้อความจำลอง)
  const avatar = '<div class="w-6 h-6 rounded bg-brand-600 text-white flex items-center justify-center shrink-0 mt-0.5 text-[10px]"><i class="fa-solid fa-file"></i></div>';
  function renderChat() {
    const c = counts();
    const steps = entry.steps || [];
    const user = entry.prompt ? `
      <div class="flex justify-end"><div class="max-w-[85%] bg-white border border-slate-200 rounded-2xl rounded-tr-sm px-3.5 py-2.5 text-xs text-slate-800 font-body leading-relaxed whitespace-pre-wrap">${esc(entry.prompt)}</div></div>` : '';
    const file = entry.sourceName ? `
      <div class="flex justify-end"><div class="inline-flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-emerald-50 border border-emerald-200 text-xs"><i class="fa-regular fa-file text-emerald-600"></i>${esc(entry.sourceName)}</div></div>` : '';
    const tools = steps.length ? `
      <div class="flex items-start gap-2.5">${avatar}
        <div class="space-y-1.5 min-w-0">
          <div class="text-xs font-medium text-slate-500">GovDoc AI</div>
          ${steps.map(s => `<div class="flex items-center gap-1.5 text-xs ${s.ok ? 'text-emerald-700 bg-emerald-50 border-emerald-200' : 'text-rose-700 bg-rose-50 border-rose-200'} px-2 py-0.5 rounded border w-fit max-w-full">
            <i class="fa-solid ${s.ok ? 'fa-check' : 'fa-xmark'} text-[10px]"></i><span class="truncate">${esc(s.label)}${s.detail ? ` · ${esc(s.detail)}` : ''}</span></div>`).join('')}
          ${entry.cloudBlocked ? '<div class="flex items-center gap-1.5 text-xs text-slate-600 bg-slate-100 border border-slate-200 px-2 py-0.5 rounded w-fit"><i class="fa-solid fa-lock text-[10px]"></i>เอกสารชั้นลับ: ไม่ได้ใช้ AI ภายนอก</div>' : ''}
        </div>
      </div>` : '';
    const ready = `
      <div class="flex items-start gap-2.5">${avatar}
        <div class="flex-1 space-y-3 min-w-0">
          <div class="text-xs font-medium text-slate-500">GovDoc AI</div>
          <div><p class="font-medium text-slate-900">${c.ph ? 'ร่างเอกสารแล้ว เหลือจุดที่ต้องระบุ' : 'ร่างเอกสารเสร็จแล้ว'}</p>
          <p class="text-slate-600 text-xs mt-0.5">${c.ph ? `มี ${toThai(c.ph)} จุดที่ระบบไม่มีข้อมูล จึงเว้นไว้ให้กรอก — คลิกที่ช่องสีเหลืองบนกระดาษเพื่อพิมพ์ทับ` : 'ตรวจทานข้อเท็จจริงอีกครั้งก่อนส่งออก'}</p></div>
          <button type="button" id="card-open" class="w-full bg-white border-2 border-emerald-500/70 rounded-xl p-3 shadow-sm hover:border-emerald-600 transition flex items-center justify-between gap-2 text-left group">
            <span class="flex items-center gap-3 min-w-0">
              <span class="w-9 h-9 rounded-lg bg-emerald-50 text-emerald-700 flex items-center justify-center shrink-0"><i class="fa-regular fa-file-lines"></i></span>
              <span class="text-xs min-w-0"><span class="text-emerald-700 font-medium">กำลังเปิดอยู่</span><span class="text-slate-400 mx-1">·</span><span class="text-slate-500 font-medium">${DOC_TYPE_LABEL[st.doc.doc_type]}</span>
              <span class="block text-slate-800 font-medium mt-0.5 truncate">${esc(st.doc.subject)}</span></span>
            </span>
            <i class="fa-solid fa-chevron-right text-slate-400 text-xs group-hover:translate-x-0.5 transition"></i>
          </button>
          ${c.ph ? `<button type="button" id="card-jump" class="text-xs text-amber-800 bg-amber-50 border border-amber-200 hover:bg-amber-100 px-3 py-1.5 rounded-lg"><i class="fa-solid fa-location-crosshairs mr-1"></i>ไปยังจุดที่ต้องระบุ</button>` : ''}
        </div>
      </div>`;
    const summary = entry.context?.summary ? `
      <div class="flex items-start gap-2.5">${avatar}
        <div class="flex-1 space-y-1 min-w-0"><div class="text-xs font-medium text-slate-500">สรุปต้นเรื่อง</div>
          <p class="text-xs text-slate-700 leading-relaxed bg-white border border-slate-200/80 p-3 rounded-lg font-body">${esc(entry.context.summary)}</p></div>
      </div>` : '';
    $('tab-chat').innerHTML = user + file + tools + ready + summary;
    $('card-open')?.addEventListener('click', () => $('doc-viewport').scrollTo({ top: 0, behavior: 'smooth' }));
    $('card-jump')?.addEventListener('click', () => jumpToPlaceholder());
  }

  // ต้นเรื่อง + ค้นหา/ไฮไลต์
  function renderSource() {
    const ctx = entry.context;
    if (!ctx) {
      $('source-meta').innerHTML = '';
      $('source-text').textContent = 'เอกสารนี้ไม่ได้สร้างจากต้นเรื่อง (เปิดจากแบบเปล่าหรือแม่แบบ)';
      return;
    }
    const row = (k, v) => v ? `<dt class="text-slate-400">${k}</dt><dd class="text-slate-700 font-body">${esc(v)}</dd>` : '';
    $('source-meta').innerHTML = row('ไฟล์', entry.sourceName || ctx.source_filename) + row('จาก', ctx.source_dept) + row('ที่', ctx.source_doc_no)
      + row('ลงวันที่', ctx.source_date) + row('เรื่อง', ctx.source_subject) + row('OCR', ctx.ocr_engine_used);
    highlightSource();
  }
  function highlightSource() {
    const text = entry.context?.raw_text || '';
    const q = $('source-search').value.trim();
    if (!q) { $('source-text').textContent = text || '(ไม่มีข้อความ)'; $('source-hits').textContent = ''; return; }
    const parts = text.split(q);
    $('source-text').innerHTML = parts.map(esc).join(`<mark class="bg-amber-200 text-slate-900 rounded px-0.5">${esc(q)}</mark>`);
    $('source-hits').textContent = `${toThai(parts.length - 1)} แห่ง`;
    $('source-text').querySelector('mark')?.scrollIntoView({ block: 'center' });
  }
  $('source-search').addEventListener('input', highlightSource);

  // ---------- เกลาสำนวน ----------
  function openRefine(key, anchor) {
    const pop = $('refine-pop');
    const text = FIELDS[key].get(st.doc);
    st.refine = { key, result: null };
    $('refine-field').textContent = '· ' + FIELD_LABEL[key];
    $('refine-before').textContent = text;
    $('refine-after-wrap').hidden = true;
    $('refine-apply').disabled = true;
    pop.hidden = false;
    const host = pop.offsetParent.getBoundingClientRect();
    const a = anchor.getBoundingClientRect();
    const left = Math.min(Math.max(16, a.left - host.left - pop.offsetWidth - 8), host.width - pop.offsetWidth - 16);
    const top = Math.min(Math.max(16, a.top - host.top - 20), host.height - pop.offsetHeight - 48);
    pop.style.left = left + 'px'; pop.style.top = top + 'px';
    pop.querySelector('[data-cmd]').focus();
  }
  function closeRefine() { $('refine-pop').hidden = true; st.refine = null; }
  $('refine-pop').addEventListener('click', async (e) => {
    if (e.target.closest('[data-refine-close]')) return closeRefine();
    const b = e.target.closest('[data-cmd]');
    if (!b || !st.refine) return;
    b.disabled = true;
    try {
      const res = await api.refine(FIELDS[st.refine.key].get(st.doc), b.dataset.cmd);
      st.refine.result = res.refined;
      $('refine-after').textContent = res.refined;
      $('refine-after-wrap').hidden = false;
      $('refine-apply').disabled = res.refined === res.original;
      if (res.refined === res.original) $('refine-after').textContent = 'ไม่มีส่วนที่ต้องปรับตามคำสั่งนี้';
    } catch (err) { toast(err.message, 'error'); }
    finally { b.disabled = false; }
  });
  $('refine-apply').addEventListener('click', () => {
    const { key, result } = st.refine || {};
    if (result == null) return;
    commit(d => FIELDS[key].set(d, result));
    closeRefine();
    const el = sheet.querySelector(`[data-field="${key}"]`);
    el?.classList.add('flash-ok'); setTimeout(() => el?.classList.remove('flash-ok'), 2300);
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeRefine(); $('quick-menu').hidden = true; } });

  // ---------- ปุ่มลัด ----------
  $('btn-quick').addEventListener('click', (e) => {
    e.stopPropagation();
    const m = $('quick-menu'); m.hidden = !m.hidden;
    $('btn-quick').setAttribute('aria-expanded', String(!m.hidden));
  });
  document.addEventListener('click', (e) => { if (!e.target.closest('#quick-menu, #btn-quick')) $('quick-menu').hidden = true; });
  $('quick-menu').addEventListener('click', async (e) => {
    const b = e.target.closest('[data-quick]'); if (!b) return;
    $('quick-menu').hidden = true;
    const act = b.dataset.quick;
    if (act === 'jump') jumpToPlaceholder();
    if (act === 'lint') { showLeft(); selectTab('checks'); runCheck(); }
    if (act === 'print') window.print();
    if (act === 'formal') {
      const keys = isMemo() ? ['memo_intro', 'memo_facts', 'memo_consideration', 'memo_request'] : ['paragraph_reason', 'paragraph_details', 'paragraph_purpose'];
      try {
        const results = await Promise.all(keys.map(k => api.refine(FIELDS[k].get(st.doc), 'formal')));
        const changed = results.filter(r => r.refined !== r.original).length;
        if (!changed) { toast('ทุกย่อหน้าเป็นทางการอยู่แล้ว'); return; }
        commit(d => keys.forEach((k, i) => FIELDS[k].set(d, results[i].refined)));
        toast(`ปรับ ${toThai(changed)} ย่อหน้าแล้ว — กดเลิกทำได้ถ้าไม่ต้องการ`);
      } catch (err) { toast(err.message, 'error'); }
    }
  });

  // ---------- ส่งออก ----------
  const safeName = () => (st.doc.subject || 'เอกสาร').replace(/[\\/:*?"<>|\[\]✏️]/g, '').trim().slice(0, 60) || 'เอกสาร';
  async function exportAs(kind, btn) {
    const c = counts();
    if (c.ph && !confirm(`ยังมี ${c.ph} จุดที่ต้องระบุ ต้องการส่งออกเป็นฉบับร่างหรือไม่?`)) return;
    const html = btn.innerHTML;
    btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i><span>กำลังสร้าง...</span>';
    try {
      const blob = kind === 'pdf' ? await api.exportPdf(st.doc) : await api.exportDocx(st.doc);
      download(blob, `${safeName()}.${kind}`);
      st.doc.edit_status = 'saved'; persist();
      snapshot(kind === 'pdf' ? 'ส่งออก PDF' : 'ส่งออก Word');
    } catch (err) { toast('ส่งออกไม่สำเร็จ: ' + err.message, 'error'); }
    finally { btn.disabled = false; btn.innerHTML = html; }
  }
  $('btn-docx').addEventListener('click', (e) => exportAs('docx', e.currentTarget));
  $('btn-pdf').addEventListener('click', (e) => exportAs('pdf', e.currentTarget));

  // ---------- ร่างใหม่จากข้อมูลเพิ่มเติม ----------
  $('redraft-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const extra = $('redraft-input').value.trim();
    if (!extra) { $('redraft-input').focus(); return; }
    const base = entry.context?.raw_text || entry.prompt || '';
    if (!confirm('ร่างใหม่ทั้งฉบับจากต้นเรื่องเดิมรวมกับข้อมูลที่เพิ่ม? (ฉบับปัจจุบันจะเก็บไว้ในประวัติเวอร์ชัน)')) return;
    $('redraft-btn').disabled = true;
    const fd = new FormData();
    fd.append('prompt', [base, extra].filter(Boolean).join('\n\n'));
    fd.append('doc_type', st.doc.doc_type);
    fd.append('urgency', st.doc.urgency);
    fd.append('secret', st.doc.secret);
    try {
      const res = await api.draft(fd);
      if (!res.document) throw new Error(res.steps.find(s => !s.ok)?.detail || 'ร่างไม่สำเร็จ');
      st.versions.push({ at: new Date().toISOString(), doc: st.doc, note: 'ก่อนร่างใหม่' });
      snapshot('ก่อนร่างใหม่');
      st.undo = []; st.redo = [];
      st.doc = res.document; st.check = res.check;
      entry.steps = res.steps; entry.context = res.context;
      entry.prompt = [entry.prompt, extra].filter(Boolean).join('\n\n');
      $('redraft-input').value = '';
      renderAll(); renderSource(); persist();
      toast('ร่างใหม่แล้ว');
    } catch (err) { toast(err.message, 'error'); }
    finally { $('redraft-btn').disabled = false; }
  });

  // ---------- ประวัติเวอร์ชัน ----------
  const vModal = $('modal-versions');
  function openVersions() {
    const rows = [{ at: st.savedAt, doc: st.doc, note: 'ฉบับปัจจุบัน', current: true }, ...st.versions.slice().reverse()];
    $('versions-list').innerHTML = rows.map((v, i) => `
      <li class="flex items-center gap-3 p-3 rounded-xl border ${v.current ? 'border-emerald-200 bg-emerald-50/50' : 'border-slate-200'}">
        <div class="flex-1 min-w-0"><div class="font-medium text-slate-800 truncate">${esc(v.doc.subject)}</div>
          <div class="text-[11px] text-slate-500">${esc(v.note || '')} · ${esc(relTime(v.at))}</div></div>
        ${v.current ? '<span class="text-[10px] text-emerald-700">กำลังใช้</span>' : `<button type="button" data-restore="${st.versions.length - i}" class="text-xs px-2.5 py-1 rounded-lg border border-slate-300 hover:bg-slate-50">กู้คืน</button>`}
      </li>`).join('');
    vModal.hidden = false;
  }
  $('btn-versions').addEventListener('click', openVersions);
  $('rail-history').addEventListener('click', openVersions);
  vModal.addEventListener('click', (e) => {
    if (e.target === vModal || e.target.closest('[data-close]')) { vModal.hidden = true; return; }
    const b = e.target.closest('[data-restore]'); if (!b) return;
    const idx = +b.dataset.restore;
    const v = st.versions[idx];
    st.versions.splice(idx, 1);
    st.versions.push({ at: new Date().toISOString(), doc: st.doc, note: 'ก่อนกู้คืน' });
    snapshot('ก่อนกู้คืน');
    commit(d => Object.assign(d, JSON.parse(JSON.stringify(v.doc))));
    vModal.hidden = true;
    toast('กู้คืนเวอร์ชันแล้ว');
  });

  // ---------- ย่อกระดาษให้พอดีจอ (คงสัดส่วน A4) ----------
  function fitSheet() {
    const vp = $('doc-viewport'), wrap = $('sheet-wrap');
    const sheetW = sheet.offsetWidth;
    const scale = Math.min(1, (vp.clientWidth - 32) / sheetW);
    // ย่อที่ตัวกระดาษ (มุมซ้ายบน) แล้วให้กรอบนอกมีขนาดเท่าที่ย่อ เพื่อให้จัดกึ่งกลางได้
    sheet.style.transformOrigin = 'top left';
    sheet.style.transform = scale < 1 ? `scale(${scale})` : '';
    wrap.style.width = scale < 1 ? sheetW * scale + 'px' : '21cm';
    wrap.style.height = scale < 1 ? sheet.offsetHeight * scale + 'px' : '';
  }
  new ResizeObserver(fitSheet).observe($('doc-viewport'));

  // ---------- เรนเดอร์ทั้งหมด ----------
  function renderAll() {
    sheet.innerHTML = sheetHTML();
    fillFields();
    renderToggles();
    renderChrome();
    renderChecks();
    renderChat();
    fitSheet();
  }

  api.profile().then(p => {
    const bare = String(p.signatory_name || '').replace(/[()]/g, '').replace(/^(นางสาว|นาง|นาย)\s*/, '').trim().split(/\s+/);
    $('rail-avatar').textContent = (bare[0]?.[0] || '') + (bare[1]?.[0] || '') || '–';
    $('rail-avatar').title = p.signatory_name || '';
  }).catch(() => {});

  renderEditMode();
  renderAll();
  renderSource();
  if (!st.check) runCheck();
})();
