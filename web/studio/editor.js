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
  // ชื่อหัวข้อบันทึกข้อความแก้ได้อิสระ (ว่าง = ไม่แสดงหัวข้อนั้นในไฟล์ที่ส่งออก)
  const MEMO_HEADS = { intro: 'ต้นเรื่อง', law: 'ข้อกฎหมาย', facts: 'ข้อเท็จจริง', consideration: 'ข้อพิจารณาและเสนอแนะ' };
  for (const [k, def] of Object.entries(MEMO_HEADS)) {
    FIELDS['head_' + k] = {
      get: d => d.memo_headings?.[k] ?? def,
      set: (d, v) => { d.memo_headings = { ...(d.memo_headings || {}), [k]: v.trim() }; },
    };
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
    head_intro: 'หัวข้อ (ว่าง = ไม่แสดง)', head_law: 'หัวข้อ (ว่าง = ไม่แสดง)', head_facts: 'หัวข้อ (ว่าง = ไม่แสดง)',
    head_consideration: 'หัวข้อ (ว่าง = ไม่แสดง)',
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
  const field = (key, cls = '', empty = '', tag = 'span') =>
    `<${tag} class="editable ${cls}" data-field="${key}" data-empty="${esc(empty || '[คลิกเพื่อพิมพ์ ' + (FIELD_LABEL[key] || '') + ']')}"></${tag}>`;
  // ย่อหน้าเนื้อความ: ทุกบรรทัดเป็นย่อหน้าของตัวเอง ระยะย่อหน้าตามเลขข้อ (๑. 2.5 ซม., ๑.๑ 3.5 ซม., ๑.๑.๑ 4.5 ซม.)
  // ผู้ใช้ปรับเองได้ด้วย Tab / Shift+Tab (แท็บนำหน้า N ตัว = ระดับ N) — ตรงกับ core/memo_layout.py
  const block = (key, cls = '') =>
    `<div class="group relative">${field(key, 'block lines ' + cls, '', 'div')}${REFINABLE.has(key) ? refineBtn(key) : ''}</div>`;
  const RE_L3 = /^[0-9๐-๙]+\.[0-9๐-๙]+\.[0-9๐-๙]+/, RE_L2 = /^([0-9๐-๙]+\.[0-9๐-๙]+|(มาตรา|ข้อ)\s*[0-9๐-๙]+)/;
  const MAX_LEVEL = 6;
  const tabCount = (line) => line.match(/^\t*/)[0].length;
  const autoLevel = (line) => { const s = line.trim(); return RE_L3.test(s) ? 3 : RE_L2.test(s) ? 2 : 1; };
  const lineLevel = (line) => Math.min(tabCount(line), MAX_LEVEL) || autoLevel(line);
  const indentOf = (line) => `${2.5 + (lineLevel(line) - 1)}cm`;
  const lineDiv = (line, inner) => `<div class="ln" style="text-indent:${indentOf(line)}">${inner || '<br>'}</div>`;
  const linesHTML = (text, raw = false) =>
    String(text ?? '').split('\n').map(ln => lineDiv(ln, raw ? esc(ln) : displayHTML(ln))).join('');
  function restyleLines(el) {
    el.querySelectorAll(':scope > div').forEach((div) => { div.style.textIndent = indentOf(div.textContent); });
  }
  function caretLine(el) {
    const sel = getSelection();
    if (!sel.rangeCount || !el.contains(sel.anchorNode)) return null;
    let n = sel.anchorNode;
    while (n && n.parentNode !== el) n = n.parentNode;
    return n && n.nodeType === 1 ? n : null;
  }
  // Tab / Shift+Tab: เลื่อนระดับย่อหน้าของบรรทัดที่เคอร์เซอร์อยู่ (กลับมาเท่าค่าอัตโนมัติ = ลบแท็บออก)
  function shiftIndent(el, delta) {
    const div = caretLine(el);
    if (!div) return;
    const sel = getSelection(), r = sel.getRangeAt(0).cloneRange();
    const pre = document.createRange(); pre.selectNodeContents(div); pre.setEnd(r.endContainer, r.endOffset);
    const caret = pre.toString().length;
    const text = div.textContent, body = text.replace(/^\t+/, '');
    const level = Math.max(1, Math.min(MAX_LEVEL, lineLevel(text) + delta));
    const next = (level === autoLevel(body) ? '' : '\t'.repeat(level)) + body;
    if (next === text) return;
    div.textContent = next;
    const pos = Math.max(0, Math.min(next.length, caret + next.length - text.length));
    const nr = document.createRange();
    if (div.firstChild) nr.setStart(div.firstChild, pos); else nr.setStart(div, 0);
    nr.collapse(true); sel.removeAllRanges(); sel.addRange(nr);
    restyleLines(el);
  }
  let lastLineField = null;
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
  // ผู้ลงนามที่ใช้ตราประทับชื่อ-ตำแหน่ง: กรอบเว้นที่แทนช่องพิมพ์ (ไฟล์ส่งออกเว้นบรรทัดว่างระยะเท่าเดิม)
  const stampArea = () => '<div class="stamp-area" contenteditable="false"><i class="fa-solid fa-stamp"></i>พื้นที่ประทับตราชื่อ-ตำแหน่ง</div>';
  function signature() {
    const d = st.doc;
    return `<div class="mt-[1.2cm] ml-auto w-[9cm] text-center space-y-0.5">
      ${isMemo() ? '' : `<div>${field('closing')}</div><div class="h-[1.6cm]"></div>`}
      ${d.signatory_stamp ? stampArea() : `<div>${field('signatory_name')}</div><div>${field('signatory_position')}</div>`}
      ${isMemo() ? (d.co_signers || []).slice(0, 3).map((co, i) =>
        `<div class="h-[1.2cm]"></div>${co.stamp ? stampArea() : `<div>${field('co_name_' + i)}</div><div>${field('co_pos_' + i)}</div>`}`).join('') : ''}
    </div>`;
  }

  function sheetHTML() {
    const d = st.doc;
    const refs = d.references != null, atts = d.attachments != null;
    if (isMemo()) {
      const law = d.memo_law != null;
      // หัวข้อ: บรรทัดเดี่ยว เริ่มตรงกับเนื้อความ (2.5 ซม.) เว้น 6 pt ทุกหัวข้อรวมต้นเรื่อง — แก้ชื่อได้
      const sec = (key) => `
        <div class="gap-6pt">
          <div class="indent-25">${field('head_' + key.replace('memo_', ''), 'doc-bold underline underline-offset-4 memo-head')}</div>
          ${block(key, 'indent-25 justify-thai')}
        </div>`;
      return `${stamps()}
        <div class="relative flex items-end h-[1.5cm] mb-2">
          <img src="/assets/garuda_krut.png" alt="ตราครุฑ" class="garuda-int absolute left-0 bottom-0">
          <div class="memo-title w-full text-center">บันทึกข้อความ</div>
        </div>
        <div class="space-y-1">
          <div class="flex items-baseline gap-2"><span class="doc-bold shrink-0">ส่วนราชการ</span>${field('dept_name', 'flex-1 dotted-fill one-line min-w-0 overflow-hidden whitespace-nowrap')}</div>
          <div class="flex items-baseline gap-4">
            <div class="flex items-baseline gap-2 flex-1 min-w-0"><span class="doc-bold">ที่</span>${field('doc_number', 'flex-1 dotted-fill')}</div>
            <div class="flex items-baseline gap-2 flex-1 min-w-0"><span class="doc-bold">วันที่</span>${field('doc_date', 'flex-1 dotted-fill')}</div>
          </div>
          <div class="flex items-baseline gap-2"><span class="doc-bold shrink-0">เรื่อง</span><div class="group relative flex-1">${field('subject', 'block first-line-fill')}</div></div>
        </div>
        <div class="gap-6pt flex items-baseline gap-2"><span class="doc-bold">${esc((d.salutation || '').match(SAL_RE)?.[1] || 'เรียน')}</span>${field('salutation_to', 'flex-1')}</div>
        ${refs ? `<div class="mt-1 flex items-baseline gap-2"><span class="doc-bold shrink-0">อ้างถึง</span>${field('references', 'flex-1')}</div>` : ''}
        ${atts ? `<div class="mt-1 flex items-baseline gap-2"><span class="doc-bold shrink-0">สิ่งที่ส่งมาด้วย</span>${field('attachments', 'flex-1')}</div>` : ''}
        <div>
          ${sec('memo_intro')}
          ${law ? sec('memo_law') : ''}
          ${sec('memo_facts')}
          ${sec('memo_consideration')}
          <div class="gap-6pt">${block('memo_request', 'indent-25 justify-thai')}</div>
        </div>
        ${signature()}`;
    }
    return `${stamps()}
      <div class="flex justify-center mb-3"><img src="/assets/garuda_krut.png" alt="ตราครุฑ" class="garuda-ext"></div>
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
      const v = FIELDS[el.dataset.field].get(st.doc);
      el.innerHTML = el.classList.contains('lines') ? linesHTML(v) : displayHTML(v);
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
    const raw = FIELDS[el.dataset.field].get(st.doc);
    if (el.classList.contains('lines')) { el.innerHTML = linesHTML(raw, true); lastLineField = el; } else el.textContent = raw;
    // ถ้าทั้งช่องเป็น placeholder ให้เลือกทั้งหมดเพื่อพิมพ์ทับได้ทันที
    // (ช่องที่มีข้อความอื่นด้วย ไม่เลือกให้ — กันกดปุ่มแล้ว placeholder กลางย่อหน้าหายโดยไม่ตั้งใจ)
    const onlyPlaceholder = hasPlaceholder(el.textContent) && !el.textContent.replace(PH_RE, '').replace(/[()\s]/g, '');
    if (onlyPlaceholder) {
      const m = el.textContent.match(PH_RE);
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      let node = walker.nextNode();
      while (node && m && !node.data.includes(m[0])) node = walker.nextNode();
      if (node && m) {
        const start = node.data.indexOf(m[0]);
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
    const shown = FIELDS[key].get(st.doc);
    el.innerHTML = el.classList.contains('lines') ? linesHTML(shown) : displayHTML(shown);
    if (el.classList.contains('one-line')) fitOneLine();
    renderTodo();
  });
  sheet.addEventListener('keydown', (e) => {
    const el = e.target.closest('[data-field]');
    if (!el) return;
    if (e.key === 'Enter' && !el.classList.contains('block') && !['references', 'attachments'].includes(el.dataset.field)) { e.preventDefault(); el.blur(); }
    if (e.key === 'Escape') { el.blur(); }
    if (e.key === 'Tab' && el.classList.contains('lines')) { e.preventDefault(); shiftIndent(el, e.shiftKey ? -1 : 1); }
  });
  sheet.addEventListener('input', (e) => {
    const el = e.target.closest('.lines');
    if (el) restyleLines(el);
  });
  for (const [id, delta] of [['btn-indent', 1], ['btn-outdent', -1]]) {
    $(id).addEventListener('mousedown', (e) => e.preventDefault());   // คงเคอร์เซอร์ไว้ในย่อหน้า
    $(id).addEventListener('click', () => {
      if (lastLineField && document.activeElement === lastLineField) shiftIndent(lastLineField, delta);
      else toast('คลิกในย่อหน้าที่ต้องการก่อน แล้วกดปุ่มนี้ (หรือกด Tab / Shift+Tab)');
    });
  }
  // วางข้อความเป็น plain text เท่านั้น
  sheet.addEventListener('paste', (e) => {
    if (!e.target.closest('[data-field]')) return;
    e.preventDefault();
    const text = e.clipboardData.getData('text/plain').replace(/\r\n?/g, '\n');
    if (!e.target.closest('.lines')) { document.execCommand('insertText', false, text); return; }
    text.split('\n').forEach((part, i) => {
      if (i) document.execCommand('insertParagraph');
      if (part) document.execCommand('insertText', false, part);
    });
  });
  sheet.addEventListener('click', (e) => {
    const b = e.target.closest('[data-refine]');
    if (b) openRefine(b.dataset.refine, b);
  });

  // ---------- ตั้งค่าเอกสาร (ฟอนต์ / เลขไทย / หัวข้อเสริม) ----------
  // กระดาษแก้ไขได้เสมอ (ไม่มีโหมดอ่านอย่างเดียวแล้ว) — ช่องพิมพ์ทั้งหมดอยู่บนกระดาษ
  function toggleSettings(open = $('settings-menu').hidden) {
    $('settings-menu').hidden = !open;
    $('btn-settings').setAttribute('aria-expanded', String(open));
  }
  $('btn-settings').addEventListener('click', (e) => { e.stopPropagation(); toggleSettings(); });
  document.addEventListener('click', (e) => { if (!e.target.closest('#settings-menu, #btn-settings')) toggleSettings(false); });

  // ---------- หัวข้อเสริม ----------
  const OPTIONAL = [
    { key: 'references', label: 'อ้างถึง', placeholder: ['[✏️ ระบุหนังสือที่อ้างถึง]'] },
    { key: 'attachments', label: 'สิ่งที่ส่งมาด้วย', placeholder: ['[✏️ ระบุสิ่งที่ส่งมาด้วย]'] },
    { key: 'memo_law', label: 'ข้อกฎหมาย', memoOnly: true, placeholder: '[✏️ ระบุข้อกฎหมายจากคลังที่ยืนยันแล้ว]' },
  ];
  function renderToggles() {
    const items = OPTIONAL.filter(o => !o.memoOnly || isMemo());
    $('section-toggles').innerHTML = items.map((o) => `
      <label class="flex items-center gap-2 cursor-pointer text-slate-700 hover:text-slate-900">
        <input type="checkbox" data-opt="${o.key}" ${st.doc[o.key] != null ? 'checked' : ''} class="rounded border-slate-300 text-brand-600 focus:ring-0 w-3.5 h-3.5">
        <span>${o.label}</span>
      </label>`).join('');
    const on = items.filter(o => st.doc[o.key] != null).length;
    $('section-count').textContent = `เปิด ${toThai(on)}/${toThai(items.length)}`;
    // ผู้ลงนามแต่ละคน: ใช้ตราประทับชื่อ-ตำแหน่งหรือไม่ (ชื่อที่แสดง = ตำแหน่ง ถ้ายังไม่มีใช้ลำดับ)
    const signers = [{ key: 'main', position: st.doc.signatory_position, stamp: !!st.doc.signatory_stamp },
      ...(isMemo() ? (st.doc.co_signers || []).slice(0, 3).map((c, i) => ({ key: String(i), position: c.position, stamp: !!c.stamp })) : [])];
    $('signer-toggles').innerHTML = signers.map((sg, i) => `
      <label class="flex items-center gap-2 cursor-pointer text-slate-700 hover:text-slate-900">
        <input type="checkbox" data-stamp="${sg.key}" ${sg.stamp ? 'checked' : ''} class="rounded border-slate-300 text-brand-600 focus:ring-0 w-3.5 h-3.5">
        <span class="truncate">${esc(String(sg.position || '').replace(PH_RE, '').trim() || 'ผู้ลงนามคนที่ ' + toThai(i + 1))}</span>
      </label>`).join('');
  }
  $('signer-toggles').addEventListener('change', (e) => {
    const key = e.target.dataset.stamp; if (!key) return;
    const on = e.target.checked;
    commit((d) => {
      if (key === 'main') d.signatory_stamp = on;
      else if (d.co_signers?.[+key]) d.co_signers[+key].stamp = on;
    });
    runCheck();
  });
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
    if (next) {
      $('next-level-label').textContent = 'เสนอขั้นถัดไป';
      $('btn-next-level').title = `สร้างบันทึกฉบับเสนอ${next.label}จากฉบับนี้ (แก้ไขแยกได้)`;
      $('btn-next-level').setAttribute('aria-label', 'เสนอขั้นถัดไป: ' + next.label);
    }
    $('btn-chain-pdf').hidden = !(memo && chainIds().length > 1);
    fitToolbar();
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
      const child = { title: doc.subject, doc, unitKey: next.key, context: entry.context, prompt: entry.prompt, chainIds: ids,
        sourceName: entry.sourceName || null, sourceFileId: entry.sourceFileId || null };
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
      const source = sourceText();
      const [check, facts] = await Promise.all([
        api.check(st.doc),
        source ? api.factCheck(st.doc, source).catch(() => null) : null,
      ]);
      check.facts = facts ? visibleFacts(facts.issues) : (st.check?.facts || []);
      st.check = check;
      renderChrome(); renderChecks(); renderTodo();
      persist();
    } catch (err) { /* ตรวจไม่สำเร็จ: คงผลเดิม */ }
  }
  // ต้นเรื่องสำหรับตรวจข้อเท็จจริง: ข้อความที่อ่านจากไฟล์ + คำสั่งที่ผู้ใช้พิมพ์ (ผู้ใช้ให้ข้อมูลเพิ่มเองได้)
  const sourceText = () => [entry.context?.raw_text, entry.prompt].filter(Boolean).join('\n');
  // ข้อเท็จจริงที่ผู้ใช้กด "ถูกต้องแล้ว" ไม่ต้องเตือนซ้ำ (เก็บกับเอกสาร)
  const factKey = (f) => `${f.field}|${f.kind}|${f.text}`;
  const visibleFacts = (list) => (list || []).filter(f => !(entry.factOk || []).includes(factKey(f)));
  function counts() {
    const ph = st.check?.placeholders?.length ?? 0;
    const issues = st.check?.lint?.issues || [];
    return { ph, errors: issues.filter(i => i.severity === 'error').length, warnings: issues.filter(i => i.severity !== 'error').length };
  }
  function renderChrome() {
    const d = st.doc;
    $('type-label').textContent = DOC_TYPE_LABEL[d.doc_type] || 'เอกสาร';
    $('type-select').value = d.doc_type;
    $('doc-title').textContent = d.subject || 'ไม่มีชื่อเรื่อง';
    $('doc-title').title = d.subject || '';
    document.title = `${d.subject || 'เอกสาร'} — GovDoc Studio`;
    $('btn-undo').disabled = !st.undo.length; $('btn-redo').disabled = !st.redo.length;
    $('toggle-thai-num').checked = !!d.use_thai_numerals;
    $('font-select').value = d.font_family || 'it9';
    $('sheet').dataset.font = d.font_family || 'it9';
    $('sheet').dataset.type = isMemo() ? 'internal' : 'external';
    $('unit-wrap').hidden = !isMemo();
    $('version-count').textContent = toThai(st.versions.length + 1);
    const words = [d.subject, d.paragraph_reason, d.paragraph_details, d.paragraph_purpose, d.memo_law].filter(Boolean).join(' ');
    $('footer-words').textContent = `ความยาว ${toThai(words.replace(/\s+/g, '').length)} ตัวอักษร`;
    $('footer-format').textContent = `A4 · ${FONT_LABEL[d.font_family || 'it9']} ๑๖ pt · ครุฑ ${isMemo() ? '๑.๕ ซม. มุมซ้าย' : '๓ ซม. กึ่งกลาง'}`;
    renderSaveState('saved');
    fitToolbar();
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
    const facts = visibleFacts(st.check?.facts);
    const factItems = facts.map((f, i) => `
      <div class="p-3 rounded-xl bg-white border border-amber-200 text-xs space-y-2">
        <div class="flex items-start gap-2.5"><i class="fa-solid fa-magnifying-glass-chart text-amber-600 mt-0.5"></i>
          <span><span class="font-medium text-slate-800">${esc(FIELD_LABEL[f.field] || f.field)}: <span class="font-body">${esc(num(f.text))}</span></span>
          <span class="block text-slate-500 mt-0.5">${esc(f.message)}</span></span></div>
        <div class="flex gap-2 pl-6">
          <button type="button" data-fact-source="${i}" class="px-2 py-1 rounded-md border border-slate-300 hover:bg-slate-50">ดูในต้นเรื่อง</button>
          <button type="button" data-fact-ok="${i}" class="px-2 py-1 rounded-md bg-emerald-600 hover:bg-emerald-700 text-white">ถูกต้องแล้ว</button>
        </div>
      </div>`);
    $('tab-checks').innerHTML = (factItems.length ? `<h3 class="text-[11px] font-semibold text-slate-400 tracking-wider">ตรวจกับต้นเรื่อง (${toThai(facts.length)})</h3>${factItems.join('')}` : '')
      + (phItems.length ? `<h3 class="text-[11px] font-semibold text-slate-400 tracking-wider">จุดที่ต้องระบุ (${toThai(ph.length)})</h3>${phItems.join('')}` : '')
      + (lintItems.length ? `<h3 class="text-[11px] font-semibold text-slate-400 tracking-wider pt-2">ระเบียบงานสารบรรณ (${toThai(issues.length)})</h3>${lintItems.join('')}` : '')
      || '<p class="text-xs text-emerald-700"><i class="fa-solid fa-circle-check mr-1"></i>ไม่พบจุดที่ต้องแก้ไข</p>';
  }
  $('tab-checks').addEventListener('click', (e) => {
    const b = e.target.closest('[data-jump]');
    if (b) { jumpToPlaceholder(b.dataset.jump); return; }
    const facts = visibleFacts(st.check?.facts);
    const s = e.target.closest('[data-fact-source]'), k = e.target.closest('[data-fact-ok]');
    if (s) showFactInSource(facts[+s.dataset.factSource]);
    if (k) confirmFact(facts[+k.dataset.factOk]);
  });

  // ---------- ป้ายเดียว "ต้องแก้": จุดที่ต้องระบุ + ข้อควรแก้ตามระเบียบ ไล่ทีละจุดตามลำดับบนกระดาษ ----------
  // ข้อควรแก้ของ linter อ้างชื่อฟิลด์ในสคีมา — แปลงเป็นช่องบนกระดาษ (บันทึกข้อความใช้ช่อง memo_*)
  const LINT_FIELD = (f) => {
    if (f === 'salutation') return 'salutation_to';
    if (isMemo()) return { paragraph_reason: 'memo_intro', paragraph_details: 'memo_facts', paragraph_purpose: 'memo_request' }[f] || f;
    return f;
  };
  // จุดทั้งหมดเรียงตามตำแหน่งบนกระดาษ: { field: ช่อง, ord: ลำดับในช่อง, text, issue? }
  function todoPoints() {
    const pts = [];
    sheet.querySelectorAll('[data-field]').forEach((el) => {
      el.querySelectorAll('.ph-chip').forEach((chip, ord) => pts.push({ field: el, ord, text: chip.textContent }));
    });
    (st.check?.lint?.issues || []).forEach((issue, i) => {
      const el = sheet.querySelector(`[data-field="${LINT_FIELD(issue.field)}"]`);
      pts.push({ field: el, ord: 1000 + i, text: issue.message, issue });
    });
    visibleFacts(st.check?.facts).forEach((fact, i) => {
      const el = sheet.querySelector(`[data-field="${fact.field}"]`);
      pts.push({ field: el, ord: 2000 + i, text: factKey(fact), fact });
    });
    return pts.sort((a, b) => {
      if (a.field === b.field) return a.ord - b.ord;
      if (!a.field) return 1;
      if (!b.field) return -1;
      return a.field.compareDocumentPosition(b.field) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
    });
  }
  const todo = { last: null };
  function renderTodo() {
    const pts = todoPoints();
    const ph = pts.filter(p => !p.issue && !p.fact).length, facts = pts.filter(p => p.fact).length;
    const issues = pts.length - ph - facts;
    const errors = pts.some(p => p.issue?.severity === 'error');
    const b = $('todo-badge');
    const base = 'shrink-0 whitespace-nowrap inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium border transition ';
    if (!pts.length) {
      b.className = base + 'text-emerald-700 bg-emerald-50 border-emerald-300 hover:bg-emerald-100';
      b.innerHTML = '<i class="fa-solid fa-check text-[10px]"></i><span class="tb-h4">พร้อมส่งออก</span>';
      b.title = 'ไม่มีจุดที่ต้องระบุ และผ่านการตรวจระเบียบงานสารบรรณ';
      todo.last = null;
    } else {
      b.className = base + (errors ? 'text-rose-700 bg-rose-50 border-rose-300 hover:bg-rose-100' : 'text-amber-800 bg-amber-50 border-amber-300 hover:bg-amber-100');
      b.innerHTML = `<i class="fa-solid ${errors ? 'fa-triangle-exclamation' : 'fa-pen'} text-[10px]"></i><span><span class="tb-h4">ต้องแก้ </span>${toThai(pts.length)}<span class="tb-h4"> จุด</span></span><span class="tb-h3 opacity-70">· ถัดไป</span><i class="fa-solid fa-chevron-right text-[9px] opacity-70"></i>`;
      b.title = [ph && `ต้องระบุ ${toThai(ph)} จุด`, issues && `ข้อควรแก้ตามระเบียบ ${toThai(issues)} จุด`,
        facts && `ตรวจกับต้นเรื่อง ${toThai(facts)} จุด`].filter(Boolean).join(' · ') + ' — กดเพื่อไปทีละจุด';
    }
    b.setAttribute('aria-label', b.title);
    fitToolbar();
  }
  // จุดถัดจากจุดที่ไปล่าสุด (กรอกจุดนั้นแล้ว จุดถัดไปในช่องเดียวกันจะเลื่อนมาอยู่ลำดับเดิม)
  function nextTodo() {
    const pts = todoPoints();
    if (!pts.length) { toast('ไม่มีจุดที่ต้องแก้แล้ว — พร้อมส่งออก'); return; }
    const last = todo.last;
    let idx = 0;
    if (last && last.field?.isConnected) {
      const after = pts.findIndex((p) => {
        if (p.field === last.field) return p.ord > last.ord || (p.ord === last.ord && p.text !== last.text);
        if (!p.field) return true;
        return !!(last.field.compareDocumentPosition(p.field) & Node.DOCUMENT_POSITION_FOLLOWING);
      });
      idx = after < 0 ? 0 : after;
    }
    const p = pts[idx];
    todo.last = { field: p.field, ord: p.ord, text: p.text };
    goToPoint(p);
  }
  function goToPoint(p) {
    closeFact();
    if (p.fact) { openFact(p); return; }
    if (p.issue) {
      toast(`${p.issue.message} — ${p.issue.suggestion}`, p.issue.severity === 'error' ? 'error' : 'warn');
      if (!p.field) return;
      p.field.scrollIntoView({ behavior: 'smooth', block: 'center' });
      p.field.classList.remove('flash-warn'); void p.field.offsetWidth; p.field.classList.add('flash-warn');
      return;
    }
    p.field.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setTimeout(() => { p.field.focus(); selectPlaceholder(p.field, p.ord); }, 250);
  }
  // เลือก placeholder ลำดับที่ ord ในช่อง (หลังโฟกัส ช่องแสดงข้อความดิบ) ให้พิมพ์ทับได้ทันที
  function selectPlaceholder(el, ord) {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let n = 0;
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      for (const m of node.data.matchAll(PH_RE)) {
        if (n++ !== ord) continue;
        const r = document.createRange(); r.setStart(node, m.index); r.setEnd(node, m.index + m[0].length);
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
        return;
      }
    }
  }
  $('todo-badge').addEventListener('mousedown', (e) => e.preventDefault());
  $('todo-badge').addEventListener('click', () => {
    // ช่องที่กำลังพิมพ์บันทึกก่อน แล้วค่อยไปจุดถัดไป
    if (document.activeElement?.closest?.('[data-field]')) document.activeElement.blur();
    nextTodo();
  });
  // ---------- ข้อเท็จจริงที่ไม่พบในต้นเรื่อง ----------
  let factOpen = null;
  function openFact(p) {
    factOpen = p;
    const pop = $('fact-pop');
    $('fact-value').textContent = num(p.fact.text);
    $('fact-message').textContent = p.fact.message;
    if (p.field) {
      p.field.scrollIntoView({ behavior: 'smooth', block: 'center' });
      p.field.classList.remove('flash-warn'); void p.field.offsetWidth; p.field.classList.add('flash-warn');
    }
    pop.hidden = false;
    setTimeout(() => {                       // รอเลื่อนเสร็จแล้ววางข้างช่อง
      const host = pop.offsetParent.getBoundingClientRect();
      const a = (p.field || sheet).getBoundingClientRect();
      pop.style.left = Math.max(16, Math.min(a.left - host.left, host.width - pop.offsetWidth - 16)) + 'px';
      const below = a.bottom - host.top + 8;
      pop.style.top = (below + pop.offsetHeight < host.height - 40 ? below : Math.max(16, a.top - host.top - pop.offsetHeight - 8)) + 'px';
      pop.querySelector('[data-fact="source"]').focus();
    }, 320);
  }
  function closeFact() { $('fact-pop').hidden = true; factOpen = null; }
  // คำค้นในต้นเรื่อง: ข้อความตามร่างก่อน แล้วค่อยกว้างขึ้น (ต้นเรื่องอาจใช้เลขไทย/อารบิก หรือเขียนเดือนย่อ)
  const MONTHS = ['มกราคม', 'กุมภาพันธ์', 'มีนาคม', 'เมษายน', 'พฤษภาคม', 'มิถุนายน', 'กรกฎาคม', 'สิงหาคม', 'กันยายน', 'ตุลาคม', 'พฤศจิกายน', 'ธันวาคม'];
  const toArabic = (t) => String(t).replace(/[๐-๙]/g, d => '๐๑๒๓๔๕๖๗๘๙'.indexOf(d));
  function factProbes(f) {
    const a = toArabic(f.text).replace(/^เวลา\s*/, '').replace(/\s*(น\.|นาฬิกา)$/, '').trim();
    const out = [a, toThai(a)];
    if (f.kind === 'date') {
      const month = MONTHS.find(m => a.includes(m));
      const day = a.match(/^\d{1,2}/)?.[0];
      if (month && day) out.push(`${day} ${month}`, `${toThai(day)} ${month}`);
      if (month) out.push(month);
    }
    if (f.kind === 'number') out.push(a.replace(/,/g, ''), toThai(a.replace(/,/g, '')));
    if (f.kind === 'time') { const hh = a.split(/[.:]/)[0]; out.push(hh + '.', toThai(hh) + '.'); }
    return [...new Set(out.filter(Boolean))];
  }
  async function showFactInSource(f) {
    showLeft(); selectTab('source');
    for (const q of factProbes(f)) {
      $('source-search').value = q;
      if ((await runSourceSearch()) > 0) return;
      // ไฟล์สแกนไม่มีชั้นข้อความ: ค้นในข้อความที่อ่านได้
      if (src.view === 'file' && src.viewer && !src.viewer.hasText) {
        setSourceView('text');
        if ((await runSourceSearch()) > 0) return;
      }
    }
    toast('ไม่พบคำใกล้เคียงในต้นเรื่อง — เปิดไฟล์จริงแล้วตรวจด้วยตา', 'warn');
  }
  function confirmFact(f) {
    entry.factOk = [...new Set([...(entry.factOk || []), factKey(f)])];
    if (st.check) st.check.facts = visibleFacts(st.check.facts);
    renderChecks(); renderTodo(); persist();
    toast('บันทึกว่าถูกต้องแล้ว — ไม่เตือนจุดนี้อีก');
  }
  $('fact-pop').addEventListener('click', (e) => {
    const b = e.target.closest('[data-fact]');
    if (!b || !factOpen) return;
    const f = factOpen.fact;
    if (b.dataset.fact === 'close') closeFact();
    if (b.dataset.fact === 'source') showFactInSource(f);
    if (b.dataset.fact === 'ok') { closeFact(); confirmFact(f); }
    if (b.dataset.fact === 'next') { closeFact(); nextTodo(); }
  });
  $('fact-pop').addEventListener('mousedown', (e) => e.preventDefault());
  function jumpToPlaceholder(text) {
    const pts = todoPoints().filter(p => !p.issue && !p.fact);
    const p = pts.find(q => !text || q.text === text || q.text === num(text)) || pts[0];
    if (!p) { toast('ไม่มีจุดที่ต้องระบุแล้ว'); return; }
    todo.last = { field: p.field, ord: p.ord, text: p.text };
    goToPoint(p);
  }

  // ---------- ข้อกฎหมายจากคลัง (ยืนยันแล้วเท่านั้น) ----------
  // เลือกแล้วเก็บใน doc.legal_refs (ใช้แนบหน้าจากไฟล์ต้นฉบับท้าย PDF) และเขียนหัวข้อ "ข้อกฎหมาย" ให้
  // ถ้าผู้ใช้แก้ข้อความหัวข้อเองแล้ว ถามก่อนเขียนทับ
  const law = { lib: null, loading: null, suggestions: [] };
  async function lawLibrary() {
    if (law.lib) return law.lib;
    law.loading = law.loading || api.legal().then(({ references }) => {
      law.lib = new Map(references.filter(r => r.verified).map(r => [String(r.id), r]));
      return law.lib;
    }).finally(() => { law.loading = null; });
    return law.loading;
  }
  const citeOf = (r) => ({ id: String(r.id), title: r.title || '', section: r.section || '', source_id: r.source_id || null,
    page_from: r.page_from || null, page_to: r.page_to || null });
  const pagesOf = (r) => r.page_from ? ` · หน้า ${toThai(r.page_from)}${r.page_to && r.page_to !== r.page_from ? '–' + toThai(r.page_to) : ''}` : '';
  // ข้อความในหัวข้อ "ข้อกฎหมาย" = เนื้อหาที่ผู้ใช้เขียน/แก้ไว้ในคลังเท่านั้น (ไม่เติมชื่อฉบับ หัวข้อ หรือ "กำหนดว่า")
  // บรรทัดที่ขึ้นใหม่เพราะการตัดบรรทัดของไฟล์สแกนต่อเป็นย่อหน้าเดียว; คงการขึ้นบรรทัดหน้า มาตรา / ข้อ / (๑) / ๑.
  const LAW_BREAK = /^(มาตรา|ข้อ|หมวด|ส่วนที่|\([0-9๐-๙]+\)|[0-9๐-๙]+(\.[0-9๐-๙]+)*\.?\s)/;
  function lawBody(quote) {
    const out = [];
    for (const raw of String(quote || '').split('\n')) {
      const line = raw.replace(/\s+/g, ' ').trim();
      if (!line) continue;
      if (out.length && !LAW_BREAK.test(line)) out[out.length - 1] += ' ' + line;
      else out.push(line);
    }
    return out.join('\n');
  }
  function lawText(refs) {
    // รายการที่หาเนื้อหาไม่เจอ (เช่น ถูกลบจากคลัง) ใช้ชื่อแทน เพื่อไม่ให้หายไปเงียบ ๆ
    return refs.map(c => lawBody(law.lib?.get(c.id)?.quote) || `${c.title} ${c.section}`.trim()).join('\n');
  }
  function setLawRefs(next) {
    const auto = entry.lawAuto;
    const cur = st.doc.memo_law;
    const untouched = cur == null || !cur.trim() || hasPlaceholder(cur) || cur === auto;
    const text = lawText(next);
    if (!untouched && isMemo() && !confirm('หัวข้อ "ข้อกฎหมาย" มีข้อความที่แก้เองอยู่ — เขียนใหม่ตามรายการที่เลือก?')) {
      commit(d => { d.legal_refs = next.length ? next : null; });
    } else {
      commit(d => {
        d.legal_refs = next.length ? next : null;
        if (isMemo()) d.memo_law = next.length ? text : null;
      });
      entry.lawAuto = next.length ? text : null;
    }
    renderLaw();
  }
  function lawItem(r, action, extra = '') {
    return `<li class="p-3 rounded-xl bg-white border border-slate-200 space-y-1.5" data-law-id="${esc(r.id)}">
      <div class="flex items-start gap-2">
        <div class="flex-1 min-w-0">
          <div class="font-semibold text-slate-800">${esc(r.section || '')}<span class="font-normal text-slate-400">${pagesOf(r)}</span></div>
          <div class="text-[11px] text-slate-500 truncate" title="${esc(r.title || '')}">${esc(r.title || '')}</div>
        </div>
        ${action}
      </div>
      ${extra}
    </li>`;
  }
  // หน้าที่จะแนบท้าย PDF (นับแบบเดียวกับเซิร์ฟเวอร์: หน้าซ้ำในไฟล์เดียวกันนับครั้งเดียว)
  function lawPageCount(refs) {
    const seen = new Set();
    for (const c of refs) {
      if (!c.source_id || !c.page_from) continue;
      for (let p = c.page_from; p <= Math.max(c.page_from, c.page_to || c.page_from); p++) seen.add(c.source_id + ':' + p);
    }
    return seen.size;
  }
  function renderLaw() {
    const refs = st.doc.legal_refs || [];
    $('law-count').textContent = toThai(refs.length);
    const pages = lawPageCount(refs);
    $('law-attach-wrap').hidden = !refs.length;
    $('law-attach').checked = st.doc.attach_legal_pages !== false;
    $('law-attach-info').textContent = pages
      ? `${toThai(pages)} หน้า จากไฟล์สแกนในคลัง (Word ไม่แนบหน้าสแกน — ใช้ PDF)`
      : 'ข้อที่เลือกไม่มีไฟล์ต้นฉบับในคลัง จึงไม่มีหน้าให้แนบ';
    $('law-external-note').classList.toggle('hidden', isMemo());
    $('law-selected').innerHTML = refs.length ? refs.map(c => lawItem(c,
      `<button type="button" data-law-remove="${esc(c.id)}" class="shrink-0 px-2 py-0.5 rounded-md border border-slate-300 hover:bg-rose-50 hover:border-rose-300 text-slate-600">เอาออก</button>`)).join('')
      : '<li class="text-slate-400">ยังไม่ได้เลือกข้อกฎหมาย</li>';
    const chosen = new Set(refs.map(c => c.id));
    const addBtn = (r) => chosen.has(String(r.id))
      ? '<span class="shrink-0 text-emerald-700"><i class="fa-solid fa-check"></i> ใส่แล้ว</span>'
      : `<button type="button" data-law-add="${esc(r.id)}" class="shrink-0 px-2 py-0.5 rounded-md bg-emerald-600 hover:bg-emerald-700 text-white">ใส่ในบันทึก</button>`;
    $('law-suggestions').innerHTML = law.suggestions.map(s => lawItem(s.reference, addBtn(s.reference),
      `<p class="text-slate-600"><i class="fa-solid ${s.by === 'ai' ? 'fa-wand-magic-sparkles text-emerald-600' : 'fa-magnifying-glass text-slate-400'} mr-1"></i>${esc(s.reason)}</p>`)).join('');
    const q = $('law-search').value.trim();
    const hits = q && law.lib ? [...law.lib.values()].filter(r => [r.title, r.section, r.chapter, r.quote].join(' ').includes(q)).slice(0, 15) : [];
    $('law-results').innerHTML = !q ? '' : hits.length ? hits.map(r => lawItem(r, addBtn(r),
      `<p class="text-slate-500 font-body line-clamp-2">${esc(String(r.quote || '').replace(/\s+/g, ' ').slice(0, 200))}</p>`)).join('')
      : '<li class="text-slate-400">ไม่พบในคลังที่ยืนยันแล้ว</li>';
  }
  async function openLawTab() {
    renderLaw();
    try { await lawLibrary(); renderLaw(); } catch (err) { $('law-results').innerHTML = `<li class="text-rose-600">${esc(err.message)}</li>`; }
  }
  $('law-search').addEventListener('input', renderLaw);
  $('law-attach').addEventListener('change', (e) => commit(d => { d.attach_legal_pages = e.target.checked; }));
  $('law-suggest').addEventListener('click', async (e) => {
    const btn = e.currentTarget, html = btn.innerHTML;
    btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i><span>กำลังหา...</span>';
    try {
      await lawLibrary();
      const d = st.doc;
      const text = [d.subject, d.memo_intro, d.memo_facts, d.memo_consideration, d.paragraph_reason, d.paragraph_details,
        aiSummary()].filter(Boolean).join('\n').replace(PH_RE, ' ');
      law.suggestions = (await api.legalSuggest(text)).suggestions;
      if (!law.suggestions.length) toast(law.lib?.size ? 'ไม่พบข้อที่เกี่ยวข้องในคลังที่ยืนยันแล้ว' : 'คลังกฎหมายยังไม่มีรายการที่ยืนยันแล้ว — นำเข้าได้ที่หน้าแรก > คลังกฎหมาย', 'warn');
      renderLaw();
    } catch (err) { toast('เสนอข้อกฎหมายไม่สำเร็จ: ' + err.message, 'error'); }
    finally { btn.disabled = false; btn.innerHTML = html; }
  });
  $('tab-law').addEventListener('click', async (e) => {
    const add = e.target.closest('[data-law-add]'), rm = e.target.closest('[data-law-remove]');
    if (!add && !rm) return;
    const refs = st.doc.legal_refs || [];
    if (rm) { setLawRefs(refs.filter(c => c.id !== rm.dataset.lawRemove)); return; }
    const lib = await lawLibrary();
    const r = lib.get(add.dataset.lawAdd) || law.suggestions.map(s => s.reference).find(x => String(x.id) === add.dataset.lawAdd);
    if (r) setLawRefs([...refs, citeOf(r)]);
  });

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
    ['chat', 'source', 'checks', 'law', 'finals'].forEach(n => { $('tab-' + n).hidden = n !== name; });
    if (name === 'law') openLawTab();
  }
  document.querySelectorAll('[data-tab]').forEach(t => t.addEventListener('click', () => selectTab(t.dataset.tab)));
  $('rail-source').addEventListener('click', () => { showLeft(); selectTab('source'); });
  function showLeft() { $('left-pane').classList.remove('max-lg:hidden'); }
  $('btn-left-toggle').addEventListener('click', () => $('left-pane').classList.toggle('max-lg:hidden'));

  // บทสนทนา: สร้างจากขั้นตอนที่ระบบทำจริง (ไม่ใช่ข้อความจำลอง)
  const avatar = '<div class="w-6 h-6 rounded bg-brand-600 text-white flex items-center justify-center shrink-0 mt-0.5 text-[10px]"><i class="fa-solid fa-file"></i></div>';
  function renderChat() {
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
          <div><p class="font-medium text-slate-900">ร่างเอกสารแล้ว</p>
          <p class="text-slate-600 text-xs mt-0.5">ข้อมูลที่ต้นเรื่องไม่มี ระบบเว้นเป็นช่องสีเหลืองให้กรอก — กดป้าย "ต้องแก้" มุมขวาบนเพื่อไปทีละจุด แล้วตรวจทานข้อเท็จจริงก่อนส่งออก</p></div>
          <button type="button" id="card-open" class="w-full bg-white border-2 border-emerald-500/70 rounded-xl p-3 shadow-sm hover:border-emerald-600 transition flex items-center justify-between gap-2 text-left group">
            <span class="flex items-center gap-3 min-w-0">
              <span class="w-9 h-9 rounded-lg bg-emerald-50 text-emerald-700 flex items-center justify-center shrink-0"><i class="fa-regular fa-file-lines"></i></span>
              <span class="text-xs min-w-0"><span class="text-emerald-700 font-medium">กำลังเปิดอยู่</span><span class="text-slate-400 mx-1">·</span><span class="text-slate-500 font-medium">${DOC_TYPE_LABEL[st.doc.doc_type]}</span>
              <span class="block text-slate-800 font-medium mt-0.5 truncate">${esc(st.doc.subject)}</span></span>
            </span>
            <i class="fa-solid fa-chevron-right text-slate-400 text-xs group-hover:translate-x-0.5 transition"></i>
          </button>
        </div>
      </div>`;
    // แสดงเฉพาะสรุปที่ AI เขียน (สรุปแบบเดิมเป็นแค่บรรทัดที่ตัดมาจากต้นเรื่อง อ่านแล้วไม่ช่วย)
    const summary = aiSummary() ? `
      <div class="flex items-start gap-2.5">${avatar}
        <div class="flex-1 space-y-1 min-w-0"><div class="text-xs font-medium text-slate-500">สรุปต้นเรื่อง <span class="font-normal text-slate-400">· ตรวจกับต้นฉบับเสมอ</span></div>
          <p id="chat-summary" class="text-xs text-slate-700 leading-relaxed bg-white border border-slate-200/80 p-3 rounded-lg font-body whitespace-pre-line">${esc(aiSummary())}</p></div>
      </div>` : '';
    $('tab-chat').innerHTML = user + file + summary + tools + ready;
    $('card-open')?.addEventListener('click', () => $('doc-viewport').scrollTo({ top: 0, behavior: 'smooth' }));
  }

  // ---------- ต้นเรื่อง: ไฟล์จริง (PDF/ภาพ) + ข้อความที่อ่านได้ + ค้นคำ ----------
  const src = { view: 'text', viewer: null, textHits: [], textCur: -1, timer: null };
  function setSourceView(view) {
    src.view = view;
    document.querySelectorAll('[data-sview]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.sview === view)));
    $('source-file').hidden = view !== 'file';
    $('source-pagebar').hidden = view !== 'file';
    $('source-textview').hidden = view !== 'text';
    runSourceSearch();
  }
  document.querySelectorAll('[data-sview]').forEach(b => b.addEventListener('click', () => setSourceView(b.dataset.sview)));
  function sourceNote(text) { $('source-note').textContent = text || ''; $('source-note').hidden = !text; }
  async function loadSourceFile() {
    if (!entry.sourceFileId || !finalsEnabled || !window.GovDocSourceViewer) return false;
    try {
      const info = await api.sourceViewUrl(entry.sourceFileId);
      if (!info.url) return false;                     // Word/ข้อความ: แสดงข้อความที่อ่านได้อย่างเดียว
      $('source-views').hidden = false;
      $('source-open').href = info.url;
      setSourceView('file');
      src.viewer = await window.GovDocSourceViewer.open($('source-file'), info, {
        onPage: (n, total) => { $('source-page').textContent = toThai(n); $('source-pages').textContent = toThai(total); },
      });
      if (!(await src.viewer.probeText())) {
        sourceNote(info.kind === 'pdf' ? 'ไฟล์สแกนไม่มีชั้นข้อความ — ค้นคำได้ในแท็บ "ข้อความที่อ่านได้"' : 'ไฟล์ภาพ — ค้นคำได้ในแท็บ "ข้อความที่อ่านได้"');
      }
      runSourceSearch();
      return true;
    } catch (err) {
      $('source-views').hidden = true;
      setSourceView('text');
      sourceNote('เปิดไฟล์ต้นเรื่องไม่ได้ (' + err.message + ') — แสดงข้อความที่อ่านได้แทน');
      return false;
    }
  }
  $('source-page-prev').addEventListener('click', () => src.viewer?.goPage(src.viewer.page - 1));
  $('source-page-next').addEventListener('click', () => src.viewer?.goPage(src.viewer.page + 1));
  for (const [id, d] of [['source-zoom-in', 1], ['source-zoom-out', -1]]) {
    $(id).addEventListener('click', () => {
      if (!src.viewer) return;
      $('source-zoom').textContent = toThai(Math.round(src.viewer.setZoom(d) * 100)) + '%';   // ไฮไลต์เดิมทาใหม่ตอนเรนเดอร์
    });
  }
  function showHits(cur, total) {
    $('source-hits').textContent = total ? `${toThai(cur + 1)}/${toThai(total)}` : ($('source-search').value.trim() ? 'ไม่พบ' : '');
    $('source-prev').disabled = $('source-next').disabled = total < 2;
  }
  async function runSourceSearch() {
    const q = $('source-search').value.trim();
    if (src.view === 'file' && src.viewer) {
      const n = await src.viewer.search(q);
      showHits(src.viewer.cur, n);
      return n;
    }
    highlightSource();
    return src.textHits.length;
  }
  function stepHit(delta) {
    if (src.view === 'file' && src.viewer) {
      src.viewer.goto(src.viewer.cur + delta).then(() => showHits(src.viewer.cur, src.viewer.hits.length));
      return;
    }
    if (!src.textHits.length) return;
    src.textHits[src.textCur]?.classList.remove('cur');
    src.textCur = (src.textCur + delta + src.textHits.length) % src.textHits.length;
    const m = src.textHits[src.textCur];
    m.classList.add('cur'); m.scrollIntoView({ block: 'center' });
    showHits(src.textCur, src.textHits.length);
  }
  $('source-search').addEventListener('input', () => { clearTimeout(src.timer); src.timer = setTimeout(runSourceSearch, 250); });
  $('source-search').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); stepHit(e.shiftKey ? -1 : 1); } });
  $('source-next').addEventListener('click', () => stepHit(1));
  $('source-prev').addEventListener('click', () => stepHit(-1));

  const aiSummary = () => (entry.context?.summary_by_ai && entry.context.summary) || '';
  function renderSource() {
    $('source-summary').hidden = !aiSummary();
    $('source-summary-text').textContent = aiSummary();
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
    src.textHits = []; src.textCur = -1;
    if (!q) { $('source-text').textContent = text || '(ไม่มีข้อความ)'; showHits(0, 0); return; }
    const parts = text.split(q);
    $('source-text').innerHTML = parts.map(esc).join(`<mark class="bg-amber-200 text-slate-900 rounded px-0.5">${esc(q)}</mark>`);
    src.textHits = [...$('source-text').querySelectorAll('mark')];
    if (src.textHits.length) stepHit(1); else showHits(0, 0);
  }

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
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeRefine(); closeFact(); $('quick-menu').hidden = true; toggleSettings(false); } });

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
    if (act === 'jump') nextTodo();
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
      const expected = kind === 'pdf' && st.doc.attach_legal_pages !== false ? lawPageCount(st.doc.legal_refs || []) : 0;
      if (expected && blob.legalPages >= expected) toast(`แนบหน้าข้อกฎหมาย ${toThai(blob.legalPages)} หน้าท้าย PDF แล้ว`);
      else if (expected) toast(`แนบหน้าข้อกฎหมายได้ ${toThai(blob.legalPages || 0)} จาก ${toThai(expected)} หน้า — ไฟล์ต้นฉบับบางไฟล์ไม่พบในคลัง`, 'warn');
      st.doc.edit_status = 'saved'; persist();
      snapshot(kind === 'pdf' ? 'ส่งออก PDF' : 'ส่งออก Word');
    } catch (err) { toast('ส่งออกไม่สำเร็จ: ' + err.message, 'error'); }
    finally { btn.disabled = false; btn.innerHTML = html; }
  }
  $('btn-docx').addEventListener('click', (e) => exportAs('docx', e.currentTarget));
  $('btn-pdf').addEventListener('click', (e) => exportAs('pdf', e.currentTarget));

  // ---------- ร่างใหม่จากข้อมูลเพิ่มเติม ----------
  // ร่างใหม่ทั้งฉบับด้วย AI จากต้นเรื่องเดิม (ข้อความที่อ่านจากไฟล์แล้ว ไม่ต้องอ่านไฟล์ซ้ำ)
  // ใช้ทั้งตอนเพิ่มข้อมูล และตอนเปลี่ยนประเภทหนังสือ
  async function redraft({ extra = '', docType = st.doc.doc_type, note = 'ก่อนร่างใหม่' } = {}) {
    const source = entry.context?.raw_text || '';
    const parts = [entry.prompt, source !== entry.prompt ? source : '', extra].filter(Boolean);
    if (!parts.length) throw new Error('ไม่มีต้นเรื่องเดิมให้ร่างใหม่ — พิมพ์ข้อมูลเพิ่มในช่องด้านล่าง');
    const fd = new FormData();
    fd.append('prompt', parts.join('\n\n'));
    fd.append('doc_type', docType);
    fd.append('urgency', st.doc.urgency);
    fd.append('secret', st.doc.secret);
    if (docType === 'internal' && entry.unitKey) fd.append('unit_key', entry.unitKey);
    const res = await api.draft(fd);
    if (!res.document) throw new Error(res.steps.find(s => !s.ok)?.detail || 'ร่างไม่สำเร็จ');
    st.versions.push({ at: new Date().toISOString(), doc: st.doc, note });
    snapshot(note);
    st.undo = []; st.redo = [];
    st.doc = res.document; st.check = res.check;
    // ต้นเรื่องเดิมยังเป็นข้อความที่อ่านจากไฟล์ (คงไว้ ไม่แทนด้วยข้อความที่ส่งไปร่างใหม่)
    entry.steps = res.steps;
    if (!entry.context) entry.context = res.context;
    else if (res.context?.summary_by_ai) entry.context = { ...entry.context, summary: res.context.summary, summary_by_ai: true };
    if (extra) entry.prompt = [entry.prompt, extra].filter(Boolean).join('\n\n');
    renderAll(); renderSource(); renderChat(); persist();
  }

  $('redraft-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const extra = $('redraft-input').value.trim();
    if (!extra) { $('redraft-input').focus(); return; }
    if (!confirm('ร่างใหม่ทั้งฉบับจากต้นเรื่องเดิมรวมกับข้อมูลที่เพิ่ม? (ฉบับปัจจุบันจะเก็บไว้ในประวัติเวอร์ชัน)')) return;
    $('redraft-btn').disabled = true;
    try {
      await redraft({ extra });
      $('redraft-input').value = '';
      toast('ร่างใหม่แล้ว');
    } catch (err) { toast(err.message, 'error'); }
    finally { $('redraft-btn').disabled = false; }
  });

  // เปลี่ยนประเภทหนังสือ → AI ร่างใหม่เป็นประเภทนั้น (โครงสร้างต่างกันมาก แปลงช่องตรง ๆ ไม่ได้ผลดี)
  $('type-select').addEventListener('change', async (e) => {
    const target = e.target.value;
    if (target === st.doc.doc_type) return;
    const label = DOC_TYPE_LABEL[target];
    if (!confirm(`ร่างใหม่เป็น${label}ด้วย AI จากต้นเรื่องเดิม? (ฉบับปัจจุบันเก็บไว้ในประวัติเวอร์ชัน กลับไปใช้ได้)`)) {
      e.target.value = st.doc.doc_type; return;
    }
    e.target.disabled = true;
    toast(`กำลังร่างใหม่เป็น${label}... อาจใช้เวลาราว ๑ นาที`);
    try {
      await redraft({ docType: target, note: `ก่อนเปลี่ยนเป็น${label}` });
      toast(`เปลี่ยนเป็น${label}แล้ว`);
    } catch (err) {
      e.target.value = st.doc.doc_type;
      toast(err.message, 'error');
    } finally { e.target.disabled = false; }
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

  // แถบเครื่องมือแถวเดียว: ไม่พอที่ก็ย่อเป็นขั้น
  // ๑ ปุ่มย่อหน้า/สถานะบันทึก + ช่องหน่วยแคบลง → ๒ เลิกทำ/ทำซ้ำ (ยังใช้ Ctrl+Z/Y ได้) → ๓ ข้อความในป้ายสถานะ
  // → ๔ ป้ายปุ่ม (เสนอขั้นถัดไป ตั้งค่าเอกสาร ชุดเสนอ) → ๕ คำว่า Word/PDF
  function fitToolbar() {
    const bar = $('toolbar');
    for (const level of ['0', '1', '2', '3', '4', '5']) {
      bar.dataset.compact = level;
      if (bar.scrollWidth <= bar.clientWidth + 1) return;
    }
  }
  new ResizeObserver(fitToolbar).observe($('toolbar'));

  // ---------- เรนเดอร์ทั้งหมด ----------
  function renderAll() {
    sheet.innerHTML = sheetHTML();
    fillFields();
    renderToggles();
    renderChrome();
    renderChecks();
    renderChat();
    renderTodo();
    renderLaw();
    fitSheet();
  }

  api.profile().then(p => {
    const bare = String(p.signatory_name || '').replace(/[()]/g, '').replace(/^(นางสาว|นาง|นาย)\s*/, '').trim().split(/\s+/);
    $('rail-avatar').textContent = (bare[0]?.[0] || '') + (bare[1]?.[0] || '') || '–';
    $('rail-avatar').title = p.signatory_name || '';
  }).catch(() => {});

  renderAll();
  renderSource();
  setSourceView('text');
  // มีไฟล์ต้นเรื่องเก็บไว้: เปิดแท็บต้นเรื่องให้อ่านเทียบกับร่างทันที
  if (entry.sourceFileId && finalsEnabled) { selectTab('source'); loadSourceFile(); }
  // เอกสารเก่าที่ยังไม่เคยตรวจข้อเท็จจริง ตรวจครั้งแรกตอนเปิด
  if (!st.check || (!st.check.facts && sourceText())) runCheck();
})();
