// internal.typ — เทมเพลต Typst สำหรับหนังสือภายใน / บันทึกข้อความ (ครุฑ 1.5 ซม. ด้านซ้าย)
// อ้างอิงจาก whs/typst-govdoc และระเบียบสำนักนายกรัฐมนตรีว่าด้วยงานสารบรรณ พ.ศ. ๒๕๒๖

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
  signatory_name: "",
  signatory_position: "",
  urgency: "normal",
  secret: "normal",
  garuda_path: "../../assets/garuda.svg",
) = {
  set page(
    paper: "a4",
    margin: (top: 2.0cm, bottom: 2.0cm, left: 3.0cm, right: 2.0cm),
  )

  set text(
    font: ("TH Sarabun New", "TH Sarabun PSK", "Sarabun"),
    size: 16pt,
    lang: "th"
  )

  set par(
    leading: 0.65em,
    justify: true
  )

  // หัวกระดาษ: ครุฑ 1.5 ซม. ซ้าย + "บันทึกข้อความ" 29 pt หนา กึ่งกลาง
  grid(
    columns: (2.5cm, 1fr),
    align: (top + left, top + center),
    image(garuda_path, height: 1.5cm),
    text(size: 29pt, weight: "bold")[บันทึกข้อความ]
  )

  #v(0.3cm)

  // ส่วนราชการ
  block[
    #text(weight: "bold")[ส่วนราชการ] #h(0.4cm) #dept_name
  ]

  #v(0.2cm)

  // ที่ และ วันที่
  grid(
    columns: (1fr, 1fr),
    align: (left, left),
    [#text(weight: "bold")[ที่] #h(0.3cm) #doc_number],
    [#text(weight: "bold")[วันที่] #h(0.3cm) #doc_date]
  )

  #v(0.2cm)

  // เรื่อง
  block[
    #text(weight: "bold")[เรื่อง] #h(0.4cm) #subject
  ]

  #v(0.2cm)

  // เรียน
  block[
    #text(weight: "bold")[เรียน] #h(0.4cm) #salutation
  ]

  if references.len() > 0 [
    #v(0.2cm)
    #for (i, ref) in references.enumerate() [
      #if i == 0 [
        #text(weight: "bold")[อ้างถึง] #h(0.3cm) #ref \
      ] else [
        #h(1.5cm) #ref \
      ]
    ]
  ]

  if attachments.len() > 0 [
    #v(0.2cm)
    #for (i, att) in attachments.enumerate() [
      #if i == 0 [
        #text(weight: "bold")[สิ่งที่ส่งมาด้วย] #h(0.3cm) #att \
      ] else [
        #h(2.8cm) #att \
      ]
    ]
  ]

  #v(0.4cm)

  // เนื้อหา 3 ภาค
  par(first-line-indent: 2.5cm)[#paragraph_reason]

  if paragraph_details != none and paragraph_details != "" [
    #v(0.2cm)
    #par(first-line-indent: 2.5cm)[#paragraph_details]
  ]

  #v(0.2cm)
  #par(first-line-indent: 2.5cm)[#paragraph_purpose]

  #v(1.0cm)

  // ผู้ลงนาม (บันทึกข้อความไม่มีคำลงท้าย เช่น ขอแสดงความนับถือ)
  align(center)[
    #h(4.5cm) #signatory_name \
    #h(4.5cm) #signatory_position
  ]
}

