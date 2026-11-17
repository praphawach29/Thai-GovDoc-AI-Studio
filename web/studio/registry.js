// registry.js — หน้าทะเบียนรับ-ส่ง: ค้นหา กรองตามปี จองเลข ยกเลิกเลข ดูประวัติ (audit) ส่งออก Excel/PDF
(async function () {
  const { api, esc, toThai, download, toast } = window.GovDoc;
  const reg = window.GovDocRegistry;
  const $ = (id) => document.getElementById(id);

  await window.GovDoc.auth.ready;
  const params = new URLSearchParams(location.search);
  const st = { kind: params.get('tab') === 'incoming' ? 'incoming' : 'outgoing', rows: [], timer: null };
  const n = (s) => $('thai').checked ? toThai(s ?? '') : String(s ?? '');
  const fmtTime = (iso) => { try { return n(new Date(iso).toLocaleString('th-TH', { dateStyle: 'medium', timeStyle: 'short' })); } catch (_) { return iso || ''; } };
  const fmtDay = (iso) => { try { return n(new Date(iso).toLocaleDateString('th-TH', { dateStyle: 'medium' })); } catch (_) { return ''; } };

  if (!(await window.GovDoc.auth.serverMode())) {
    $('local-note').hidden = false;
    document.querySelectorAll('#btn-reserve,#btn-xlsx,#btn-pdf').forEach(b => { b.disabled = true; });
    return;
  }
  const showError = (msg) => { $('error-box').textContent = msg || ''; $('error-box').hidden = !msg; };

  // ---------- ปี ----------
  try {
    const { years, current } = await reg.years();
    $('year').innerHTML = years.map(y => `<option value="${y}"${y === current ? ' selected' : ''}>${toThai(y)}</option>`).join('');
    const want = Number(params.get('year'));
    if (years.includes(want)) $('year').value = String(want);
  } catch (err) { showError(err.message); }

  // ---------- ตาราง ----------
  const STATUS = {
    issued: '<span class="px-1.5 py-0.5 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-800">ออกเลขแล้ว</span>',
    reserved: '<span class="px-1.5 py-0.5 rounded-full bg-amber-50 border border-amber-200 text-amber-800">จองไว้</span>',
    cancelled: '<span class="px-1.5 py-0.5 rounded-full bg-rose-50 border border-rose-200 text-rose-700">ยกเลิก</span>',
  };
  const th = (cols) => '<tr>' + cols.map(c => `<th class="px-3 py-2 font-medium whitespace-nowrap">${c}</th>`).join('') + '</tr>';
  const docLink = (id, text) => id ? `<a href="editor.html?id=${encodeURIComponent(id)}" class="text-brand-700 hover:underline">${text}</a>` : text;
  const actBtn = (act, id, icon, label, cls = 'text-slate-600 hover:bg-slate-100') =>
    `<button type="button" data-act="${act}" data-id="${esc(id)}" class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded ${cls}" title="${label}"><i class="${icon}"></i><span class="sr-only sm:not-sr-only">${label}</span></button>`;

  function render() {
    const out = st.kind === 'outgoing';
    document.querySelectorAll('[data-kind]').forEach(b => {
      const on = b.dataset.kind === st.kind;
      b.setAttribute('aria-selected', String(on));
      b.className = 'pb-2.5 border-b-2 ' + (on ? 'border-brand-600 text-slate-900 font-medium' : 'border-transparent text-slate-500 hover:text-slate-800');
    });
    $('status-wrap').hidden = !out;
    $('btn-reserve').hidden = !out;
    $(`count-${st.kind}`).textContent = n(st.rows.length);
    $('thead').innerHTML = out
      ? th(['เลขทะเบียนส่ง', 'ที่', 'ลงวันที่', 'จาก', 'ถึง', 'เรื่อง', 'การปฏิบัติ / หมายเหตุ', 'สถานะ', ''])
      : th(['เลขทะเบียนรับ', 'วันเวลารับ', 'ที่', 'ลงวันที่', 'จาก', 'ถึง', 'เรื่อง', 'การปฏิบัติ', '']);
    if (!st.rows.length) {
      $('tbody').innerHTML = `<tr><td colspan="9" class="px-3 py-8 text-center text-slate-400">${$('q').value.trim() ? 'ไม่พบรายการที่ค้น' : 'ยังไม่มีรายการในปีนี้'}</td></tr>`;
      return;
    }
    $('tbody').innerHTML = st.rows.map(r => out ? outRow(r) : inRow(r)).join('');
  }
  function outRow(r) {
    const cancelled = r.status === 'cancelled';
    const notes = [
      r.incoming ? `ตอบหนังสือรับเลข ${n(r.incoming.reg_no)}/${n(r.incoming.year_be)}` : '',
      r.action_taken,
      cancelled ? `<span class="text-rose-700">ยกเลิก: ${esc(r.cancel_reason || '')}</span> <span class="text-slate-400">${esc(r.cancelled_by_name || '')} ${r.cancelled_at ? fmtTime(r.cancelled_at) : ''}</span>` : '',
      r.status === 'reserved' ? `จองโดย ${esc(r.created_by_name || '')} ${fmtDay(r.created_at)}` : '',
      r.remark,
    ].filter(Boolean);
    return `<tr class="${cancelled ? 'bg-rose-50/30 text-slate-500' : ''} align-top">
      <td class="px-3 py-2 text-center whitespace-nowrap">${n(r.reg_no)}</td>
      <td class="px-3 py-2 whitespace-nowrap font-medium ${cancelled ? 'line-through' : ''}">${docLink(r.document_id, esc(n(r.doc_number)))}</td>
      <td class="px-3 py-2 whitespace-nowrap">${esc(n(r.doc_date || ''))}</td>
      <td class="px-3 py-2">${esc(r.from_unit || '')}</td>
      <td class="px-3 py-2">${esc(r.to_recipient || '')}</td>
      <td class="px-3 py-2 min-w-[14rem]">${esc(r.subject || '')}</td>
      <td class="px-3 py-2 min-w-[10rem]">${notes.map(x => `<div>${x.startsWith('<') ? x : esc(x)}</div>`).join('')}</td>
      <td class="px-3 py-2 whitespace-nowrap">${STATUS[r.status] || esc(r.status)}</td>
      <td class="px-3 py-2 whitespace-nowrap text-right">
        ${!cancelled ? actBtn('cancel', r.id, 'fa-solid fa-ban', 'ยกเลิก', 'text-rose-700 hover:bg-rose-50') : ''}
        ${actBtn('audit', r.id, 'fa-solid fa-clock-rotate-left', 'ประวัติ')}
      </td></tr>`;
  }
  function inRow(r) {
    const replies = (r.replies || []).filter(x => x.status !== 'cancelled')
      .map(x => `<div class="text-emerald-800">ตอบแล้ว ${docLink(x.document_id, 'ที่ ' + esc(n(x.doc_number)))}${x.doc_date ? ` ลว. ${esc(n(x.doc_date))}` : ''}</div>`);
    return `<tr class="align-top">
      <td class="px-3 py-2 text-center whitespace-nowrap">${n(r.reg_no)}</td>
      <td class="px-3 py-2 whitespace-nowrap">${fmtTime(r.received_at)}</td>
      <td class="px-3 py-2 whitespace-nowrap">${esc(n(r.source_doc_number || ''))}</td>
      <td class="px-3 py-2 whitespace-nowrap">${esc(n(r.source_doc_date || ''))}</td>
      <td class="px-3 py-2">${esc(r.from_org || '')}</td>
      <td class="px-3 py-2">${esc(r.to_unit || '')}</td>
      <td class="px-3 py-2 min-w-[14rem]">${docLink(r.document_id, esc(r.subject || ''))}</td>
      <td class="px-3 py-2 min-w-[10rem]">${replies.join('')}${r.action_taken ? `<div>${esc(r.action_taken)}</div>` : ''}${r.remark ? `<div class="text-slate-500">${esc(r.remark)}</div>` : ''}</td>
      <td class="px-3 py-2 whitespace-nowrap text-right">${actBtn('audit', r.id, 'fa-solid fa-clock-rotate-left', 'ประวัติ')}</td></tr>`;
  }
  const filters = () => ({ year: $('year').value, q: $('q').value.trim(), status: st.kind === 'outgoing' ? $('status').value : '' });
  async function load() {
    showError('');
    try {
      st.rows = st.kind === 'outgoing' ? await reg.outgoing(filters()) : await reg.incoming(filters());
    } catch (err) { st.rows = []; showError(err.message); }
    render();
  }
  document.querySelectorAll('[data-kind]').forEach(b => b.addEventListener('click', () => {
    st.kind = b.dataset.kind;
    history.replaceState(null, '', '?tab=' + st.kind);
    load();
  }));
  $('year').addEventListener('change', load);
  $('status').addEventListener('change', load);
  $('thai').addEventListener('change', render);
  $('q').addEventListener('input', () => { clearTimeout(st.timer); st.timer = setTimeout(load, 300); });

  // ---------- ส่งออก ----------
  async function exportAs(format) {
    const btn = $(format === 'xlsx' ? 'btn-xlsx' : 'btn-pdf');
    btn.disabled = true;
    try {
      const f = filters();
      const file = await reg.exportFile(st.kind, format, { year: f.year, q: f.q, thai: $('thai').checked });
      download(file.blob, file.filename);
      toast(`ส่งออก ${n(file.rows)} รายการแล้ว`);
    } catch (err) { toast('ส่งออกไม่สำเร็จ: ' + err.message, 'error'); }
    finally { btn.disabled = false; }
  }
  $('btn-xlsx').addEventListener('click', () => exportAs('xlsx'));
  $('btn-pdf').addEventListener('click', () => exportAs('pdf'));

  // ---------- ป๊อปอัป ----------
  const openModal = (title, html) => { $('modal-title').textContent = title; $('modal-body').innerHTML = html; $('modal').hidden = false; };
  const closeModal = () => { $('modal').hidden = true; };
  $('modal').addEventListener('click', (e) => { if (e.target === $('modal') || e.target.closest('[data-close]')) closeModal(); });
  const input = (id, label, value = '', hint = '') => `<label class="block space-y-1"><span class="font-medium text-slate-700">${label}</span>
    <input id="${id}" type="text" value="${esc(value)}" class="w-full px-3 py-1.5 border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-amber-500 font-body text-sm">
    ${hint ? `<span class="block text-[11px] text-slate-500">${hint}</span>` : ''}</label>`;

  // จองเลข: รหัสจากหน่วยออกหนังสือ ({gap} = ตำแหน่งเลข)
  let units = [];
  $('btn-reserve').addEventListener('click', async () => {
    if (!units.length) { try { units = await api.units(); } catch (_) { units = []; } }
    const year = String(new Date().getFullYear() + 543);
    const formats = units.map(u => {
      const [prefix, suffix = ''] = String(u.doc_number_format || '').replace('{year}', year).split('{gap}');
      return { label: u.label, prefix: prefix.trim(), suffix: suffix.trim() };
    }).filter(f => f.prefix || f.suffix);
    const first = formats.find(f => f.prefix) || formats[0] || { prefix: '', suffix: '' };
    openModal('จองเลขที่หนังสือล่วงหน้า', `
      ${formats.length ? `<label class="block space-y-1"><span class="font-medium text-slate-700">หน่วยออกหนังสือ</span>
        <select id="rs-unit" class="w-full border border-slate-200 rounded-md bg-white py-1.5 pl-2 pr-7 text-xs focus:ring-0">
        ${formats.map((f, i) => `<option value="${i}"${f === first ? ' selected' : ''}>${esc(f.label)} — ${esc(f.prefix)}…${esc(f.suffix)}</option>`).join('')}</select></label>` : ''}
      <div class="grid grid-cols-2 gap-2">${input('rs-prefix', 'รหัสหนังสือ', first.prefix, 'เช่น กท 1205/')}${input('rs-suffix', 'ส่วนท้าย (ถ้ามี)', first.suffix, 'เช่น /2569')}</div>
      <label class="flex items-center gap-2"><input id="rs-circular" type="checkbox" class="rounded border-slate-300 w-3.5 h-3.5"> หนังสือเวียน (เลขชุด ว)</label>
      ${input('rs-subject', 'เรื่อง', '')}
      ${input('rs-to', 'ถึง (ถ้าทราบ)', '')}
      <p class="text-slate-500">เลขที่จองไว้ใช้กับเอกสารได้จากปุ่ม "ออกเลข" ในหน้าแก้ไข — ถ้าไม่ใช้ให้ยกเลิกพร้อมเหตุผล (เลขไม่ถูกนำกลับมาใช้)</p>
      <button type="button" id="rs-submit" class="w-full px-3 py-2 rounded-lg bg-amber-600 hover:bg-amber-700 disabled:bg-slate-300 text-white font-semibold text-sm">จองเลข</button>`);
    $('rs-unit')?.addEventListener('change', (e) => {
      const f = formats[Number(e.target.value)];
      $('rs-prefix').value = f.prefix; $('rs-suffix').value = f.suffix;
    });
  });

  $('modal-body').addEventListener('click', async (e) => {
    const btn = e.target.closest('button');
    if (!btn) return;
    if (btn.id === 'rs-submit') {
      const val = (id) => $(id).value.trim();
      if (!val('rs-subject')) { toast('ใส่เรื่องก่อนจองเลข', 'warn'); return; }
      if (!val('rs-prefix') && !val('rs-suffix')) { toast('ใส่รหัสหนังสือก่อน', 'warn'); return; }
      btn.disabled = true;
      try {
        const res = await reg.reserve({ prefix: val('rs-prefix'), suffix: val('rs-suffix'), subject: val('rs-subject'),
          to_recipient: val('rs-to'), is_circular: $('rs-circular').checked });
        closeModal();
        toast(`จองเลข ${n(res.reserved_number)} แล้ว`);
        load();
      } catch (err) { toast('จองเลขไม่สำเร็จ: ' + err.message, 'error'); btn.disabled = false; }
    }
    if (btn.id === 'cx-submit') {
      const reason = $('cx-reason').value.trim();
      if (!reason) { toast('ต้องระบุเหตุผลการยกเลิกเลข', 'warn'); $('cx-reason').focus(); return; }
      btn.disabled = true;
      try {
        await reg.cancel(btn.dataset.id, reason);
        closeModal();
        toast('ยกเลิกเลขแล้ว — รายการยังอยู่ในทะเบียน');
        load();
      } catch (err) { toast('ยกเลิกไม่สำเร็จ: ' + err.message, 'error'); btn.disabled = false; }
    }
  });

  $('tbody').addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const row = st.rows.find(r => String(r.id) === btn.dataset.id);
    if (!row) return;
    if (btn.dataset.act === 'cancel') {
      openModal('ยกเลิกเลขที่หนังสือ', `
        <div class="bg-rose-50 border border-rose-200 rounded-xl p-3"><div class="font-semibold text-rose-900 text-sm font-body">ที่ ${esc(n(row.doc_number))}</div>
          <div class="text-slate-600">${esc(row.subject || '')}</div></div>
        ${row.document_id ? '<p class="text-amber-800">เลขนี้ผูกกับเอกสารในระบบ — ช่อง "ที่" ของเอกสารจะว่างให้ออกเลขใหม่</p>' : ''}
        <label class="block space-y-1"><span class="font-medium text-slate-700">เหตุผล (บันทึกในทะเบียน)</span>
          <textarea id="cx-reason" rows="3" maxlength="500" class="w-full px-3 py-1.5 border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-rose-500"></textarea></label>
        <p class="text-slate-500">เลขที่ยกเลิกยังอยู่ในทะเบียนพร้อมเหตุผล ผู้ยกเลิก และเวลา — จะไม่ถูกนำกลับมาใช้</p>
        <button type="button" id="cx-submit" data-id="${esc(row.id)}" class="w-full px-3 py-2 rounded-lg bg-rose-600 hover:bg-rose-700 disabled:bg-slate-300 text-white font-semibold text-sm">ยกเลิกเลข</button>`);
      $('cx-reason').focus();
      return;
    }
    openModal(`ประวัติ ${st.kind === 'outgoing' ? 'ที่ ' + n(row.doc_number) : 'เลขรับ ' + n(row.reg_no)}`, '<p class="text-slate-500">กำลังโหลด...</p>');
    try {
      const items = await reg.audit(st.kind, row.id);
      $('modal-body').innerHTML = items.length ? `<ol class="space-y-2">${items.map(a => `<li class="border-l-2 border-slate-200 pl-3">
          <div class="font-medium text-slate-800">${esc(a.action_label)}${a.details?.cancel_reason && a.action === 'cancel' ? ` — ${esc(a.details.cancel_reason)}` : ''}</div>
          <div class="text-slate-500">${esc(a.actor_name || 'ไม่ทราบชื่อผู้ใช้')} · ${fmtTime(a.at)}</div></li>`).join('')}</ol>
          <p class="text-[11px] text-slate-400 pt-2">บันทึกจาก audit log ที่แก้ไขย้อนหลังไม่ได้</p>`
        : '<p class="text-slate-500">ยังไม่มีประวัติ</p>';
    } catch (err) { $('modal-body').innerHTML = `<p class="text-rose-700">${esc(err.message)}</p>`; }
  });

  load();
})();
