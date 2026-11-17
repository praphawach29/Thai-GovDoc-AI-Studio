// stamp.typ — หนังสือประทับตรา (แบบที่ ๓ ระเบียบสำนักนายกรัฐมนตรีว่าด้วยงานสารบรรณ พ.ศ. ๒๕๒๖)
// ส่วนประกอบ: ที่ · ถึง · ข้อความ · ส่วนราชการที่ส่งหนังสือออก · ตราชื่อส่วนราชการ (หมึกแดง + ลงชื่อย่อกำกับตรา)
//             · วัน เดือน ปี · ส่วนราชการเจ้าของเรื่อง · โทร. / โทรสาร / ไปรษณีย์อิเล็กทรอนิกส์
// ไม่มีเรื่อง คำขึ้นต้น คำลงท้าย และผู้ลงนาม
// หน้ากระดาษ/ครุฑ/ระยะบรรทัดเหมือนหนังสือภายนอก (external.typ): ขอบ บน 2.5 ล่าง 2 ซ้าย 3 ขวา 2 ซม., ครุฑ 3 ซม. กึ่งกลาง
// ส่วนราชการที่ส่ง และวันที่ เริ่มที่แนวกึ่งกลางพื้นที่พิมพ์ (8 ซม.) — ตรงกับ core/word_exporter._build_stamp_doc

#let _thai_digits(s) = {
  let out = str(s)
  for (a, b) in (("0", "๐"), ("1", "๑"), ("2", "๒"), ("3", "๓"), ("4", "๔"),
                 ("5", "๕"), ("6", "๖"), ("7", "๗"), ("8", "๘"), ("9", "๙")) {
    out = out.replace(a, b)
  }
  out
}

#let _CENTER = 8cm
#let _RED = rgb("#c00000")
#let _LEADING = 0.25em
#let _LINE = 1.3em
#let _enters(n) = v((n - 1) * _LINE)

#let _secret_label(secret) = if secret == "top_secret" { "ลับที่สุด" } else if secret == "very_secret" { "ลับมาก" } else { "ลับ" }
#let _urgency_label(urgency) = if urgency == "most_urgent" { "ด่วนที่สุด" } else if urgency == "very_urgent" { "ด่วนมาก" } else { "ด่วน" }

#let govdoc_stamp(
  doc_number: "",
  recipient: "",
  // ย่อหน้าเนื้อความ ((indent: 2.5cm, text: "..."), ...) จาก core.doc_forms.body_lines
  body: (),
  sender: "",
  doc_date: "",
  stamp_gap: 2.2cm,
  contact_dept: "",
  contact_tel: "",
  contact_fax: none,
  contact_email: none,
  urgency: "normal",
  secret: "normal",
  thai_page_numbers: false,
  font: "TH SarabunPSK",
  garuda_path: "../../assets/garuda_krut.png",
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
  #set text(font: (font, "TH Sarabun New", "Sarabun"), size: 16pt, lang: "th",
            top-edge: 0.75em, bottom-edge: -0.3em)
  #set par(leading: _LEADING, spacing: _LEADING + 6pt, justify: true, first-line-indent: 0pt)

  // แถวหัว: [ชั้นความเร็ว / ที่] | ครุฑ 3 ซม. | (ว่าง) — "ที่" อยู่แนวเท้าครุฑ
  #grid(
    columns: (1fr, 3cm, 1fr),
    align(left + bottom)[
      #if urgency != "normal" {
        block(text(size: 32pt, weight: "bold", fill: _RED, _urgency_label(urgency)))
      }
      #text(weight: "bold")[ที่]#h(0.3cm)#doc_number
    ],
    align(center + top, image(if garuda != none { garuda } else { garuda_path }, height: 3.0cm)),
    [],
  )

  #v(6pt)
  #par(hanging-indent: 1.0cm, justify: false)[#text(weight: "bold")[ถึง]#h(0.3cm)#recipient]

  #for b in body {
    par[#h(b.indent)#b.text]
  }

  // ส่วนราชการที่ส่ง — เว้นที่ประทับตรา — วัน เดือน ปี (เริ่มที่แนวกึ่งกลาง)
  #v(6pt + _LINE)
  #set par(justify: false)
  #pad(left: _CENTER, sender)
  #v(stamp_gap)
  #pad(left: _CENTER, doc_date)

  #_enters(4)
  #set par(spacing: _LEADING)
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
