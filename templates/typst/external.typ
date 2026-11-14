// external.typ — เทมเพลต Typst สำหรับหนังสือภายนอก (ตราครุฑ 3 ซม. กึ่งกลาง)
// อ้างอิงจาก whs/typst-govdoc และระเบียบสำนักนายกรัฐมนตรีว่าด้วยงานสารบรรณ พ.ศ. ๒๕๒๖
// ทดสอบคอมไพล์กับ Typst 0.15
//
// ตำแหน่งตามคู่มือการพิมพ์หนังสือราชการ (แบบที่ ๒๘ กระดาษตราครุฑ):
//   พื้นที่พิมพ์กว้าง 16 ซม. (ขอบซ้าย 3 ขวา 2) แนวกึ่งกลาง = 8 ซม.
//   ครุฑสูง 3 ซม. เท้าขวาอยู่ห่างแนวกึ่งกลาง ~0.7 ซม. (วัดจาก assets/garuda.svg)
//   "ที่" และส่วนราชการเจ้าของหนังสือ อยู่แนวเท้าครุฑ
//   ตัวแรกของ "ชื่อเดือน" ตรงแนวเท้าขวาของครุฑ
//   เรื่อง/เรียน/อ้างถึง/สิ่งที่ส่งมาด้วย/ย่อหน้า: 1 บรรทัด + 6 pt
//   คำลงท้าย: ตัวแรกตรงแนวกึ่งกลาง, ห่างย่อหน้าสุดท้าย 1 บรรทัด + 12 pt
//   ชื่อ/ตำแหน่ง: ใต้คำลงท้าย 4 Enter และอยู่กึ่งกลางซึ่งกันและกันกับคำลงท้าย
//   ส่วนราชการเจ้าของเรื่อง: 16 pt ใต้ตำแหน่ง 4 Enter
//   ชั้นความเร็ว: แดง 32 pt / ชั้นความลับ: แดง กลางหน้า บนและล่าง

#let _thai_digits(s) = {
  let out = str(s)
  for (a, b) in (("0", "๐"), ("1", "๑"), ("2", "๒"), ("3", "๓"), ("4", "๔"),
                 ("5", "๕"), ("6", "๖"), ("7", "๗"), ("8", "๘"), ("9", "๙")) {
    out = out.replace(a, b)
  }
  out
}

#let _CENTER = 8cm          // แนวกึ่งกลางพื้นที่พิมพ์ (16 ซม. / 2)
#let _GARUDA_FOOT = 0.7cm   // ระยะเท้าขวาครุฑจากแนวกึ่งกลาง (ครุฑสูง 3 ซม.)
#let _RED = rgb("#c00000")
// ระยะบรรทัด single ของ TH Sarabun 16 pt ≈ 20.8 pt (0.75em + 0.3em + leading 0.25em)
#let _LEADING = 0.25em
#let _LINE = 1.3em
// n Enter = บรรทัดถัดไปอยู่ห่าง n บรรทัด (เว้นว่าง n-1 บรรทัด)
// ช่วงลงนามเป็น block ซึ่ง Typst ให้ระยะห่าง 1 บรรทัดอยู่แล้ว จึงเติม n-1 บรรทัด
// (วัดจาก PDF จริงใน tests/test_step4_layout.py)
#let _enters(n) = v((n - 1) * _LINE)

#let _secret_label(secret) = if secret == "top_secret" { "ลับที่สุด" } else if secret == "very_secret" { "ลับมาก" } else { "ลับ" }
#let _urgency_label(urgency) = if urgency == "most_urgent" { "ด่วนที่สุด" } else if urgency == "very_urgent" { "ด่วนมาก" } else { "ด่วน" }

// วันที่: วางให้ชื่อเดือนเริ่มที่แนวเท้าขวาครุฑ (เลขวันอยู่ทางซ้ายของแนว)
#let _dated(date) = context {
  let parts = date.trim().split(" ")
  let day = if parts.len() > 2 and parts.first().len() > 0 { parts.first() + " " } else { "" }
  let offset = measure(text(day)).width
  pad(left: calc.max(0cm, _CENTER + _GARUDA_FOOT - offset).to-absolute())[#date.trim()]
}

// คำลงท้าย + ชื่อ + ตำแหน่ง กึ่งกลางซึ่งกันและกัน โดยตัวแรกของคำลงท้ายอยู่ที่แนวกึ่งกลาง
#let _signoff(closing, name, position) = context {
  let axis = _CENTER + measure(text(closing)).width / 2
  let line(body) = {
    let w = measure(text(body)).width
    pad(left: calc.max(0cm, (axis - w / 2).to-absolute()), body)
  }
  set par(justify: false)
  line(closing)
  _enters(4)
  // ชื่อและตำแหน่งห่างกัน 1 Enter (ไม่มีระยะเพิ่ม 6 pt)
  block(spacing: _LEADING, line(name))
  block(spacing: _LEADING, line(position))
}

#let govdoc_external(
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
  closing: "ขอแสดงความนับถือ",
  signatory_name: "",
  signatory_position: "",
  contact_dept: "",
  contact_tel: "",
  contact_fax: none,
  contact_email: none,
  urgency: "normal",
  secret: "normal",
  thai_page_numbers: false,
  garuda_path: "../../assets/garuda.svg",
  // bytes ของภาพครุฑ อ่านจากไฟล์หลักด้วย read(..., encoding: none)
  // (image() หาพาธเทียบกับไฟล์ที่เรียก จึงต้องอ่านจากไฟล์หลักแล้วส่งเข้ามา)
  garuda: none,
) = [
  #set page(
    paper: "a4",
    margin: (top: 2.5cm, bottom: 2.0cm, left: 3.0cm, right: 2.0cm),
    header: context {
      if secret != "normal" {
        align(center, text(size: 20pt, weight: "bold", fill: _RED, _secret_label(secret)))
      }
      let n = counter(page).get().first()
      if n > 1 {
        let label = if thai_page_numbers { _thai_digits(n) } else { str(n) }
        align(center, text(size: 16pt, "-" + label + "-"))
      }
    },
    footer: if secret != "normal" {
      align(center, text(size: 20pt, weight: "bold", fill: _RED, _secret_label(secret)))
    },
  )
  #set text(font: ("TH Sarabun New", "TH SarabunPSK", "TH Sarabun PSK", "TH SarabunIT๙", "TH Sarabun IT9", "Sarabun"), size: 16pt, lang: "th",
            top-edge: 0.75em, bottom-edge: -0.3em)
  // 1 Enter + Before 6 pt ระหว่างย่อหน้าและหัวข้อ
  #set par(leading: _LEADING, spacing: _LEADING + 6pt, justify: true, first-line-indent: 0pt)

  // แถวหัว: [ชั้นความเร็ว / ที่] | ครุฑ 3 ซม. | [ส่วนราชการ] — "ที่" และส่วนราชการอยู่แนวเท้าครุฑ
  #let dept_lines = dept_name.split("\n")
  #grid(
    columns: (1fr, 3cm, 1fr),
    column-gutter: 0cm,
    align(left + bottom)[
      #if urgency != "normal" {
        block(text(size: 32pt, weight: "bold", fill: _RED, _urgency_label(urgency)))
      }
      ที่#h(0.3cm)#doc_number
    ],
    align(center + top, image(if garuda != none { garuda } else { garuda_path }, height: 3.0cm)),
    align(left + bottom, pad(left: 1cm, dept_lines.first())),
  )
  #if dept_lines.len() > 1 {
    v(_LEADING, weak: true)
    pad(left: _CENTER + 1.5cm + 1cm, par(justify: false, dept_lines.slice(1).join("\n")))
  }

  #_dated(doc_date)

  #par(hanging-indent: 1.25cm)[เรื่อง#h(0.3cm)#subject]
  #par[#salutation]

  #if references != none and references.len() > 0 {
    par(hanging-indent: 1.5cm)[อ้างถึง#h(0.3cm)#references.join(linebreak())]
  }
  #if attachments != none and attachments.len() > 0 {
    par(hanging-indent: 2.8cm)[สิ่งที่ส่งมาด้วย#h(0.3cm)#attachments.join(linebreak())]
  }

  // เนื้อความ ย่อหน้า 2.5 ซม. (ภาคเหตุ / ภาคข้อเท็จจริง / ภาคความประสงค์)
  #par[#h(2.5cm)#paragraph_reason]
  #if paragraph_details != none and paragraph_details != "" {
    par[#h(2.5cm)#paragraph_details]
  }
  #par[#h(2.5cm)#paragraph_purpose]

  // คำลงท้าย: 1 Enter + Before 12 pt จากย่อหน้าสุดท้าย
  #v(6pt)
  #_signoff(closing, signatory_name, signatory_position)

  // ส่วนราชการเจ้าของเรื่อง 16 pt ใต้ตำแหน่ง 4 Enter
  #_enters(4)
  #set par(justify: false, spacing: _LEADING)
  #contact_dept
  #if contact_tel != none and contact_tel != "" [

    โทร. #contact_tel
  ]
  #if contact_fax != none and contact_fax != "" [

    โทรสาร #contact_fax
  ]
  #if contact_email != none and contact_email != "" [

    ไปรษณีย์อิเล็กทรอนิกส์ #contact_email
  ]
]
