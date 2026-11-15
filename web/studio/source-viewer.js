// source-viewer.js — แสดงไฟล์ต้นเรื่องจริงฝั่งซ้ายของหน้าแก้ไข
// PDF: pdf.js เรนเดอร์ทีละหน้า (เฉพาะหน้าที่เลื่อนมาถึง) + ชั้นข้อความโปร่งใสสำหรับค้นคำ/ไฮไลต์
// ภาพ: <img> ย่อ/ขยายได้
// ไฟล์สแกนที่ไม่มีชั้นข้อความ ค้นคำไม่ได้ในตัวไฟล์ — hasText = false ให้หน้าแก้ไขค้นในข้อความที่ AI อ่านแทน
(function () {
  const PDFJS = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/';
  let loading = null;
  function loadPdfJs() {
    if (window.pdfjsLib) return Promise.resolve(window.pdfjsLib);
    loading = loading || new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = PDFJS + 'build/pdf.min.js';
      s.onload = () => {
        window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS + 'build/pdf.worker.min.js';
        resolve(window.pdfjsLib);
      };
      s.onerror = () => { loading = null; reject(new Error('โหลดตัวแสดง PDF ไม่สำเร็จ')); };
      document.head.appendChild(s);
    });
    return loading;
  }
  // เทียบคำค้นโดยไม่สนช่องว่าง (pdf.js แบ่งข้อความไทยเป็นชิ้น ๆ และอาจแทรกช่องว่าง)
  const squash = (s) => String(s || '').replace(/[\s​]+/g, '');
  const ZOOMS = [0.6, 0.75, 0.9, 1, 1.25, 1.5, 2];

  function base(container, onPage) {
    return {
      container, onPage: onPage || (() => {}), zoomIndex: ZOOMS.indexOf(1), hits: [], cur: -1, hasText: true,
      get zoom() { return ZOOMS[this.zoomIndex]; },
      setZoom(delta) {
        this.zoomIndex = Math.max(0, Math.min(ZOOMS.length - 1, this.zoomIndex + delta));
        this.layout();
        return this.zoom;
      },
    };
  }

  async function openPdf(container, url, onPage) {
    const lib = await loadPdfJs();
    const pdf = await lib.getDocument({
      url, disableRange: true, disableStream: true,
      cMapUrl: PDFJS + 'cmaps/', cMapPacked: true, standardFontDataUrl: PDFJS + 'standard_fonts/',
    }).promise;
    const v = base(container, onPage);
    v.kind = 'pdf';
    v.total = pdf.numPages;
    v.page = 1;
    const pages = [];
    for (let i = 0; i < pdf.numPages; i++) {
      const page = await pdf.getPage(i + 1);
      const vp = page.getViewport({ scale: 1 });
      const div = document.createElement('div');
      div.className = 'pdf-page';
      div.dataset.page = String(i + 1);
      container.appendChild(div);
      pages.push({ page, w: vp.width, h: vp.height, div, rendered: null, textDivs: [], starts: [], ends: [], text: null });
    }

    async function textOf(i) {
      const p = pages[i];
      if (p.text != null) return p;
      const tc = await p.page.getTextContent();
      p.items = tc;
      let acc = 0, joined = '';
      p.starts = []; p.ends = [];
      for (const it of tc.items) {
        const s = squash(it.str);
        p.starts.push(acc); acc += s.length; p.ends.push(acc); joined += s;
      }
      p.text = joined;
      return p;
    }

    let gen = 0;   // เปลี่ยนเมื่อย่อ/ขยาย: งานเรนเดอร์ค้างของขนาดเก่าทิ้งไป
    async function render(i) {
      const p = pages[i];
      if (p.rendered === gen) return;
      const my = gen;
      p.rendered = my;
      const scale = p.scale;
      const vp = p.page.getViewport({ scale });
      const dpr = window.devicePixelRatio || 1;
      const canvas = document.createElement('canvas');
      canvas.width = Math.floor(vp.width * dpr); canvas.height = Math.floor(vp.height * dpr);
      canvas.style.width = vp.width + 'px'; canvas.style.height = vp.height + 'px';
      const ctx = canvas.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      await p.page.render({ canvasContext: ctx, viewport: vp }).promise;
      if (my !== gen) return;
      await textOf(i);
      const layer = document.createElement('div');
      layer.className = 'textLayer';
      layer.style.setProperty('--scale-factor', String(scale));
      const textDivs = [];
      await lib.renderTextLayer({ textContentSource: p.items, container: layer, viewport: vp, textDivs }).promise;
      if (my !== gen) return;
      p.div.replaceChildren(canvas, layer);
      p.textDivs = textDivs;
      v.paint(i);
    }

    const io = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) render(+e.target.dataset.page - 1).catch(() => {});
    }, { root: container, rootMargin: '600px 0px' });

    v.layout = function () {
      const width = container.clientWidth - 24;
      if (width <= 0) return;
      gen++;
      for (const p of pages) {
        p.scale = (width / p.w) * v.zoom;
        p.div.style.width = p.w * p.scale + 'px';
        p.div.style.height = p.h * p.scale + 'px';
        p.div.replaceChildren();
        p.textDivs = [];
        p.rendered = null;
        io.unobserve(p.div); io.observe(p.div);
      }
    };
    let lastWidth = 0;
    new ResizeObserver(() => {
      const w = container.clientWidth;
      if (w && Math.abs(w - lastWidth) > 4) { lastWidth = w; v.layout(); }
    }).observe(container);

    container.addEventListener('scroll', () => {
      const y = container.scrollTop + container.clientHeight / 3;
      let n = 1;
      for (const p of pages) if (p.div.offsetTop <= y) n = +p.div.dataset.page;
      if (n !== v.page) { v.page = n; v.onPage(n, v.total); }
    });

    v.goPage = function (n) {
      n = Math.max(1, Math.min(v.total, n));
      container.scrollTo({ top: pages[n - 1].div.offsetTop - 12 });
      v.page = n; v.onPage(n, v.total);
    };

    // ไฮไลต์ชิ้นข้อความที่ทับกับคำค้น (ทั้งชิ้น — pdf.js วางข้อความเป็นชิ้น ๆ)
    v.paint = function (i) {
      const p = pages[i];
      p.textDivs.forEach((d, j) => {
        const s = p.starts[j], e = p.ends[j];
        const overlap = (h) => h.page === i && h.start < e && h.end > s;
        d.classList.toggle('hl', v.hits.some(overlap));
        d.classList.toggle('hl-cur', v.cur >= 0 && overlap(v.hits[v.cur]));
      });
    };

    v.search = async function (q) {
      const needle = squash(q);
      v.hits = []; v.cur = -1;
      let chars = 0;
      for (let i = 0; i < pages.length; i++) {
        const p = await textOf(i);
        chars += p.text.length;
        if (!needle) continue;
        for (let k = p.text.indexOf(needle); k >= 0; k = p.text.indexOf(needle, k + needle.length)) {
          v.hits.push({ page: i, start: k, end: k + needle.length });
        }
      }
      v.hasText = chars >= 20;
      pages.forEach((_, i) => v.paint(i));
      if (v.hits.length) await v.goto(0);
      return v.hits.length;
    };

    v.goto = async function (k) {
      if (!v.hits.length) return;
      v.cur = (k + v.hits.length) % v.hits.length;
      const h = v.hits[v.cur];
      v.goPage(h.page + 1);
      await render(h.page);
      pages.forEach((_, i) => v.paint(i));
      pages[h.page].div.querySelector('.hl-cur')?.scrollIntoView({ block: 'center' });
    };

    // รู้ล่วงหน้าว่าเป็นไฟล์สแกน (ไม่มีชั้นข้อความ) จาก ๓ หน้าแรก
    v.probeText = async function () {
      let chars = 0;
      for (let i = 0; i < Math.min(3, pages.length); i++) chars += (await textOf(i)).text.length;
      v.hasText = chars >= 20;
      return v.hasText;
    };

    v.layout();
    v.onPage(1, v.total);
    return v;
  }

  function openImage(container, url, onPage) {
    const v = base(container, onPage);
    v.kind = 'image'; v.total = 1; v.page = 1; v.hasText = false;
    const img = document.createElement('img');
    img.src = url; img.alt = 'ไฟล์ต้นเรื่อง';
    img.className = 'block mx-auto bg-white shadow-paper';
    container.appendChild(img);
    v.layout = () => { img.style.width = (v.zoom * 100) + '%'; img.style.maxWidth = 'none'; };
    v.goPage = () => {};
    v.search = async () => 0;
    v.goto = async () => {};
    v.probeText = async () => false;
    v.layout();
    v.onPage(1, 1);
    return new Promise((resolve, reject) => {
      img.onload = () => resolve(v);
      img.onerror = () => reject(new Error('เปิดภาพต้นเรื่องไม่สำเร็จ'));
    });
  }

  window.GovDocSourceViewer = {
    open(container, { url, kind }, { onPage } = {}) {
      container.replaceChildren();
      return kind === 'pdf' ? openPdf(container, url, onPage) : openImage(container, url, onPage);
    },
  };
})();
