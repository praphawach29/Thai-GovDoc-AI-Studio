// word-template.js — ใช้ไฟล์ Word ที่แนบเป็นแม่แบบ (หน้าแรก)
// ๑ เลือกไฟล์ + พิมพ์สิ่งที่ต้องการแก้ → AI เสนอข้อความใหม่รายย่อหน้า (server/routers/word_template.py)
// ๒ ตรวจทีละจุด: ติ๊กเลือก/แก้ข้อความได้ → ๓ สร้างไฟล์ Word ที่คงรูปแบบเดิม (ไฟล์ไม่ถูกเก็บบนเซิร์ฟเวอร์)
(function () {
  const { api, esc, toThai, download, toast } = window.GovDoc;
  const $ = (id) => document.getElementById(id);
  const modal = $('modal-wt');
  if (!modal) return;
  let proposal = null, lastFocus = null;
  let pendingRefs = [];      // ต้นแบบอื่นจากช่องแชท (เช่น คู่มือ PDF) ส่งเป็นแนวทางให้ AI

  const open = () => { lastFocus = document.activeElement; modal.hidden = false; $('wt-file').focus(); };
  const close = () => { modal.hidden = true; pendingRefs = []; lastFocus?.focus?.(); };
  $('btn-word-template').addEventListener('click', open);
  modal.addEventListener('click', (e) => { if (e.target === modal || e.target.closest('[data-close]')) close(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !modal.hidden) close(); });
  $('wt-file').addEventListener('change', () => { proposal = null; pendingRefs = []; $('wt-review').hidden = true; });

  // เรียกจากช่องแชทหน้าแรก (แนบต้นเรื่อง + แม่แบบ): ใส่ไฟล์/คำสั่งในหน้าต่างนี้แล้วให้ AI เสนอทันที
  const asFiles = (f) => { const dt = new DataTransfer(); if (f) dt.items.add(f); return dt.files; };
  window.GovDocWordTemplate = {
    run({ template, source, prompt, secret, references = [] }) {
      pendingRefs = references;
      open();
      $('wt-file').files = asFiles(template);
      $('wt-source-file').files = asFiles(source);
      $('wt-prompt').value = prompt || '';
      $('wt-source').value = '';
      $('wt-secret').value = secret === 'normal' ? 'normal' : 'secret';
      proposal = null; $('wt-review').hidden = true;
      $('wt-form').requestSubmit();
    },
  };

  function busy(btn, on, label) {
    btn.disabled = on;
    if (on) { btn.dataset.html = btn.innerHTML; btn.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i><span>${label}</span>`; }
    else if (btn.dataset.html) btn.innerHTML = btn.dataset.html;
  }

  $('wt-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const file = $('wt-file').files[0];
    if (!file) { $('wt-file').focus(); return; }
    if (!/\.docx$/i.test(file.name)) { toast('ใช้ได้เฉพาะไฟล์ .docx', 'error'); return; }
    if (!$('wt-prompt').value.trim() && !$('wt-source').value.trim() && !$('wt-source-file').files[0]) {
      toast('แนบไฟล์ต้นเรื่องหรือพิมพ์สิ่งที่ต้องการให้แก้ก่อน', 'warn'); $('wt-prompt').focus(); return;
    }
    const fd = new FormData();
    fd.append('file', file);
    if ($('wt-source-file').files[0]) fd.append('source', $('wt-source-file').files[0]);
    pendingRefs.forEach(f => fd.append('references', f));
    fd.append('prompt', $('wt-prompt').value);
    fd.append('source_text', $('wt-source').value);
    fd.append('secret', $('wt-secret').value);
    busy($('wt-propose'), true, $('wt-source-file').files[0] ? 'AI กำลังอ่านต้นเรื่องและแม่แบบ... (ราว ๑–๒ นาที)' : 'AI กำลังอ่านแม่แบบ... (ราว ๑ นาที)');
    try {
      proposal = await api.wordTemplate.propose(fd);
      renderReview();
    } catch (err) { toast(err.message, 'error'); }
    finally { busy($('wt-propose'), false); }
  });

  function renderReview() {
    const box = $('wt-review');
    const ch = proposal.changes || [];
    box.hidden = false;
    box.innerHTML = `
      <div class="rounded-xl bg-blue-50/70 border border-blue-100 p-3 text-xs text-slate-700 space-y-1">
        <div class="font-medium text-blue-800">AI เสนอแก้ ${toThai(ch.length)} จุด จาก ${toThai(proposal.segment_count || 0)} ย่อหน้า</div>
        ${proposal.summary ? `<div class="whitespace-pre-line">${esc(proposal.summary)}</div>` : ''}
        ${proposal.notes ? `<div class="text-amber-800 whitespace-pre-line"><i class="fa-solid fa-triangle-exclamation mr-1"></i>${esc(proposal.notes)}</div>` : ''}
      </div>
      ${ch.length ? `<div class="flex items-center justify-between text-xs text-slate-500">
          <span>ตรวจทีละจุด — แก้ข้อความในช่องได้ ไม่ติ๊ก = คงข้อความเดิม</span>
          <label class="flex items-center gap-1.5 cursor-pointer"><input type="checkbox" id="wt-all" checked class="rounded border-slate-300 w-3.5 h-3.5">เลือกทั้งหมด</label></div>
        <ol class="space-y-2">${ch.map((c, i) => `
          <li class="rounded-xl border border-slate-200 p-3 space-y-1.5">
            <label class="flex items-center gap-2 text-[11px] text-slate-500 cursor-pointer">
              <input type="checkbox" data-wt-pick="${i}" checked class="rounded border-slate-300 w-3.5 h-3.5">
              <span>${toThai(i + 1)}. ${esc(c.where)}</span></label>
            <div class="text-xs text-slate-400 line-through whitespace-pre-wrap">${esc(c.before) || '(ว่าง)'}</div>
            <textarea data-wt-after="${i}" rows="${Math.min(6, Math.max(1, Math.ceil((c.after || '').length / 70)))}" class="w-full rounded-lg border-slate-300 text-sm">${esc(c.after)}</textarea>
          </li>`).join('')}</ol>
        <div class="flex justify-end gap-2 sticky bottom-0 bg-white pt-2">
          <button type="button" id="wt-build" class="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium"><i class="fa-solid fa-file-arrow-down"></i><span>สร้างไฟล์ Word</span></button>
        </div>` : '<p class="text-xs text-slate-500">ไม่มีจุดที่ต้องแก้ตามคำสั่งนี้ — ลองระบุให้ชัดขึ้น</p>'}`;
    box.scrollIntoView({ behavior: 'smooth', block: 'start' });
    $('wt-all')?.addEventListener('change', (e) => box.querySelectorAll('[data-wt-pick]').forEach(c => { c.checked = e.target.checked; }));
    $('wt-build')?.addEventListener('click', build);
  }

  async function build() {
    const box = $('wt-review');
    const edits = {};
    (proposal.changes || []).forEach((c, i) => {
      if (box.querySelector(`[data-wt-pick="${i}"]`).checked) edits[c.id] = box.querySelector(`[data-wt-after="${i}"]`).value;
    });
    if (!Object.keys(edits).length) { toast('ยังไม่ได้เลือกจุดที่จะแก้', 'warn'); return; }
    const file = $('wt-file').files[0];
    const fd = new FormData();
    fd.append('file', file);
    fd.append('edits', JSON.stringify(edits));
    const btn = $('wt-build');
    busy(btn, true, 'กำลังสร้างไฟล์...');
    try {
      const blob = await api.wordTemplate.build(fd);
      download(blob, file.name.replace(/\.docx$/i, '') + ' (แก้ไข).docx');
      const left = Object.values(edits).filter(v => /\[✏️/.test(v)).length;
      toast(`สร้างไฟล์แล้ว แก้ ${toThai(blob.changed)} ย่อหน้า` + (left ? ` · ยังมี [✏️ ระบุ...] ${toThai(left)} จุดให้กรอกใน Word` : ''), left ? 'warn' : undefined);
    } catch (err) { toast('สร้างไฟล์ไม่สำเร็จ: ' + err.message, 'error'); }
    finally { busy(btn, false); }
  }
})();
