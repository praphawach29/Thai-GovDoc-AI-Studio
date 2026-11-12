// external.typ — เทมเพลต Typst สำหรับหนังสือภายนอก (ตราครุฑ 3 ซม. กึ่งกลาง)
// อ้างอิงจาก whs/typst-govdoc และระเบียบสำนักนายกรัฐมนตรีว่าด้วยงานสารบรรณ พ.ศ. ๒๕๒๖
// ทดสอบคอมไพล์กับ Typst 0.15

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
  garuda_path: "../../assets/garuda.svg",
  // bytes ของภาพครุฑ อ่านจากไฟล์หลักด้วย read(..., encoding: none)
  // (image() หาพาธเทียบกับไฟล์ที่เรียก จึงต้องอ่านจากไฟล์หลักแล้วส่งเข้ามา)
  garuda: none,
) = [
  #set page(
    paper: "a4",
    margin: (top: 2.5cm, bottom: 2.0cm, left: 3.0cm, right: 2.0cm),
    header: if secret != "normal" {
      let label = if secret == "top_secret" { "ลับที่สุด" } else if secret == "very_secret" { "ลับมาก" } else { "ลับ" }
      align(center, text(size: 16pt, weight: "bold", fill: rgb("#c00000"), label))
    },
  )
  #set text(font: ("TH Sarabun New", "TH SarabunPSK", "TH Sarabun PSK", "TH SarabunIT๙", "TH Sarabun IT9", "Sarabun"), size: 16pt, lang: "th")
  #set par(leading: 0.5em, justify: true, first-line-indent: 0pt)

  // ชั้นความเร็ว (ถ้ามี) มุมบนซ้าย
  #if urgency != "normal" {
    let label = if urgency == "most_urgent" { "ด่วนที่สุด" } else if urgency == "very_urgent" { "ด่วนมาก" } else { "ด่วน" }
    place(top + left, dy: -0.5cm, text(size: 18pt, weight: "bold", fill: rgb("#c00000"), label))
  }

  // ตราครุฑ 3.0 ซม. กึ่งกลางหน้า
  #align(center, image(if garuda != none { garuda } else { garuda_path }, height: 3.0cm))
  #v(0.3cm)

  // ที่ (ซ้าย) และ ส่วนราชการเจ้าของหนังสือ (ขวา)
  #grid(
    columns: (1fr, 1fr),
    [ที่ #doc_number],
    [#dept_name],
  )
  #v(0.2cm)

  // วันที่ เยื้องกึ่งกลางไปทางขวา
  #pad(left: 6.5cm)[#doc_date]
  #v(0.2cm)

  // เรื่อง, เรียน, อ้างถึง, สิ่งที่ส่งมาด้วย
  #par(hanging-indent: 1.25cm)[เรื่อง#h(0.4cm)#subject]
  #salutation

  #if references != none and references.len() > 0 {
    for (i, r) in references.enumerate() {
      if i == 0 [อ้างถึง#h(0.3cm)#r \ ] else [#h(1.5cm)#r \ ]
    }
  }
  #if attachments != none and attachments.len() > 0 {
    for (i, a) in attachments.enumerate() {
      if i == 0 [สิ่งที่ส่งมาด้วย#h(0.3cm)#a \ ] else [#h(2.8cm)#a \ ]
    }
  }
  #v(0.3cm)

  // เนื้อหา 3 ภาค ย่อหน้า 2.5 ซม.
  #block[#h(2.5cm)#paragraph_reason]
  #if paragraph_details != none and paragraph_details != "" {
    block[#h(2.5cm)#paragraph_details]
  }
  #block[#h(2.5cm)#paragraph_purpose]
  #v(0.8cm)

  // คำลงท้าย และผู้ลงนาม
  #pad(left: 6cm)[
    #align(center)[
      #closing
      #v(1.5cm)
      #signatory_name \
      #signatory_position
    ]
  ]
  #v(0.8cm)

  // ส่วนราชการเจ้าของเรื่อง (มุมล่างซ้าย)
  #text(size: 14pt)[
    #contact_dept \
    โทรศัพท์ #contact_tel \
    #if contact_fax != none and contact_fax != "" [โทรสาร #contact_fax \ ]
    #if contact_email != none and contact_email != "" [ไปรษณีย์อิเล็กทรอนิกส์ #contact_email]
  ]
]
