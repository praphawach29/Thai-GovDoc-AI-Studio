// external.typ — เทมเพลต Typst สำหรับหนังสือภายนอก (ตราครุฑ 3 ซม. กึ่งกลาง)
// อ้างอิงจาก whs/typst-govdoc และระเบียบสำนักนายกรัฐมนตรีว่าด้วยงานสารบรรณ พ.ศ. ๒๕๒๖

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
) = {
  set page(
    paper: "a4",
    margin: (top: 2.5cm, bottom: 2.0cm, left: 3.0cm, right: 2.0cm),
    header: locate(loc => {
      if secret != "normal" {
        align(center)[#text(size: 16pt, weight: "bold", fill: rgb("#c00000"))[
          #if secret == "top_secret" [ลับที่สุด] else if secret == "very_secret" [ลับมาก] else [ลับ]
        ]]
      }
    })
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

  // ชั้นความเร็ว (ถ้ามี) วางมุมบนซ้าย
  if urgency != "normal" [
    #place(top + left, dx: 0cm, dy: -0.5cm)[
      #text(size: 18pt, weight: "bold", fill: rgb("#c00000"))[
        #if urgency == "most_urgent" [ด่วนที่สุด] else if urgency == "very_urgent" [ด่วนมาก] else [ด่วน]
      ]
    ]
  ]

  // ตราครุฑ 3.0 ซม. กึ่งกลางหน้า
  align(center)[
    #image(garuda_path, height: 3.0cm)
  ]

  #v(0.3cm)

  // ที่ และ ส่วนราชการ
  grid(
    columns: (1fr, 1fr),
    align: (left, left),
    [ที่ #doc_number],
    [#dept_name]
  )

  #v(0.2cm)

  // วันที่ วางกึ่งกลางเยื้องไปทางขวา
  align(center)[
    #h(4.0cm) #doc_date
  ]

  #v(0.2cm)

  // เรื่อง, เรียน, อ้างถึง, สิ่งที่ส่งมาด้วย
  block[
    #text(weight: "bold")[เรื่อง] #h(0.4cm) #subject \
    #text(weight: "bold")[เรียน] #h(0.4cm) #salutation \
    #if references != none and references.len() > 0 [
      #text(weight: "bold")[อ้างถึง] #h(0.3cm) #references.join("\n" + h(1.5cm)) \
    ]
    #if attachments != none and attachments.len() > 0 [
      #text(weight: "bold")[สิ่งที่ส่งมาด้วย] #h(0.2cm) #attachments.join("\n" + h(2.8cm)) \
    ]
  ]

  #v(0.3cm)

  // เนื้อหา 3 ภาค ย่อหน้า 2.5 ซม.
  par(first-line-indent: 2.5cm)[#paragraph_reason]

  if paragraph_details != none and paragraph_details != "" [
    #v(0.2cm)
    #par(first-line-indent: 2.5cm)[#paragraph_details]
  ]

  #v(0.2cm)
  #par(first-line-indent: 2.5cm)[#paragraph_purpose]

  #v(0.8cm)

  // คำลงท้าย และผู้ลงนาม
  align(center)[
    #h(4.5cm) #closing \
    #v(1.5cm)
    #h(4.5cm) #signatory_name \
    #h(4.5cm) #signatory_position
  ]

  #v(0.8cm)

  // ส่วนราชการเจ้าของเรื่อง (มุมล่างซ้าย)
  align(left)[
    #text(size: 14pt)[
      #contact_dept \
      โทรศัพท์ #contact_tel \
      #if contact_fax != none and contact_fax != "" [โทรสาร #contact_fax \ ]
      #if contact_email != none and contact_email != "" [ไปรษณีย์อิเล็กทรอนิกส์ #contact_email]
    ]
  ]
}

