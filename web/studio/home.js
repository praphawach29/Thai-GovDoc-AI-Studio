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
  const STEPS = [
    { key: 'extract', label: 'อ่านต้นเรื่อง' },
    { key: 'classify', label: 'จำแนกชนิดหนังสือ' },
    { key: 'draft', label: 'ร่างหนังสือตามโครงสร้าง ๓ ภาค' },
  ];
  function renderProgress(done = [], running = true) {
    const doneMap = Object.fromEntries(done.map(s => [s.key, s]));
    $('progress-steps').innerHTML = STEPS.map((s, i) => {
      const d = doneMap[s.key];
      const isRunning = running && !d && (i === 0 || doneMap[STEPS[i - 1].key]);
      const icon = d ? (d.ok ? '<i class="fa-solid fa-circle-check text-emerald-600"></i>' : '<i class="fa-solid fa-circle-xmark text-rose-600"></i>')
        : isRunning ? '<i class="fa-solid fa-circle-notch fa-spin text-emerald-600"></i>' : '<i class="fa-regular fa-circle text-slate-300"></i>';
      return `<li class="flex items-center gap-2.5"><span class="w-4 text-center">${icon}</span>
        <span class="${d || isRunning ? 'text-slate-800 font-medium' : 'text-slate-400'}">${d ? esc(d.label) : s.label}</span>
        ${d?.detail ? `<span class="text-slate-400">· ${esc(d.detail)}</span>` : ''}</li>`;
    }).join('');
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
    state.busy = true;
    $('btn-submit').disabled = true;
    $('error-box').hidden = true;
    $('progress').hidden = false;
    renderProgress([]);

    const fd = new FormData();
    fd.append('prompt', prompt);
    if ($('doc-type').value) fd.append('doc_type', $('doc-type').value);
    if ($('unit').value) fd.append('unit_key', $('unit').value);
    fd.append('urgency', state.urgency);
    fd.append('secret', state.secret);
    try {
      if (state.file && (await auth.serverMode())) {
        // โหมดเซิร์ฟเวอร์: ส่งไฟล์ตรงเข้า Storage ก่อน แล้วให้ API อ่านจากที่นั่น (รองรับไฟล์ถึง 50 MB)
        fd.append('source_path', await api.uploadSource(state.file));
        fd.append('source_name', state.file.name);
      } else if (state.file) {
        fd.append('file', state.file);
      }
      const res = await api.draft(fd);
      renderProgress(res.steps, false);
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
      $('progress').hidden = true;
      $('error-box').innerHTML = `<i class="fa-solid fa-triangle-exclamation mr-1"></i>${esc(err.message)}`;
      $('error-box').hidden = false;
    } finally {
      state.busy = false;
      $('btn-submit').disabled = false;
    }
  }
  form.addEventListener('submit', (e) => { e.preventDefault(); submit(); });
  $('prompt').addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submit(); } });

  $('btn-new').addEventListener('click', () => {
    $('prompt').value = ''; $('file-input').value = ''; setFile(null);
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
      const { references } = await api.legal();
      body.innerHTML = `<p class="text-xs text-slate-500 mb-3">ระบบใส่ข้อกฎหมายลงในร่างเฉพาะรายการที่ <b>ยืนยันแหล่งแล้ว</b> เท่านั้น</p>` +
        (references.length ? `<ul class="space-y-2">${references.map(r => `
          <li class="p-3 rounded-xl border border-slate-200">
            <div class="flex items-start justify-between gap-3">
              <div class="text-xs font-semibold text-slate-800">${esc(r.title)}${r.section ? ` <span class="font-normal text-slate-500">${esc(r.section)}</span>` : ''}</div>
              <span class="text-[10px] px-1.5 py-0.5 rounded border shrink-0 ${r.verified ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-amber-50 text-amber-700 border-amber-200'}">${r.verified ? 'ยืนยันแล้ว' : 'ยังไม่ยืนยัน'}</span>
            </div>
            ${r.quote ? `<p class="text-xs text-slate-600 mt-1.5 font-body leading-relaxed">${esc(r.quote)}</p>` : ''}
          </li>`).join('')}</ul>` : '<p class="text-xs text-slate-400">ยังไม่มีรายการในคลังกฎหมาย</p>');
    },
    async profile(body) {
      const p = state.profile || await api.profile();
      const row = (k, v) => `<div class="grid grid-cols-3 gap-3 py-2 border-b border-slate-100 last:border-0 text-xs"><dt class="text-slate-500">${k}</dt><dd class="col-span-2 text-slate-800 font-body">${esc(v || '—')}</dd></div>`;
      body.innerHTML = `<dl>${row('ส่วนราชการ', p.department_full)}${row('รหัสหนังสือออก', p.doc_origin_code)}${row('ผู้ลงนาม', p.signatory_name)}${row('ตำแหน่ง', p.signatory_position)}${row('ส่วนราชการเจ้าของเรื่อง', p.contact_dept)}${row('โทร / โทรสาร', [p.contact_tel, p.contact_fax].filter(Boolean).join(' / '))}${row('อีเมล', p.contact_email)}</dl>
        <p class="text-[11px] text-slate-400 mt-3">ข้อมูลนี้ใช้เติมหัวหนังสือและผู้ลงนามในร่างทุกฉบับ (ไฟล์ data/user_profile.json)</p>`;
    },
  };
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
