// home.js — หน้าแรก: รับคำสั่ง/ไฟล์ต้นเรื่อง → เรียก /studio/draft → เปิดหน้าแก้ไขเอกสาร
(function () {
  const { api, store, auth, esc, toThai, relTime, toast, URGENCY, SECRET, DOC_TYPE_LABEL } = window.GovDoc;
  const $ = (id) => document.getElementById(id);

  const state = { file: null, urgency: 'normal', secret: 'normal', busy: false };

  // ---------- Sidebar (มือถือ) ----------
  const sidebar = $('sidebar'), backdrop = $('sidebar-backdrop');
  const setSidebar = (open) => { sidebar.classList.toggle('-translate-x-full', !open); backdrop.hidden = !open; };
  $('btn-menu').addEventListener('click', () => setSidebar(true));
  backdrop.addEventListener('click', () => setSidebar(false));

  // ---------- ผู้ใช้ + สถานะระบบ ----------
  // แสดงผู้ใช้บนการ์ดมุมล่างซ้ายและคำทักทาย
  //   โหมด Supabase: บัญชีที่ล็อกอิน (ชื่อในโปรไฟล์ ถ้ายังไม่ตั้งใช้อีเมล)
  //   โหมดเครื่องเดียว: ผู้ลงนามในไฟล์ data/user_profile.json
  function showUser({ name, greeting, initials, subtitle }) {
    $('greeting').textContent = greeting || 'สวัสดีครับ';
    $('user-name').textContent = name;
    $('user-name').title = name;
    $('user-position').textContent = subtitle || '';
    $('user-position').title = subtitle || '';
    $('user-avatar').textContent = initials || '–';
  }
  const personName = (raw) => {
    const full = String(raw || '').replace(/[()]/g, '').trim();
    const bare = full.replace(/^(นางสาว|นาง|นาย|ดร\.|ว่าที่ร้อยตรี)\s*/, '');
    const parts = bare.split(/\s+/).filter(Boolean);
    return { full, first: parts[0] || '', initials: (parts[0]?.[0] || '') + (parts[1]?.[0] || '') };
  };
  auth.ready.then(async (cfg) => {
    store.where().then((w) => { $('recent-where').textContent = 'เก็บ' + w; }).catch(() => {});
    if (cfg.auth_required) {
      $('btn-signout').hidden = false;
      $('btn-signout').addEventListener('click', () => auth.signOut());
      const me = await api.me();
      const person = personName(me.full_name);
      const email = me.email || '';
      const local = email.split('@')[0];
      showUser({
        name: person.full || email || 'ผู้ใช้',
        greeting: person.first ? `สวัสดี คุณ${person.first}` : local ? `สวัสดี ${local}` : '',
        initials: person.initials || local.replace(/[^a-z0-9]/gi, '').slice(0, 2).toUpperCase(),
        subtitle: [person.full ? email : '', me.position, me.organization?.name].filter(Boolean).join(' · '),
      });
    } else {
      const p = await api.profile();
      state.profile = p;
      const person = personName(p.signatory_name);
      showUser({ name: person.full || 'ยังไม่ได้ตั้งค่าผู้ลงนาม', greeting: person.first && `สวัสดี คุณ${person.first}`,
                 initials: person.initials, subtitle: p.signatory_position });
    }
  }).catch((err) => {
    // แสดงสาเหตุบนการ์ดด้วย (ข้อความเด้งหายเร็ว) เช่น "บัญชีนี้ยังไม่ได้ผูกกับหน่วยงาน"
    $('user-name').textContent = 'โหลดข้อมูลผู้ใช้ไม่สำเร็จ';
    $('user-position').textContent = err.message;
    $('user-position').title = err.message;
    toast(err.message, 'error');
  });

  api.health().then((ok) => {
    $('health').innerHTML = ok
      ? '<i class="fa-solid fa-circle-check text-emerald-600"></i><span>พร้อมใช้งาน</span>'
      : '<i class="fa-solid fa-triangle-exclamation text-amber-600"></i><span>เชื่อมต่อระบบไม่ได้</span>';
  }).catch(() => {
    $('health').innerHTML = '<i class="fa-solid fa-triangle-exclamation text-rose-600"></i><span>เชื่อมต่อระบบไม่ได้</span>';
  });

  // ---------- งานล่าสุด ----------
  // แต่ละรายการบอก ประเภท · หน่วย · สถานะ (ต้องแก้ n / ส่งออกแล้ว / ร่าง) · เวลา — เรื่องซ้ำกันก็แยกได้
  // เก็บฉบับทดลองออกจากรายการได้ (ไม่ลบ ดึงกลับได้จาก "ที่เก็บไว้")
  const DOT = { normal: 'bg-sky-500', urgent: 'bg-amber-500', very_urgent: 'bg-rose-500', most_urgent: 'bg-rose-700' };
  const TYPE_SHORT = { internal: 'บันทึก', external: 'ภายนอก' };
  const unitLabels = {};
  let recent = [], showArchived = false;
  async function loadRecent() {
    try { recent = await store.list({ archived: showArchived }); }
    catch (err) { recent = []; toast('โหลดรายการเอกสารไม่สำเร็จ: ' + err.message, 'error'); }
    renderRecent();
    window.dispatchEvent(new CustomEvent('govdoc:recent', { detail: showArchived ? null : recent }));
  }
  function statusOf(e) {
    if (e.todo > 0) return `<span class="text-amber-700 font-medium">ต้องแก้ ${toThai(e.todo)}</span>`;
    if (e.editStatus === 'saved') return '<span class="text-emerald-700">ส่งออกแล้ว</span>';
    return '<span>ร่าง</span>';
  }
  function metaOf(e) {
    return [TYPE_SHORT[e.docType] && `<span>${TYPE_SHORT[e.docType]}</span>`,
      e.unitKey && unitLabels[e.unitKey] && `<span class="truncate">${esc(unitLabels[e.unitKey])}</span>`,
      statusOf(e), `<span class="shrink-0">${esc(relTime(e.updated))}</span>`]
      .filter(Boolean).join('<span class="text-slate-300">·</span>');
  }
  function renderRecent() {
    const q = $('recent-search').value.trim();
    const items = recent.filter(e => !q || (e.title || '').includes(q));
    $('recent-title').textContent = showArchived ? 'ที่เก็บไว้' : 'งานล่าสุด';
    $('btn-archived').innerHTML = showArchived
      ? '<i class="fa-solid fa-arrow-left text-[10px]"></i><span>กลับไปงานล่าสุด</span>'
      : '<i class="fa-solid fa-box-archive text-[10px]"></i><span>ที่เก็บไว้</span>';
    const action = (e) => showArchived
      ? `<button type="button" data-restore="${esc(e.id)}" class="absolute right-1 top-1.5 px-1.5 h-6 rounded-md text-[10px] text-emerald-700 hover:bg-emerald-50 border border-emerald-200 bg-white" title="ดึงกลับมาที่งานล่าสุด"><i class="fa-solid fa-rotate-left mr-0.5"></i>ดึงกลับ</button>`
      : `<button type="button" data-archive="${esc(e.id)}" class="absolute right-1 top-1.5 w-6 h-6 rounded-md text-slate-400 hover:text-slate-700 hover:bg-white opacity-0 group-hover:opacity-100 focus:opacity-100 transition" title="เก็บออกจากรายการ (ไม่ลบ ดึงกลับได้)" aria-label="เก็บ ${esc(e.title || '')}"><i class="fa-solid fa-box-archive text-[11px]"></i></button>`;
    $('recent-list').innerHTML = items.length ? items.slice(0, 15).map(e => `
      <li class="group relative" data-doc="${esc(e.id)}">
        <a href="editor.html?id=${encodeURIComponent(e.id)}" class="block pl-2.5 ${showArchived ? 'pr-16' : 'pr-8'} py-1.5 rounded-lg text-slate-700 hover:bg-slate-100 transition-colors" title="${esc(e.title)}">
          <span class="flex items-center gap-2.5">
            <span class="w-2 h-2 rounded-full shrink-0 ${DOT[e.doc?.urgency] || 'bg-slate-300'}"></span>
            <span class="truncate flex-1">${esc(e.title || 'ไม่มีชื่อเรื่อง')}</span>
          </span>
          <span class="mt-0.5 pl-[1.125rem] flex items-center gap-1 text-[10px] text-slate-400 min-w-0 overflow-hidden whitespace-nowrap">${metaOf(e)}</span>
        </a>
        ${action(e)}
      </li>`).join('')
      : `<li class="px-2.5 py-2 text-slate-400">${q ? 'ไม่พบเอกสาร' : showArchived ? 'ยังไม่มีเอกสารที่เก็บไว้' : 'ยังไม่มีเอกสาร — เริ่มร่างฉบับแรกได้เลย'}</li>`;
  }
  $('recent-search').addEventListener('input', renderRecent);
  $('btn-archived').addEventListener('click', () => { showArchived = !showArchived; loadRecent(); });
  $('recent-list').addEventListener('click', async (ev) => {
    const b = ev.target.closest('[data-archive], [data-restore]');
    if (!b) return;
    ev.preventDefault();
    const id = b.dataset.archive || b.dataset.restore, archiving = !!b.dataset.archive;
    b.disabled = true;
    try {
      await store.setArchived(id, archiving);
      recent = recent.filter(e => e.id !== id);
      renderRecent();
      window.dispatchEvent(new CustomEvent('govdoc:recent', { detail: showArchived ? null : recent }));
      toast(archiving ? 'เก็บแล้ว — ดึงกลับได้ที่ "ที่เก็บไว้"' : 'ดึงกลับมาที่งานล่าสุดแล้ว');
    } catch (err) { b.disabled = false; toast((archiving ? 'เก็บไม่สำเร็จ: ' : 'ดึงกลับไม่สำเร็จ: ') + err.message, 'error'); }
  });
  auth.ready.then(loadRecent);

  // ---------- งานค้าง (หน้าหลัก) ----------
  // จากรายการงานล่าสุด: ยังมีจุดต้องแก้ หรือยังไม่ได้ส่งออก Word/PDF — ฉบับที่เก็บไว้ไม่นับ
  const isPending = (e) => e.todo > 0 || e.editStatus !== 'saved';
  function renderPending(list) {
    if (!list) return;                                    // กำลังดู "ที่เก็บไว้": คงกล่องเดิม
    const items = list.filter(isPending);
    $('pending').hidden = !items.length;
    $('pending-count').textContent = toThai(items.length) + ' ฉบับ';
    $('pending-list').innerHTML = items.slice(0, 4).map(e => `
      <li><a href="editor.html?id=${encodeURIComponent(e.id)}" data-pending="${esc(e.id)}" class="h-full flex flex-col gap-1.5 p-3 rounded-xl border border-slate-200 bg-white hover:border-emerald-300 hover:shadow-sm transition text-left">
        <span class="text-xs font-medium text-slate-800 leading-snug line-clamp-2" title="${esc(e.title)}">${esc(e.title || 'ไม่มีชื่อเรื่อง')}</span>
        <span class="mt-auto flex items-center gap-1.5 text-[11px] text-slate-500 min-w-0">
          ${e.todo > 0
            ? `<span class="shrink-0 px-1.5 py-0.5 rounded-full bg-amber-50 border border-amber-200 text-amber-800 font-medium">ต้องแก้ ${toThai(e.todo)} จุด</span>`
            : '<span class="shrink-0 px-1.5 py-0.5 rounded-full bg-slate-50 border border-slate-200 text-slate-600">ยังไม่ส่งออก</span>'}
          <span class="truncate">${[TYPE_SHORT[e.docType], e.unitKey && unitLabels[e.unitKey]].filter(Boolean).map(esc).join(' · ')}</span>
          <span class="ml-auto shrink-0 text-slate-400">${esc(relTime(e.updated))}</span>
        </span>
      </a></li>`).join('')
      + (items.length > 4 ? `<li class="sm:col-span-2 text-[11px] text-slate-400 px-1">และอีก ${toThai(items.length - 4)} ฉบับในรายการงานล่าสุดด้านซ้าย</li>` : '');
  }
  window.addEventListener('govdoc:recent', (ev) => renderPending(ev.detail));

  // ---------- หน่วยออกหนังสือ (ส่วนราชการ + รูปแบบเลขที่ของบันทึกข้อความ) ----------
  auth.ready.then(() => api.units()).then((units) => {
    units.forEach((u) => { unitLabels[u.key] = u.label; });
    renderRecent();
    if (!showArchived) renderPending(recent);
    $('unit').innerHTML = units.map(u =>
      `<option value="${esc(u.key)}" ${u.is_default ? 'selected' : ''}>${esc(u.label)}</option>`).join('');
    fitSelect($('unit'));
  }).catch(() => { $('unit').innerHTML = '<option value="">หน่วยตั้งต้น</option>'; fitSelect($('unit')); });

  // ---------- ไฟล์แนบ ----------
  const fmtSize = (n) => n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';
  const fileIcon = (name) => /\.pdf$/i.test(name) ? 'fa-file-pdf' : /\.docx$/i.test(name) ? 'fa-file-word' : /\.(png|jpe?g|tiff?)$/i.test(name) ? 'fa-file-image' : 'fa-file-lines';
  function setFile(f) {
    if (f && f.size > 50 * 1024 * 1024) { toast('ไฟล์ใหญ่เกิน 50 MB', 'error'); return; }
    if (f && !/\.(pdf|docx|txt|png|jpe?g|tiff?)$/i.test(f.name)) { toast('รองรับ PDF, DOCX, TXT และรูปภาพ', 'error'); return; }
    state.file = f || null;
    const bar = $('file-bar');
    bar.hidden = !state.file;
    bar.innerHTML = state.file ? `
      <div class="inline-flex items-center gap-2 px-2.5 py-1 rounded-lg bg-emerald-50 border border-emerald-200/80 text-xs text-slate-700 shadow-xs animate-fadeIn">
        <i class="fa-regular ${fileIcon(state.file.name)} text-emerald-600 text-sm"></i>
        <span class="font-medium text-slate-800 max-w-[16rem] truncate">${esc(state.file.name)}</span>
        <span class="text-[10px] text-slate-400">(${fmtSize(state.file.size)})</span>
        <button type="button" id="btn-remove-file" class="text-slate-400 hover:text-rose-500 ml-1 p-0.5" aria-label="ลบไฟล์แนบ"><i class="fa-solid fa-xmark text-xs"></i></button>
      </div>` : '';
    if (state.file) $('btn-remove-file').addEventListener('click', () => { $('file-input').value = ''; setFile(null); });
    syncExamples();
  }
  $('btn-attach').addEventListener('click', () => $('file-input').click());
  $('file-input').addEventListener('change', (e) => setFile(e.target.files[0]));

  const form = $('prompt-form');
  let dragDepth = 0;
  form.addEventListener('dragenter', (e) => { e.preventDefault(); dragDepth++; $('drop-hint').hidden = false; });
  form.addEventListener('dragover', (e) => e.preventDefault());
  form.addEventListener('dragleave', () => { if (--dragDepth <= 0) { dragDepth = 0; $('drop-hint').hidden = true; } });
  form.addEventListener('drop', (e) => {
    e.preventDefault(); dragDepth = 0; $('drop-hint').hidden = true;
    if (state.busy) return;
    if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
  });

  // ---------- ชั้นความเร็ว / ความลับ ----------
  const URGENCY_DESC = {
    normal: 'ปฏิบัติตามลำดับขั้นตอนงานสารบรรณปกติ',
    urgent: 'ให้เจ้าหน้าที่ปฏิบัติเร็วกว่าปกติ',
    very_urgent: 'ให้เจ้าหน้าที่ปฏิบัติโดยเร็ว',
    most_urgent: 'ให้เจ้าหน้าที่ปฏิบัติในทันทีที่ได้รับหนังสือ',
  };
  const SECRET_DESC = {
    normal: 'เอกสารทั่วไป ไม่มีชั้นความลับ',
    secret: 'หากเปิดเผยอาจเกิดความเสียหายแก่ประโยชน์แห่งรัฐ',
    very_secret: 'หากเปิดเผยจะเกิดความเสียหายอย่างร้ายแรง',
    top_secret: 'หากเปิดเผยจะเกิดความเสียหายอย่างร้ายแรงที่สุด',
  };
  const optionCard = (name, value, meta, desc, checked) => `
    <label class="flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-colors has-[:checked]:border-2 has-[:checked]:border-emerald-600 has-[:checked]:bg-emerald-50/40 border-slate-200 hover:bg-slate-50">
      <input type="radio" name="${name}" value="${value}" ${checked ? 'checked' : ''} class="mt-1 text-emerald-600 focus:ring-emerald-500 border-slate-300">
      <span class="flex-1 min-w-0">
        <span class="flex items-center justify-between gap-2"><span class="text-xs font-semibold text-slate-800">${meta.label}</span>
        <span class="text-[10px] px-1.5 py-0.5 rounded border ${meta.cls}">${meta.label}</span></span>
        <span class="block text-[11px] text-slate-500 mt-0.5 leading-snug">${desc}</span>
      </span>
    </label>`;
  function renderClassifyOptions() {
    $('urgency-options').innerHTML = Object.entries(URGENCY).map(([k, m]) => optionCard('urgency', k, m, URGENCY_DESC[k], k === state.urgency)).join('');
    $('secret-options').innerHTML = Object.entries(SECRET).map(([k, m]) => optionCard('secret', k, m, SECRET_DESC[k], k === state.secret)).join('');
  }
  function renderClassifyBadges() {
    const u = URGENCY[state.urgency], s = SECRET[state.secret];
    $('classify-badges').innerHTML =
      `<span class="px-1.5 py-0.5 rounded text-xs font-semibold border leading-tight ${u.cls}">${u.label}</span>` +
      `<span class="px-1.5 py-0.5 rounded text-xs font-medium border leading-tight ${s.cls}">${state.secret === 'normal' ? 'ไม่มีชั้นลับ' : s.label}</span>`;
  }
  renderClassifyBadges();

  const modals = { classify: $('modal-classify'), panel: $('modal-panel') };
  let lastFocus = null;
  function openModal(m) { lastFocus = document.activeElement; m.hidden = false; m.querySelector('[data-close]')?.focus(); }
  function closeModal(m) { m.hidden = true; lastFocus?.focus?.(); }
  Object.values(modals).forEach((m) => {
    m.addEventListener('click', (e) => { if (e.target === m || e.target.closest('[data-close]')) closeModal(m); });
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') Object.values(modals).forEach((m) => { if (!m.hidden) closeModal(m); });
  });

  $('btn-classify').addEventListener('click', () => { renderClassifyOptions(); openModal(modals.classify); });
  $('btn-classify-save').addEventListener('click', () => {
    state.urgency = document.querySelector('input[name=urgency]:checked')?.value || 'normal';
    state.secret = document.querySelector('input[name=secret]:checked')?.value || 'normal';
    renderClassifyBadges();
    closeModal(modals.classify);
  });

  // ---------- เริ่มร่าง ----------
  // ---------- ความคืบหน้าระหว่างร่าง ----------
  // เซิร์ฟเวอร์ตอบครั้งเดียวตอนจบ จึงเดินขั้นตอนตามเวลาที่วัดได้จริง (อ่านสแกน ๖–๗ หน้า ~๑๖ วิ, ร่าง ~๖–๙ วิ)
  // ขั้นอัปโหลดเป็นของจริง และขั้นสุดท้ายรอผลจริงเสมอ (ไม่แสดงว่าเสร็จก่อนผลมา)
  // เมื่อผลมา แสดงขั้นตอนจริงจากเซิร์ฟเวอร์ (ชื่อ/รายละเอียด/สำเร็จหรือไม่)
  const prog = { plan: [], timer: null, t0: 0, phase0: 0, uploading: false, est: 0 };
  function planSteps(file, upload) {
    const scan = file && /\.(pdf|png|jpe?g|tiff?)$/i.test(file.name);
    const readS = !file ? 1 : scan ? Math.min(40, Math.round(10 + (file.size / 1048576) * 2)) : 2;
    const plan = [];
    if (upload) plan.push({ key: 'upload', label: 'อัปโหลดไฟล์ต้นเรื่อง', real: true });
    plan.push({ key: 'extract', label: file ? (scan ? 'AI อ่านต้นเรื่อง' : 'อ่านไฟล์ต้นเรื่อง') : 'อ่านคำสั่งที่พิมพ์', s: readS });
    plan.push({ key: 'classify', label: 'เลือกประเภทหนังสือ', s: 1 });
    plan.push({ key: 'ai', label: 'AI ร่างหนังสือ', s: 7 });
    plan.push({ key: 'draft', label: 'จัดรูปแบบและตรวจระเบียบงานสารบรรณ', s: 2, last: true });
    return plan;
  }
  const ICON = {
    done: '<i class="fa-solid fa-circle-check text-emerald-600"></i>',
    fail: '<i class="fa-solid fa-circle-xmark text-rose-600"></i>',
    run: '<i class="fa-solid fa-circle-notch fa-spin text-emerald-600"></i>',
    wait: '<i class="fa-regular fa-circle text-slate-300"></i>',
  };
  function stepStates() {
    // ขั้นที่ประมาณเวลา: เดินตามเวลาหลังอัปโหลดเสร็จ ขั้นสุดท้ายค้างไว้ที่ "กำลังทำ"
    let t = (Date.now() - prog.phase0) / 1000, running = false;
    return prog.plan.map((st) => {
      if (st.result) return st.result.ok === false ? 'fail' : 'done';
      if (st.real) return prog.uploading ? (running = true, 'run') : 'done';
      if (running || prog.uploading) return 'wait';
      if (!st.last && t >= st.s) { t -= st.s; return 'done'; }
      running = true;
      return 'run';
    });
  }
  function renderProgress() {
    const states = stepStates();
    $('progress-steps').innerHTML = prog.plan.map((st, i) => {
      const state = states[i], r = st.result;
      return `<li class="flex items-center gap-2.5" data-step="${st.key}" data-state="${state}"><span class="w-4 text-center">${ICON[state]}</span>
        <span class="${state === 'wait' ? 'text-slate-400' : 'text-slate-800 font-medium'}">${esc(r?.label || st.label)}</span>
        ${r?.detail ? `<span class="text-slate-400 text-xs truncate">· ${esc(r.detail)}</span>` : ''}</li>`;
    }).join('');
    const sec = Math.floor((Date.now() - prog.t0) / 1000);
    $('progress-time').textContent = prog.timer ? `ผ่านไป ${toThai(sec)} วินาที · ปกติใช้ราว ${toThai(prog.est)} วินาที` : '';
    const slow = !prog.timer ? '' : sec >= 100 ? 'ใกล้ครบเวลาสูงสุด (๒ นาที) — ถ้ายังไม่สำเร็จ ระบบจะแจ้งให้ทราบ ไม่ต้องกดซ้ำ'
      : sec >= Math.max(60, prog.est * 2) ? 'ใช้เวลานานกว่าปกติ — ระบบอาจกำลังสลับไปใช้ AI สำรอง กรุณารอสักครู่ ไม่ต้องกดซ้ำ' : '';
    $('progress-slow').textContent = slow;
    $('progress-slow').hidden = !slow;
  }
  function startProgress(file, upload) {
    prog.plan = planSteps(file, upload);
    prog.uploading = upload;
    prog.t0 = prog.phase0 = Date.now();
    prog.est = Math.round(prog.plan.reduce((n, st) => n + (st.s || 0), 0) + (upload ? 2 : 0));
    clearInterval(prog.timer);
    prog.timer = setInterval(renderProgress, 500);
    $('progress').hidden = false;
    renderProgress();
  }
  function uploadDone() { prog.uploading = false; prog.phase0 = Date.now(); renderProgress(); }
  // ผลจริงจากเซิร์ฟเวอร์ (ขั้นที่ไม่มีในผล เช่น AI ไม่ได้ตั้งค่า ถือว่าข้าม)
  function finishProgress(steps) {
    clearInterval(prog.timer); prog.timer = null;
    const byKey = Object.fromEntries((steps || []).map(st => [st.key, st]));
    prog.plan = prog.plan.filter(st => st.real || byKey[st.key]).map(st => ({ ...st, result: st.real ? { ok: true } : byKey[st.key] }));
    renderProgress();
  }
  function stopProgress() { clearInterval(prog.timer); prog.timer = null; }

  // ระหว่างร่าง: ล็อกช่องพิมพ์และปุ่มทั้งหมด กันกดซ้ำหรือเปลี่ยนค่ากลางทาง
  function setBusy(on) {
    state.busy = on;
    $('prompt-form').setAttribute('aria-busy', String(on));
    $('prompt').readOnly = on;
    ['btn-submit', 'btn-attach', 'doc-type', 'unit', 'btn-classify'].forEach((id) => { $(id).disabled = on; });
    $('prompt-form').querySelectorAll('[data-example], #btn-remove-file').forEach((b) => { b.disabled = on; });
    $('prompt-form').classList.toggle('opacity-70', on);
  }

  async function openInEditor(payload) {
    try {
      const id = await store.create({ title: payload.doc.subject, ...payload });
      location.href = `editor.html?id=${encodeURIComponent(id)}`;
    } catch (err) { toast('บันทึกเอกสารไม่สำเร็จ: ' + err.message, 'error'); }
  }

  async function submit() {
    if (state.busy) return;
    const prompt = $('prompt').value.trim();
    if (!prompt && !state.file) { $('prompt').focus(); toast('พิมพ์คำสั่งหรือแนบไฟล์ต้นเรื่องก่อน', 'warn'); return; }
    setBusy(true);
    $('error-box').hidden = true;
    const upload = !!state.file && (await auth.serverMode());
    startProgress(state.file, upload);

    const fd = new FormData();
    fd.append('prompt', prompt);
    if ($('doc-type').value) fd.append('doc_type', $('doc-type').value);
    if ($('unit').value) fd.append('unit_key', $('unit').value);
    fd.append('urgency', state.urgency);
    fd.append('secret', state.secret);
    try {
      if (upload) {
        // โหมดเซิร์ฟเวอร์: ส่งไฟล์ตรงเข้า Storage ก่อน แล้วให้ API อ่านจากที่นั่น (รองรับไฟล์ถึง 50 MB)
        fd.append('source_path', await api.uploadSource(state.file));
        fd.append('source_name', state.file.name);
        uploadDone();
      } else if (state.file) {
        fd.append('file', state.file);
      }
      const res = await api.draft(fd);
      finishProgress(res.steps);
      if (!res.document) {
        const failed = res.steps.find(s => !s.ok);
        $('error-box').innerHTML = `<div class="font-semibold mb-1"><i class="fa-solid fa-triangle-exclamation mr-1"></i>ยังไม่สร้างร่าง</div>${esc(failed?.detail || 'อ่านต้นเรื่องไม่สำเร็จ')} — ลองไฟล์อื่น หรือพิมพ์/วางข้อความต้นเรื่องแทน`;
        $('error-box').hidden = false;
        return;
      }
      await openInEditor({
        doc: res.document, context: res.context, classification: res.classification,
        check: res.check, steps: res.steps, prompt, cloudBlocked: res.cloud_ai_blocked,
        sourceName: state.file?.name || null, sourceFileId: res.source_file_id || null, unitKey: $('unit').value || null,
      });
    } catch (err) {
      stopProgress();
      $('progress').hidden = true;
      $('error-box').innerHTML = `<i class="fa-solid fa-triangle-exclamation mr-1"></i>${esc(err.message)}`;
      $('error-box').hidden = false;
    } finally {
      setBusy(false);
    }
  }
  form.addEventListener('submit', (e) => { e.preventDefault(); submit(); });
  $('prompt').addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submit(); } });

  $('btn-new').addEventListener('click', () => {
    $('prompt').value = ''; $('file-input').value = ''; setFile(null);
    if (state.busy) return;
    $('progress').hidden = true; $('error-box').hidden = true; setSidebar(false); syncExamples(); $('prompt').focus();
  });
  // ---------- ช่องเลือกในแถบเครื่องมือ: กว้างเท่าตัวเลือกที่เลือกอยู่ (select ปกติกว้างเท่าตัวเลือกที่ยาวที่สุด) ----------
  const measurer = document.createElement('span');
  measurer.style.cssText = 'position:absolute;visibility:hidden;white-space:pre;left:-9999px';
  document.body.appendChild(measurer);
  function fitSelect(sel) {
    const opt = sel.options[sel.selectedIndex];
    if (!opt) return;
    measurer.style.font = getComputedStyle(sel).font;
    measurer.textContent = opt.textContent;
    sel.style.width = Math.ceil(measurer.getBoundingClientRect().width) + 46 + 'px';   // + ระยะขวาและลูกศรของ select
  }
  ['doc-type', 'unit'].forEach((id) => $(id).addEventListener('change', () => fitSelect($(id))));
  // วัดใหม่เมื่อฟอนต์เว็บโหลดเสร็จ (วัดก่อนฟอนต์มาจะได้ความกว้างของฟอนต์สำรอง ข้อความถูกตัด)
  const refitSelects = () => { fitSelect($('doc-type')); fitSelect($('unit')); };
  document.fonts?.ready.then(refitSelects);
  document.fonts?.addEventListener?.('loadingdone', refitSelects);
  window.addEventListener('load', refitSelects);
  fitSelect($('doc-type'));

  // ---------- ตัวอย่างคำสั่ง (ในช่องพิมพ์ แสดงเฉพาะตอนยังว่าง) ----------
  const EXAMPLES = [
    { label: 'สรุปไฟล์แนบแล้วร่างบันทึกเสนอ', type: 'internal', attach: true,
      text: 'ร่างบันทึกข้อความเสนอตามหนังสือที่แนบ สรุปข้อเท็จจริงและข้อพิจารณา เพื่อเสนอผู้บังคับบัญชาพิจารณา' },
    { label: 'ขออนุมัติเป็นเจ้าภาพร่วมจัดกีฬา', type: 'internal',
      text: 'ร่างบันทึกข้อความขออนุมัติเป็นเจ้าภาพร่วมจัดการแข่งขันกีฬาเยาวชน และขอใช้ลานกีฬากลาง ระหว่างวันที่ ๑๐ – ๑๒ มกราคม ๒๕๗๐ ตามหนังสือของสมาคมกีฬาที่ขอความร่วมมือมา' },
    { label: 'ตอบหนังสือขอใช้สถานที่', type: 'external',
      text: 'ร่างหนังสือภายนอกตอบสมาคมกีฬา แจ้งอนุญาตให้ใช้ลานกีฬากลาง ในวันที่ ๑๕ มกราคม ๒๕๗๐ เวลา ๐๘.๐๐ – ๑๖.๐๐ น. โดยให้ประสานเจ้าหน้าที่สนามล่วงหน้า' },
  ];
  $('examples').innerHTML = EXAMPLES.map((x, i) => `
    <button type="button" data-example="${i}" class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-slate-200 bg-slate-50 hover:bg-emerald-50 hover:border-emerald-300 text-xs text-slate-600 hover:text-emerald-800 transition">
      <i class="fa-regular ${x.attach ? 'fa-file-lines' : 'fa-lightbulb'} text-emerald-600"></i>${esc(x.label)}</button>`).join('');
  $('examples').addEventListener('click', (e) => {
    const b = e.target.closest('[data-example]');
    if (!b) return;
    const x = EXAMPLES[+b.dataset.example];
    $('prompt').value = x.text;
    $('doc-type').value = x.type;
    fitSelect($('doc-type'));
    syncExamples();
    $('prompt').focus();
    if (x.attach && !state.file) toast('แนบไฟล์ต้นเรื่องด้วยปุ่ม "แนบไฟล์" หรือลากไฟล์มาวางในกล่องนี้');
  });
  function syncExamples() { $('examples').hidden = !!($('prompt').value.trim() || state.file); }
  $('prompt').addEventListener('input', syncExamples);

  // ---------- เอกสารเปล่า / แม่แบบ ----------
  async function openBlank(type) {
    try {
      const doc = await api.blank(type, $('unit').value);
      doc.urgency = state.urgency; doc.secret = state.secret;
      const check = await api.check(doc);
      await openInEditor({ doc, check, unitKey: $('unit').value || null, steps: [{ key: 'blank', label: `เปิด${DOC_TYPE_LABEL[type]}เปล่า`, ok: true, detail: 'ข้อมูลหน่วยงานจากโปรไฟล์' }] });
    } catch (err) { toast(err.message, 'error'); }
  }
  document.querySelectorAll('[data-blank]').forEach(b => b.addEventListener('click', () => openBlank(b.dataset.blank)));

  async function openTemplate(id, title) {
    try {
      const doc = await api.template(id);
      const check = await api.check(doc);
      await openInEditor({ doc, check, steps: [{ key: 'template', label: 'เปิดจากคลังแม่แบบ', ok: true, detail: title }] });
    } catch (err) { toast(err.message, 'error'); }
  }

  const panels = {
    async templates(body) {
      const list = await api.templates();
      const groups = {};
      list.forEach(t => (groups[t.category] ||= []).push(t));
      body.innerHTML = Object.entries(groups).map(([cat, items]) => `
        <h4 class="text-[11px] font-semibold text-slate-400 tracking-wider mt-3 first:mt-0 mb-1.5">${esc(cat)}</h4>
        <ul class="space-y-1">${items.map(t => `
          <li><button type="button" data-template="${esc(t.id)}" class="w-full text-left flex items-center gap-3 px-3 py-2 rounded-lg border border-transparent hover:border-emerald-200 hover:bg-emerald-50/60 text-xs">
            <span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 shrink-0">${DOC_TYPE_LABEL[t.doc_type]}</span>
            <span class="text-slate-800 flex-1">${esc(t.title)}</span><i class="fa-solid fa-chevron-right text-[10px] text-slate-300"></i>
          </button></li>`).join('')}</ul>`).join('');
      body.querySelectorAll('[data-template]').forEach(b => b.addEventListener('click', () => openTemplate(b.dataset.template, b.textContent.trim())));
    },
    async legal(body) {
      const server = await auth.serverMode();
      body.innerHTML = `
        ${server ? `
        <div id="law-import" class="mb-4 p-3.5 rounded-xl border border-emerald-200 bg-emerald-50/50 text-xs space-y-2">
          <div class="flex items-center justify-between gap-3">
            <div><div class="font-semibold text-slate-800"><i class="fa-solid fa-file-import text-emerald-700 mr-1"></i>นำเข้าไฟล์กฎหมาย/ระเบียบ (PDF สแกนได้)</div>
              <div class="text-slate-500 mt-0.5">AI อ่านทีละหน้า แยกเป็นข้อ/มาตรา พร้อมเลขหน้า แล้วให้คุณตรวจและยืนยัน</div></div>
            <input id="law-file" type="file" accept=".pdf,application/pdf" class="sr-only">
            <button type="button" id="law-pick" class="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-brand-700 text-white font-medium"><i class="fa-solid fa-upload"></i>เลือกไฟล์</button>
          </div>
          <div id="law-progress" class="hidden">
            <div class="flex items-center justify-between text-slate-600"><span id="law-status"></span><span id="law-count" class="tabular-nums whitespace-nowrap shrink-0 pl-2"></span></div>
            <div class="mt-1 h-1.5 rounded-full bg-emerald-100 overflow-hidden"><div id="law-bar" class="h-full bg-emerald-500 transition-all" style="width:0%"></div></div>
          </div>
        </div>` : '<p class="mb-3 text-xs text-amber-700">นำเข้าไฟล์กฎหมายได้เมื่อเข้าสู่ระบบและเก็บข้อมูลบนเซิร์ฟเวอร์</p>'}
        <p class="text-xs text-slate-500 mb-3">ระบบใส่ข้อกฎหมายลงในร่างเฉพาะรายการที่ <b>ยืนยันแล้ว</b> เท่านั้น — ตรวจข้อความกับไฟล์จริงก่อนกดยืนยัน</p>
        <div id="law-list" class="space-y-4"><p class="text-xs text-slate-400"><i class="fa-solid fa-circle-notch fa-spin mr-1"></i>กำลังโหลด...</p></div>`;
      await renderLawList(body);
      if (!server) return;
      $('law-pick').addEventListener('click', () => $('law-file').click());
      $('law-file').addEventListener('change', async (e) => {
        const file = e.target.files[0];
        e.target.value = '';
        if (!file) return;
        if (!/\.pdf$/i.test(file.name)) { toast('รับเฉพาะไฟล์ PDF', 'error'); return; }
        try { await importLaw(file); await renderLawList(body); }
        catch (err) { lawStatus('นำเข้าไม่สำเร็จ: ' + err.message, null, true); }
        finally { $('law-pick').disabled = false; }
      });
    },
    async profile(body) {
      const p = state.profile || await api.profile();
      const row = (k, v) => `<div class="grid grid-cols-3 gap-3 py-2 border-b border-slate-100 last:border-0 text-xs"><dt class="text-slate-500">${k}</dt><dd class="col-span-2 text-slate-800 font-body">${esc(v || '—')}</dd></div>`;
      body.innerHTML = `<dl>${row('ส่วนราชการ', p.department_full)}${row('รหัสหนังสือออก', p.doc_origin_code)}${row('ผู้ลงนาม', p.signatory_name)}${row('ตำแหน่ง', p.signatory_position)}${row('ส่วนราชการเจ้าของเรื่อง', p.contact_dept)}${row('โทร / โทรสาร', [p.contact_tel, p.contact_fax].filter(Boolean).join(' / '))}${row('อีเมล', p.contact_email)}</dl>
        <p class="text-[11px] text-slate-400 mt-3">ข้อมูลนี้ใช้เติมหัวหนังสือและผู้ลงนามในร่างทุกฉบับ (ไฟล์ data/user_profile.json)</p>`;
    },
  };
  // ---------- คลังกฎหมาย: นำเข้าไฟล์ + ตรวจยืนยันรายข้อ ----------
  function lawStatus(text, ratio, error) {
    $('law-progress').classList.remove('hidden');
    $('law-status').textContent = text;
    $('law-status').className = error ? 'text-rose-700' : 'text-slate-600';
    if (ratio != null) $('law-bar').style.width = Math.round(ratio * 100) + '%';
  }
  // เรนเดอร์หน้าเป็นภาพ JPEG กว้างราว 1400 px (อ่านตัวอักษรไทยได้ชัด ไฟล์ไม่ใหญ่)
  async function pageJpeg(pdf, n) {
    const page = await pdf.getPage(n);
    const base = page.getViewport({ scale: 1 });
    const vp = page.getViewport({ scale: Math.min(3, 1400 / base.width) });
    const canvas = document.createElement('canvas');
    canvas.width = Math.floor(vp.width); canvas.height = Math.floor(vp.height);
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height);
    await page.render({ canvasContext: ctx, viewport: vp }).promise;
    return new Promise((res) => canvas.toBlob(res, 'image/jpeg', 0.85));
  }
  async function importLaw(file) {
    $('law-pick').disabled = true;
    $('law-count').textContent = '';
    lawStatus('อัปโหลดไฟล์...', 0.02);
    const source = await api.legalImport.upload(file);
    const lib = await window.GovDocSourceViewer.loadPdfJs();
    const pdf = await lib.getDocument({ data: await file.arrayBuffer() }).promise;
    const total = pdf.numPages, texts = new Array(total).fill('');
    let done = 0, next = 1;
    lawStatus('AI กำลังอ่านทีละหน้า...', 0.05);
    // อ่านพร้อมกัน ๓ หน้า (หน้าละหนึ่งคำขอ ไม่ชนเพดานเวลาของเซิร์ฟเวอร์) — หน้าที่พลาดลองใหม่หนึ่งครั้ง
    async function worker() {
      while (next <= total) {
        const n = next++;
        const blob = await pageJpeg(pdf, n);
        let out;
        try { out = await api.legalImport.ocrPage(blob, n); }
        catch (_) { out = await api.legalImport.ocrPage(blob, n); }
        texts[n - 1] = out.text;
        done++;
        $('law-count').textContent = `${toThai(done)}/${toThai(total)} หน้า`;
        lawStatus(`AI กำลังอ่านทีละหน้า... (หน้าละราว ๕–๑๐ วินาที)`, 0.05 + 0.85 * done / total);
      }
    }
    await Promise.all([worker(), worker(), worker()]);
    lawStatus('แยกเป็นข้อ/มาตรา...', 0.95);
    const res = await api.legalImport.sections(source.id, texts);
    lawStatus(`เสร็จแล้ว: "${res.title}" แยกได้ ${toThai(res.references.length)} รายการ — ตรวจแล้วกดยืนยันด้านล่าง`, 1);
    toast('นำเข้าแล้ว — ตรวจข้อความกับไฟล์จริงก่อนกดยืนยัน');
    lawOpen.add(source.id);
  }
  const lawOpen = new Set();                 // กลุ่มที่กางไว้ (ไฟล์ที่เพิ่งนำเข้ากางให้อัตโนมัติ)
  const lawEdit = { ref: null, source: null, split: null };   // รายการ/ฉบับที่กำลังแก้ / รายการที่กำลังแยกข้อย่อย
  const lawNum = (r) => parseFloat(String(r.section || '').replace(/[๐-๙]/g, d => '๐๑๒๓๔๕๖๗๘๙'.indexOf(d)).replace(/[^\d.]/g, '')) || 9999;
  function lawItemHTML(r) {
    if (lawEdit.ref === String(r.id)) {
      const rows = Math.min(16, Math.max(5, String(r.quote || '').split('\n').length + 1));
      return `<li class="px-3.5 py-3 text-xs bg-amber-50/40 space-y-2" data-law-ref="${esc(r.id)}" data-law-editing>
        <label class="block"><span class="text-[11px] font-medium text-slate-600">หัวข้อ (ใช้เรียกและแสดงในบันทึก เช่น "ข้อ ๑๔" หรือชื่อที่ตั้งเอง)</span>
          <input data-law-f="section" value="${esc(r.section || '')}" maxlength="200" class="mt-1 w-full px-2.5 py-1.5 border border-slate-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-emerald-500"></label>
        <label class="block"><span class="text-[11px] font-medium text-slate-600">เนื้อหา (แก้คำที่ AI อ่านผิด — เทียบกับไฟล์จริง${r.page_from ? ` หน้า ${toThai(r.page_from)}${r.page_to && r.page_to !== r.page_from ? '–' + toThai(r.page_to) : ''}` : ''})</span>
          <textarea data-law-f="quote" rows="${rows}" class="mt-1 w-full px-2.5 py-1.5 border border-slate-300 rounded-lg font-body text-[13px] leading-relaxed focus:outline-none focus:ring-1 focus:ring-emerald-500">${esc(r.quote || '')}</textarea></label>
        <div class="flex flex-wrap items-center gap-2">
          <button type="button" data-law-save="${esc(r.id)}" class="px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-brand-700 text-white font-medium">บันทึก</button>
          ${r.verified ? '' : `<button type="button" data-law-save="${esc(r.id)}" data-and-verify="1" class="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-medium">บันทึกและยืนยัน</button>`}
          <button type="button" data-law-cancel class="px-3 py-1.5 rounded-lg text-slate-600 hover:bg-slate-100">ยกเลิก</button>
          ${r.source_id ? `<button type="button" data-law-file="${esc(r.source_id)}" class="ml-auto px-2 py-1 rounded-md text-[11px] text-slate-600 hover:bg-slate-200"><i class="fa-regular fa-file-pdf mr-1"></i>เปิดไฟล์จริง</button>` : ''}
        </div>
      </li>`;
    }
    return `<li class="px-3.5 py-2.5 text-xs" data-law-ref="${esc(r.id)}">
      <div class="flex items-start gap-2">
        <div class="flex-1 min-w-0">
          <div class="font-semibold text-slate-800">${esc(r.section || '')}${r.page_from ? `<span class="font-normal text-slate-400"> · หน้า ${toThai(r.page_from)}${r.page_to && r.page_to !== r.page_from ? '–' + toThai(r.page_to) : ''}</span>` : ''}</div>
          ${r.chapter ? `<div class="text-[11px] text-slate-500">${esc(r.chapter)}</div>` : ''}
          <p class="mt-1 text-slate-600 font-body leading-relaxed whitespace-pre-line line-clamp-3 cursor-pointer" data-law-expand title="กดเพื่อดูทั้งหมด">${esc(r.quote || '')}</p>
        </div>
        <div class="shrink-0 flex items-center gap-1">
          ${r.source_id ? `<button type="button" data-law-split="${esc(r.id)}" class="px-2 py-0.5 rounded-full border border-slate-300 bg-white text-[10px] text-slate-600 hover:border-slate-400" title="เลือกเฉพาะบางข้อจากรายการนี้ เป็นรายการใหม่"><i class="fa-solid fa-scissors mr-0.5"></i>แยกข้อย่อย</button>` : ''}
          <button type="button" data-law-edit="${esc(r.id)}" class="px-2 py-0.5 rounded-full border border-slate-300 bg-white text-[10px] text-slate-600 hover:border-slate-400" title="แก้หัวข้อหรือเนื้อหา"><i class="fa-solid fa-pen mr-0.5"></i>แก้ไข</button>
          <button type="button" data-law-verify="${esc(r.id)}" data-on="${r.verified ? '1' : ''}" class="px-2 py-0.5 rounded-full border text-[10px] ${r.verified ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-white text-slate-600 border-slate-300 hover:border-emerald-400'}">${r.verified ? '<i class="fa-solid fa-check mr-0.5"></i>ยืนยันแล้ว' : 'ยืนยัน'}</button>
        </div>
      </div>
    </li>`;
  }
  // ฟอร์มแยกข้อย่อย: เริ่มจากเนื้อหาและหน้าของรายการเดิม ให้ตัดเหลือเฉพาะข้อที่ใช้
  function lawSplitHTML(r) {
    const rows = Math.min(16, Math.max(6, String(r.quote || '').split('\n').length + 1));
    const num = (name, v) => `<input data-law-f="${name}" type="number" min="1" value="${v || ''}" class="w-16 px-2 py-1 border border-slate-300 rounded-lg text-center focus:outline-none focus:ring-1 focus:ring-emerald-500">`;
    return `<li class="px-3.5 py-3 text-xs bg-emerald-50/50 space-y-2" data-law-split-form="${esc(r.id)}">
      <div class="font-medium text-emerald-800"><i class="fa-solid fa-scissors mr-1"></i>แยกข้อย่อยจาก "${esc(r.section || '')}" — ได้รายการใหม่ (รายการเดิมยังอยู่)</div>
      <label class="block"><span class="text-[11px] font-medium text-slate-600">หัวข้อ (เช่น "ข้อ ๒")</span>
        <input data-law-f="section" maxlength="200" placeholder="ข้อ ..." class="mt-1 w-full px-2.5 py-1.5 border border-slate-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-emerald-500"></label>
      <label class="block"><span class="text-[11px] font-medium text-slate-600">เนื้อหา (ลบส่วนที่ไม่ใช้ เหลือเฉพาะข้อนี้)</span>
        <textarea data-law-f="quote" rows="${rows}" class="mt-1 w-full px-2.5 py-1.5 border border-slate-300 rounded-lg font-body text-[13px] leading-relaxed focus:outline-none focus:ring-1 focus:ring-emerald-500">${esc(r.quote || '')}</textarea></label>
      <div class="flex flex-wrap items-center gap-2 text-[11px] text-slate-600">
        <span>หน้าที่จะแนบท้าย PDF:</span> ${num('page_from', r.page_from)} <span>ถึง</span> ${num('page_to', r.page_to || r.page_from)}
        <button type="button" data-law-file="${esc(r.source_id)}" class="ml-auto px-2 py-1 rounded-md text-slate-600 hover:bg-slate-200"><i class="fa-regular fa-file-pdf mr-1"></i>เปิดไฟล์จริง</button>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <button type="button" data-law-split-save="${esc(r.id)}" class="px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-brand-700 text-white font-medium">บันทึก</button>
        <button type="button" data-law-split-save="${esc(r.id)}" data-and-verify="1" class="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-medium">บันทึกและยืนยัน</button>
        <button type="button" data-law-cancel class="px-3 py-1.5 rounded-lg text-slate-600 hover:bg-slate-100">ยกเลิก</button>
      </div>
    </li>`;
  }
  async function renderLawList(body) {
    const list = body.querySelector('#law-list');
    const { references } = await api.legal();
    if (!references.length) { list.innerHTML = '<p class="text-xs text-slate-400">ยังไม่มีรายการในคลังกฎหมาย</p>'; return; }
    const groups = new Map();
    for (const r of references) {
      const key = r.source_id || 'manual';
      if (!groups.has(key)) groups.set(key, { title: r.source_id ? r.title : 'รายการที่เพิ่มเอง', items: [] });
      groups.get(key).items.push(r);
    }
    list.innerHTML = [...groups.entries()].map(([key, g]) => {
      g.items.sort((a, b) => (a.page_from || 0) - (b.page_from || 0) || lawNum(a) - lawNum(b));
      const ok = g.items.filter(r => r.verified).length;
      const open = lawOpen.has(key) || groups.size === 1;
      const renaming = lawEdit.source === key;
      return `<section class="rounded-xl border border-slate-200" data-law-group="${esc(key)}">
        <header class="px-3.5 py-2.5 flex items-center gap-2 bg-slate-50/70 rounded-t-xl">
          ${renaming ? `
          <div class="flex-1 min-w-0 flex items-center gap-2">
            <label class="sr-only" for="law-rename">ชื่อฉบับ</label>
            <input id="law-rename" value="${esc(g.title)}" maxlength="300" class="flex-1 min-w-0 px-2.5 py-1 text-xs border border-slate-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-emerald-500">
            <button type="button" data-law-rename-save="${esc(key)}" class="shrink-0 px-2.5 py-1 rounded-md text-[11px] bg-slate-900 text-white">บันทึก</button>
            <button type="button" data-law-cancel class="shrink-0 px-2 py-1 rounded-md text-[11px] text-slate-600 hover:bg-slate-200">ยกเลิก</button>
          </div>` : `
          <button type="button" data-law-toggle="${esc(key)}" class="flex-1 min-w-0 text-left">
            <div class="text-xs font-semibold text-slate-800 truncate" title="${esc(g.title)}"><i class="fa-solid fa-chevron-${open ? 'down' : 'right'} text-[9px] text-slate-400 mr-1.5"></i>${esc(g.title)}</div>
            <div class="text-[11px] text-slate-500 mt-0.5 pl-4">${toThai(g.items.length)} รายการ · ยืนยันแล้ว ${toThai(ok)}</div>
          </button>
          ${key !== 'manual' ? `<button type="button" data-law-rename="${esc(key)}" class="shrink-0 w-7 h-7 rounded-md text-slate-500 hover:bg-slate-200" title="เปลี่ยนชื่อฉบับ" aria-label="เปลี่ยนชื่อฉบับ"><i class="fa-solid fa-pen text-[11px]"></i></button>
          <button type="button" data-law-file="${esc(key)}" class="shrink-0 px-2 py-1 rounded-md text-[11px] text-slate-600 hover:bg-slate-200" title="เปิดไฟล์จริง"><i class="fa-regular fa-file-pdf mr-1"></i>ไฟล์</button>` : ''}
          ${ok < g.items.length ? `<button type="button" data-law-verify-all="${esc(key)}" class="shrink-0 px-2 py-1 rounded-md text-[11px] bg-emerald-600 hover:bg-emerald-700 text-white">ยืนยันทั้งหมด</button>` : ''}`}
        </header>
        <ul class="${open || g.items.some(r => lawEdit.ref === String(r.id) || lawEdit.split === String(r.id)) ? '' : 'hidden'} divide-y divide-slate-100">${g.items.map(r => lawItemHTML(r) + (lawEdit.split === String(r.id) ? lawSplitHTML(r) : '')).join('')}</ul>
      </section>`;
    }).join('');
    list.querySelector('[data-law-editing] [data-law-f="quote"]')?.focus();
    list.querySelector('[data-law-split-form] [data-law-f="section"]')?.focus();
    list.querySelector('#law-rename')?.select();
    list.onclick = async (e) => {
      const t = e.target.closest('[data-law-toggle]');
      if (t) { const k = t.dataset.lawToggle; lawOpen.has(k) ? lawOpen.delete(k) : lawOpen.add(k); return renderLawList(body); }
      const x = e.target.closest('[data-law-expand]');
      if (x) { x.classList.toggle('line-clamp-3'); return; }
      const f = e.target.closest('[data-law-file]');
      if (f) { try { window.open(await api.legalImport.fileUrl(f.dataset.lawFile), '_blank', 'noopener'); } catch (err) { toast(err.message, 'error'); } return; }
      if (e.target.closest('[data-law-cancel]')) { lawEdit.ref = lawEdit.source = lawEdit.split = null; return renderLawList(body); }
      const sp = e.target.closest('[data-law-split]');
      if (sp) { lawEdit.split = sp.dataset.lawSplit; lawEdit.ref = lawEdit.source = null; return renderLawList(body); }
      const ss = e.target.closest('[data-law-split-save]');
      if (ss) {
        const form = ss.closest('[data-law-split-form]');
        const val = (n) => form.querySelector(`[data-law-f="${n}"]`).value.trim();
        const fields = { section: val('section'), quote: val('quote'), page_from: Number(val('page_from')), page_to: Number(val('page_to')) || null };
        if (!fields.section || !fields.quote) { toast('ใส่หัวข้อและเนื้อหาก่อน', 'warn'); return; }
        if (!(fields.page_from >= 1)) { toast('ใส่หน้าที่จะแนบ', 'warn'); return; }
        if (ss.dataset.andVerify) fields.verified = true;
        const parent = references.find(x => String(x.id) === ss.dataset.lawSplitSave);
        ss.disabled = true;
        try {
          await api.legalImport.addSection(parent.source_id, fields);
          lawEdit.split = null; lawOpen.add(parent.source_id);
          toast(`เพิ่ม "${fields.section}" แล้ว${fields.verified ? ' (ยืนยันแล้ว)' : ''}`);
          await renderLawList(body);
        } catch (err) { ss.disabled = false; toast('เพิ่มไม่สำเร็จ: ' + err.message, 'error'); }
        return;
      }
      const ed = e.target.closest('[data-law-edit]');
      if (ed) { lawEdit.ref = ed.dataset.lawEdit; lawEdit.source = null; return renderLawList(body); }
      const rn = e.target.closest('[data-law-rename]');
      if (rn) { lawEdit.source = rn.dataset.lawRename; lawEdit.ref = null; return renderLawList(body); }
      const rs = e.target.closest('[data-law-rename-save]');
      if (rs) {
        const title = list.querySelector('#law-rename').value.trim();
        if (!title) { toast('ใส่ชื่อฉบับก่อน', 'warn'); return; }
        try { await api.legalImport.rename(rs.dataset.lawRenameSave, title); lawEdit.source = null; toast('เปลี่ยนชื่อฉบับแล้ว'); await renderLawList(body); }
        catch (err) { toast('เปลี่ยนชื่อไม่สำเร็จ: ' + err.message, 'error'); }
        return;
      }
      const sv = e.target.closest('[data-law-save]');
      if (sv) {
        const li = sv.closest('[data-law-ref]');
        const section = li.querySelector('[data-law-f="section"]').value.trim();
        const quote = li.querySelector('[data-law-f="quote"]').value.trim();
        if (!section || !quote) { toast('หัวข้อและเนื้อหาว่างไม่ได้', 'warn'); return; }
        const fields = { section, quote };
        if (sv.dataset.andVerify) fields.verified = true;
        sv.disabled = true;
        try { await api.legalEdit(sv.dataset.lawSave, fields); lawEdit.ref = null; toast(fields.verified ? 'บันทึกและยืนยันแล้ว' : 'บันทึกแล้ว'); await renderLawList(body); }
        catch (err) { sv.disabled = false; toast('บันทึกไม่สำเร็จ: ' + err.message, 'error'); }
        return;
      }
      const v = e.target.closest('[data-law-verify]');
      const all = e.target.closest('[data-law-verify-all]');
      if (!v && !all) return;
      const ids = v ? [v.dataset.lawVerify]
        : [...list.querySelectorAll(`[data-law-group="${CSS.escape(all.dataset.lawVerifyAll)}"] [data-law-verify]:not([data-on="1"])`)].map(b => b.dataset.lawVerify);
      const on = v ? !v.dataset.on : true;
      if (all && !confirm(`ยืนยัน ${toThai(ids.length)} รายการ? ควรตรวจข้อความกับไฟล์จริงแล้ว`)) return;
      try {
        if (await auth.serverMode()) await api.legalImport.verify(ids, on);
        else throw new Error('ยืนยันได้เมื่อเข้าสู่ระบบ');
        await renderLawList(body);
      } catch (err) { toast(err.message, 'error'); }
    };
  }

  const PANEL_TITLE = { templates: 'คลังแม่แบบหนังสือราชการ', legal: 'คลังข้อกฎหมาย / ระเบียบ', profile: 'ข้อมูลหน่วยงานและผู้ลงนาม' };
  document.querySelectorAll('[data-open]').forEach(b => b.addEventListener('click', async () => {
    const key = b.dataset.open;
    setSidebar(false);
    $('panel-title').textContent = PANEL_TITLE[key];
    $('panel-body').innerHTML = '<p class="text-xs text-slate-400"><i class="fa-solid fa-circle-notch fa-spin mr-1"></i>กำลังโหลด...</p>';
    openModal(modals.panel);
    try { await panels[key]($('panel-body')); }
    catch (err) { $('panel-body').innerHTML = `<p class="text-xs text-rose-700">${esc(err.message)}</p>`; }
  }));

  $('prompt').focus();
})();
