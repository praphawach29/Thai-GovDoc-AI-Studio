// internal.typ — เทมเพลต Typst สำหรับหนังสือภายใน / บันทึกข้อความ (ครุฑ 1.5 ซม. ด้านซ้าย)
// อ้างอิงจาก whs/typst-govdoc และระเบียบสำนักนายกรัฐมนตรีว่าด้วยงานสารบรรณ พ.ศ. ๒๕๒๖
//
// โครงสร้างหัวกระดาษตามแบบบันทึกข้อความ:
//   ส่วนราชการ / ที่ / วันที่ / เรื่อง  ตัวหนา 20 pt ตามด้วยเส้นจุดไข่ปลาถึงขอบขวา
//   เรียน ตัวปกติ 16 pt
// เนื้อความ: รับ memo_blocks ที่จัดเตรียมโดย core/memo_layout.py
//   แต่ละบล็อก = (lead, lead_style, text, indent, space_before, kind)
// เลขหน้า "-๒-" กึ่งกลางด้านบน เริ่มตั้งแต่หน้าที่ ๒

#let _thai_digits(s) = {
  let out = str(s)
  for (a, b) in (("0", "๐"), ("1", "๑"), ("2", "๒"), ("3", "๓"), ("4", "๔"),
                 ("5", "๕"), ("6", "๖"), ("7", "๗"), ("8", "๘"), ("9", "๙")) {
    out = out.replace(a, b)
  }
  out
}

#let _leader = box(width: 1fr, repeat[.])

#let _secret_label(secret) = if secret == "top_secret" { "ลับที่สุด" } else if secret == "very_secret" { "ลับมาก" } else { "ลับ" }
#let _urgency_label(urgency) = if urgency == "most_urgent" { "ด่วนที่สุด" } else if urgency == "very_urgent" { "ด่วนมาก" } else { "ด่วน" }

// ระยะบรรทัด ≈ 0.75 ซม. ที่ 16pt (เทียบกับบันทึกข้อความต้นแบบที่พิมพ์จาก Word)
#let _leading = 0.25em

#let _field(label, value) = [
  #text(size: 20pt, weight: "bold")[#label]#h(0.25cm)#value#_leader
]

// "ส่วนราชการ" ต้องอยู่บรรทัดเดียวเสมอ (เช่น "สำนัก... (กอง... โทร... โทรสาร ...)")
// ถ้ายาวเกิน บีบตัวอักษรแนวนอนให้พอดีแบบเดียวกับ Word (w:w) — ไม่ขึ้นบรรทัดใหม่
#let _field_one_line(label, value) = layout(size => context {
  let head = text(size: 20pt, weight: "bold")[#label]
  let room = size.width - measure(head).width - 0.25cm - 0.3cm
  let w = measure(value).width
  if w <= room or w == 0pt {
    _field(label, value)
  } else {
    let ratio = room / w * 100%
    [#head#h(0.25cm)#box(scale(x: ratio, origin: left, reflow: true, box(width: w + 1pt, value)))#_leader]
  }
})

#let govdoc_internal(
  doc_number: "",
  dept_name: "",
  doc_date: "",
  subject: "",
  salutation: "",
  references: (),
  attachments: (),
  paragraph_reason: "",
  paragraph_details: none,
  paragraph_purpose: "",
  memo_blocks: (),
  signatory_name: "",
  signatory_position: "",
  // ผู้ลงนามเพิ่มเติมต่อจากผู้ลงนามหลัก: ((name: "...", position: "..."), ...)
  co_signers: (),
  urgency: "normal",
  secret: "normal",
  thai_page_numbers: false,
  // โปรไฟล์ค่าเริ่มต้น = แบบกรุงเทพมหานคร (ขอบบน 1.5 ซม., หัว 32 pt)
  // คู่มือการพิมพ์ทั่วไป: top_margin 2.5cm, title_size 29pt
  top_margin: 1.5cm,
  title_size: 32pt,
  garuda_path: "../../assets/garuda.svg",
  // bytes ของภาพครุฑ อ่านจากไฟล์หลักด้วย read(..., encoding: none)
  // (image() หาพาธเทียบกับไฟล์ที่เรียก จึงต้องอ่านจากไฟล์หลักแล้วส่งเข้ามา)
  garuda: none,
) = [
  #set page(
    paper: "a4",
    margin: (top: top_margin, bottom: 2.0cm, left: 3.0cm, right: 2.0cm),
    header: context {
      // ชั้นความลับ: แดง กลางหน้า ทั้งบนและล่างทุกหน้า
      if secret != "normal" {
        align(center, text(size: 20pt, weight: "bold", fill: rgb("#c00000"), _secret_label(secret)))
      }
      let n = counter(page).get().first()
      if n > 1 {
        let label = if thai_page_numbers { _thai_digits(n) } else { str(n) }
        align(center, text(size: 16pt, "-" + label + "-"))
      }
    },
    footer: if secret != "normal" {
      align(center, text(size: 20pt, weight: "bold", fill: rgb("#c00000"), _secret_label(secret)))
    },
  )
  // ฟอนต์ตระกูล Sarabun มี ascender/descender สูงมาก — กำหนดขอบบรรทัดเองให้ระยะบรรทัดใกล้เคียง Word (single)
  #set text(font: ("TH Sarabun New", "TH SarabunPSK", "TH Sarabun PSK", "TH SarabunIT๙", "TH Sarabun IT9", "Sarabun"), size: 16pt, lang: "th",
            top-edge: 0.75em, bottom-edge: -0.3em)
  #set par(leading: _leading, spacing: _leading, justify: true, first-line-indent: 0pt)

  // หัวกระดาษ: ครุฑ 1.5 ซม. ซ้าย + ชั้นความเร็ว (แดง 32 pt ถัดจากครุฑ) + "บันทึกข้อความ" ตัวหนา กึ่งกลาง
  #block(height: 1.6cm, width: 100%)[
    #place(top + left, image(if garuda != none { garuda } else { garuda_path }, height: 1.5cm))
    #if urgency != "normal" {
      place(left + horizon, dx: 1.9cm,
            text(size: 32pt, weight: "bold", fill: rgb("#c00000"), _urgency_label(urgency)))
    }
    #align(center + horizon, text(size: title_size, weight: "bold")[บันทึกข้อความ])
  ]

  #_field_one_line("ส่วนราชการ", dept_name)

  #grid(
    columns: (7.5cm, 1fr),
    _field("ที่", doc_number),
    _field("วันที่", doc_date),
  )

  #par(hanging-indent: 1.25cm)[#_field("เรื่อง", subject)]

  #v(0.2cm)
  #salutation

  #if references.len() > 0 {
    for (i, r) in references.enumerate() {
      if i == 0 [*อ้างถึง*#h(0.3cm)#r \ ] else [#h(1.5cm)#r \ ]
    }
  }

  #if attachments.len() > 0 {
    for (i, a) in attachments.enumerate() {
      if i == 0 [*สิ่งที่ส่งมาด้วย*#h(0.3cm)#a \ ] else [#h(2.8cm)#a \ ]
    }
  }

  // เนื้อความบันทึกข้อความ (ระยะย่อหน้าบรรทัดแรกกำหนดจาก memo_layout)
  #if memo_blocks.len() > 0 {
    for b in memo_blocks {
      let lead = if b.lead == "" { [] } else if b.lead_style == "underline" {
        underline(b.lead)
      } else if b.lead_style == "bold" {
        strong(b.lead)
      } else { [#b.lead] }
      let gap = if b.lead != "" and b.text != "" { h(0.5em) } else { [] }
      // ระยะระหว่างบล็อก = ระยะบรรทัดปกติ + ระยะเว้นก่อนหัวข้อ (ถ้า 0 บล็อกจะซ้อนทับกัน)
      block(above: _leading + b.space_before, below: 0pt)[
        #par(justify: b.kind != "heading")[#h(b.indent)#lead#gap#b.text]
      ]
    }
  } else {
    // ข้อมูลรุ่นเดิม: เนื้อหา 3 ภาค
    block[#h(2.5cm)#paragraph_reason]
    if paragraph_details != none and paragraph_details != "" {
      block[#h(2.5cm)#paragraph_details]
    }
    block[#h(2.5cm)#paragraph_purpose]
  }

  #v(1.5cm)

  // ผู้ลงนาม (บันทึกข้อความไม่มีคำลงท้าย เช่น ขอแสดงความนับถือ)
  #pad(left: 6cm)[
    #align(center)[
      #signatory_name \
      #signatory_position
    ]
  ]

  // ผู้ลงนามถัดไป (เช่น หัวหน้ากลุ่มงานลงนามต่อจากผู้เสนอเรื่อง)
  #for s in co_signers {
    v(1.5cm)
    pad(left: 6cm, align(center)[#s.name \ #s.position])
  }
]
