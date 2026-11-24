// project.typ — แบบเสนอโครงการของกรุงเทพมหานคร (รูปแบบการเขียนโครงการ กทม.)
// ชื่อโครงการ / หน่วยงาน / ปีงบประมาณ · เส้นประคั่น · หัวข้อ ๑–๑๐ (ตัวหนา) · ตารางแผนปฏิบัติการ งบประมาณ
// ความเสี่ยง ตัวชี้วัด (14 pt) · ลงชื่อผู้เสนอ/ผู้อนุมัติโครงการ
// ขอบ บน 2.5 ล่าง 2 ซ้าย 3 ขวา 2 ซม. — ข้อมูลทั้งหมดมาจาก core.project.project_view (Word ใช้ชุดเดียวกัน)

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
#let _secret_label(secret) = if secret == "top_secret" { "ลับที่สุด" } else if secret == "very_secret" { "ลับมาก" } else { "ลับ" }
#let _urgency_label(urgency) = if urgency == "most_urgent" { "ด่วนที่สุด" } else if urgency == "very_urgent" { "ด่วนมาก" } else { "ด่วน" }

#let _lines(items) = {
  for b in items {
    par[#h(b.indent * 1cm)#b.text]
  }
}

#let govdoc_project(
  view: (:),
  label_width: 2.7cm,
  sign_left: 6cm,
  table_size: 14pt,
  plan_step: 5.6cm,
  plan_fill: rgb("#BFBFBF"),
  budget_cols: (3.2cm, 7cm, 2.6cm, 3.2cm),
  risk_cols: (4.2cm, 1.9cm, 1.9cm, 2cm, 6cm),
  kpi_cols: (4cm, 2.3cm, 2.3cm, 4.9cm, 2.5cm),
  urgency: "normal",
  secret: "normal",
  thai_page_numbers: false,
  font: "TH SarabunPSK",
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
  #set par(leading: _LEADING, spacing: _LEADING, justify: true, first-line-indent: 0pt)
  #set table(stroke: 0.5pt, inset: (x: 3pt, y: 3pt))

  #if urgency != "normal" {
    place(top + left, dy: -1.2cm, text(size: 32pt, weight: "bold", fill: _RED, _urgency_label(urgency)))
  }

  // ส่วนหัว: ป้ายตัวหนา + ข้อความ (บรรทัดถัดไปเริ่มตรงข้อความ)
  #for (label, value) in view.head {
    grid(columns: (label_width, 1fr), row-gutter: 0pt, text(weight: "bold", label), par(justify: false, value))
  }
  #v(4pt)
  #line(length: 100%, stroke: (thickness: 0.6pt, dash: "dashed"))

  #let cell_text(body, al: left) = align(al, par(justify: false, body))
  #let head_cell(body, ..args) = table.cell(align: center + horizon, ..args,
                                            par(justify: false, text(weight: "bold", body)))

  #for b in view.blocks {
    // หัวข้อติดกับส่วนถัดไปเสมอ (sticky) — ไม่ค้างท้ายหน้าโดยที่ตารางขึ้นหน้าใหม่
    if b.type == "heading" {
      v(6pt)
      block(sticky: true, par(justify: false, text(weight: "bold", b.text)))
    } else if b.type == "sub" {
      block(sticky: true, par(justify: false)[#h(2.5cm)#text(weight: "bold", b.text)])
    } else if b.type == "usub" {
      block(sticky: true, par(justify: false)[#h(2.5cm)#underline(b.text)])
    } else if b.type == "lines" {
      _lines(b.lines)
    } else if b.type == "plan" {
      v(4pt)
      set text(size: table_size)
      table(
        columns: (plan_step, ..range(12).map(_ => 1fr)),
        table.header(
          head_cell([ขั้นตอนการดำเนินงาน], rowspan: 2),
          head_cell([ปีงบประมาณ พ.ศ. #b.year], colspan: 12),
          ..b.months.map(m => head_cell(text(size: table_size - 2pt, m))),
        ),
        ..b.rows.map(r => (
          cell_text(r.step),
          ..r.months.map(on => table.cell(fill: if on { plan_fill } else { none }, [])),
        )).flatten(),
      )
    } else if b.type == "budget" {
      v(4pt)
      set text(size: table_size)
      let body = ()
      for r in b.rows {
        if r.span > 0 {
          body.push(table.cell(rowspan: r.span, cell_text(r.activity)))
        }
        body.push(pad(left: (r.level - 1) * 0.4cm, cell_text(r.item)))
        body.push(cell_text(r.amount, al: right))
        body.push(cell_text(r.law))
      }
      table(
        columns: budget_cols,
        table.header(..b.heads.map(h => head_cell(h))),
        ..body,
        table.cell(colspan: 2, cell_text(text(weight: "bold", b.total_label), al: center)),
        cell_text(text(weight: "bold", b.total), al: right),
        [],
      )
      v(4pt)
    } else if b.type == "risks" {
      v(4pt)
      set text(size: table_size)
      table(
        columns: risk_cols,
        table.header(
          head_cell([ความเสี่ยง], rowspan: 2),
          head_cell([การประเมินความเสี่ยง], colspan: 3),
          head_cell([แนวทางการบริหารความเสี่ยง], rowspan: 2),
          head_cell([โอกาสที่จะเกิด]), head_cell([ผลกระทบ]), head_cell([ระดับของความเสี่ยง]),
        ),
        ..b.rows.map(r => (
          cell_text(r.risk), cell_text(r.likelihood, al: center), cell_text(r.impact, al: center),
          cell_text(r.level, al: center), cell_text(r.mitigation),
        )).flatten(),
      )
    } else if b.type == "kpis" {
      v(2pt)
      set text(size: table_size)
      table(
        columns: kpi_cols,
        table.header(..b.heads.map(h => head_cell(h))),
        ..b.rows.map(r => (
          cell_text(r.indicator), cell_text(r.target, al: center), cell_text(r.kind, al: center),
          cell_text(r.method), cell_text(r.period, al: center),
        )).flatten(),
      )
      v(2pt)
    }
  }

  // ลงชื่อผู้เสนอ / ผู้อนุมัติโครงการ — กึ่งกลางในช่วง sign_left ถึงขอบขวา
  #set par(justify: false)
  #for s in view.signers {
    v(1.5cm)
    pad(left: sign_left, block(width: 100%, breakable: false, stack(
      spacing: _LEADING,
      align(center, s.line), align(center, s.name), align(center, s.position),
    )))
  }
]
