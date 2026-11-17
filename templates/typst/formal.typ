// formal.typ — แบบหัวกลางของระเบียบงานสารบรรณ: คำสั่ง (แบบที่ ๔) / ระเบียบ (๕) / ข้อบังคับ (๖) / ประกาศ (๗)
// ครุฑ 3 ซม. กึ่งกลาง · ชื่อเอกสาร (ตัวหนา กึ่งกลาง) · ที่ (เฉพาะคำสั่ง) · เรื่อง/ว่าด้วย (กึ่งกลาง)
// · [ฉบับที่ / พ.ศ. ของระเบียบ] · เส้นคั่นสั้นกึ่งกลาง · ข้อความ (ย่อหน้า 2.5 ซม.)
// · "<สั่ง/ประกาศ> ณ วันที่ ..." (เริ่ม 5 ซม.) · ลายมือชื่อ · (ชื่อเต็ม) · ตำแหน่ง (กึ่งกลางช่วง 6 ซม.–ขอบขวา)
// ขอบ บน 2.5 ล่าง 2 ซ้าย 3 ขวา 2 ซม. (เหมือนหนังสือภายนอก) — ตำแหน่งตรงกับ core/word_exporter._build_formal_doc

#let _thai_digits(s) = {
  let out = str(s)
  for (a, b) in (("0", "๐"), ("1", "๑"), ("2", "๒"), ("3", "๓"), ("4", "๔"),
                 ("5", "๕"), ("6", "๖"), ("7", "๗"), ("8", "๘"), ("9", "๙")) {
    out = out.replace(a, b)
  }
  out
}

#let _RED = rgb("#c00000")
#let _LEADING = 0.25em
#let _LINE = 1.3em
#let _enters(n) = v((n - 1) * _LINE)
#let _secret_label(secret) = if secret == "top_secret" { "ลับที่สุด" } else if secret == "very_secret" { "ลับมาก" } else { "ลับ" }
#let _urgency_label(urgency) = if urgency == "most_urgent" { "ด่วนที่สุด" } else if urgency == "very_urgent" { "ด่วนมาก" } else { "ด่วน" }

#let govdoc_formal(
  title: "",
  // none = ไม่มีบรรทัด "ที่" (ประกาศ/ระเบียบ/ข้อบังคับ)
  doc_number: none,
  subject_label: "เรื่อง",
  subject: "",
  // บรรทัดเพิ่มใต้เรื่อง เช่น ("(ฉบับที่ ๒)", "พ.ศ. ๒๕๖๙") ของระเบียบ/ข้อบังคับ
  extra_lines: (),
  rule_length: 4cm,
  body: (),
  date_label: "สั่ง ณ วันที่",
  doc_date: "",
  date_indent: 5cm,
  sign_left: 6cm,
  signatory_name: "",
  signatory_position: "",
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

  #if urgency != "normal" {
    place(top + left, text(size: 32pt, weight: "bold", fill: _RED, _urgency_label(urgency)))
  }
  #align(center, image(if garuda != none { garuda } else { garuda_path }, height: 3.0cm))

  // หัวกลาง: ชื่อเอกสาร · ที่ · เรื่อง — ระยะ 1 บรรทัด (ไม่มี 6 pt) กึ่งกลางทุกบรรทัด
  #v(6pt)
  #{
    set par(justify: false, spacing: _LEADING)
    align(center, text(weight: "bold", title))
    if doc_number != none {
      align(center)[ที่#h(0.3cm)#doc_number]
    }
    align(center)[#subject_label#h(0.3cm)#subject]
    for line in extra_lines {
      align(center, line)
    }
  }
  #v(4pt)
  #align(center, line(length: rule_length, stroke: 0.6pt))
  #v(2pt)

  #for b in body {
    par[#h(b.indent)#b.text]
  }

  // วันที่สั่ง/ประกาศ: 1 บรรทัด + 6 pt จากข้อความ, เริ่มที่ date_indent
  #v(_LINE)
  #set par(justify: false)
  #pad(left: date_indent)[#date_label#h(0.3cm)#doc_date]

  // ลายมือชื่อ (ว่าง 3 บรรทัด) · ชื่อเต็ม · ตำแหน่ง — กึ่งกลางในช่วง sign_left ถึงขอบขวา
  #_enters(4)
  #pad(left: sign_left, block(width: 100%, spacing: _LEADING, align(center, signatory_name)))
  #for line in signatory_position.split("\n") {
    pad(left: sign_left, block(width: 100%, spacing: _LEADING, align(center, line)))
  }
]
