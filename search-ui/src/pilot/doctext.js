// search-ui/src/pilot/doctext.js — reading the text the pipeline extracted, without moving a
// character: every transformation keeps the string's length, so mention offsets stay valid.

// A PDF breaks lines where the page ran out, not where the sentence ends. A break is joined (made a
// space) when the line before does not close a sentence or a heading and the next line continues
// it: starts in lower case, or the line before is long and the next one is not a list item.
const ENDS = /[.:;!?»”)]\s*$/
const ITEM = /^\s*(?:[•·\-–—*]|\(?[a-z0-9]{1,3}[.)]\s|\d+(?:\.\d+)*\.?\s|[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ]{6,}$|\[Página)/

// Symbol-font bullets come out of PDFs as private-use characters (drawn as boxes): one bullet each.
const PRIVATE = /[\uE000-\uF8FF]/g

export function reflow(text, keys) {
  const lines = text.replace(PRIVATE, '•').split('\n')
  let out = ''
  for (let i = 0; i < lines.length; i++) {
    out += lines[i]
    if (i === lines.length - 1) break
    const cur = lines[i], nxt = lines[i + 1]
    const fixed = keys?.size && (keys.has(lineKey(cur)) || keys.has(lineKey(nxt)))    // a page's footer stays a line
    const value = /^\s*:/.test(nxt)                                   // a notice's "Label" / ": value"
    const soft = !fixed && cur.trim() && nxt.trim() && (value || (!ENDS.test(cur) && !ITEM.test(nxt) &&
      (/^\s*[a-záéíóúñü(]/.test(nxt) || cur.trim().length >= 55)))
    out += soft ? ' ' : '\n'
  }
  return out
}

// The same key the API gives repeated lines: numbers and spacing out, lower case.
export const lineKey = (line) => line.replace(/\d+/g, '#').replace(/\s+/g, ' ').trim().toLowerCase()

// [a, b) ranges of the lines of `text` whose key is in `keys`.
export function lineKeyRanges(text, keys) {
  if (!keys?.size) return []
  const out = []
  let at = 0
  for (const line of text.split('\n')) {
    if (keys.has(lineKey(line))) out.push({ a: at, b: at + line.length })
    at += line.length + 1
  }
  return out
}

// The reflowed text as blocks to lay out, each an [a, b) range of it (so mentions still land):
//   page     "[Página 3]" on its own line
//   heading  a short line that opens a section: after a blank line, in capitals, numbered ("1.2 ",
//            "3. "), or just before a notice's fields ("Contacto"); `sub` for the last kind
//   field    a notice's "Label" line and its indented value lines ("Número de Expediente\n 192/2026"),
//            or one line "Ponderación  : 100" / "Sitio Web   http://…"
//   item     a bullet or "a)" / "1." line
//   para     consecutive other lines, up to a blank line
const PAGE_LINE = /^\s*\[Página (\d+)\]\s*$/
const BULLET = /^\s*(?:[•·\-–—*]\s|\(?[a-z0-9]{1,3}[.)]\s)/
// Capitals and spaces, two words at least: "CLÁUSULA TERCERA", not "ES300" or "GARCIA, JESUS".
const CAPS = /^[A-ZÁÉÍÓÚÑÜ()ºª-]+(?:\s+[A-ZÁÉÍÓÚÑÜ()ºª-]+)+$/
// "1.2 División", "3. Objeto": a dotted number, so "30 Día(s)" is not one.
const NUMBERED = /^(?:\d+\.(?:\d+\.?)*)\s+[A-ZÁÉÍÓÚÑ]/
// "Label : value" (a notice, or reflow's join of "Label\n: value") and "Label   value".
const INLINE = /^(\s*)([A-ZÁÉÍÓÚÑ][^:.]{1,59}?)(?:\s+:\s*|\s{3,})(\S.*?)\s*$/
const INDENTED = /^[ \t]+\S/

export function blocks(text) {
  const lines = []
  let at = 0
  for (const s of text.split('\n')) { lines.push({ s, t: s.trim(), a: at, b: at + s.length }); at += s.length + 1 }
  const out = []
  let para = null, blank = true
  const close = () => { if (para) out.push(para); para = null }
  for (let i = 0; i < lines.length; i++) {
    const { s, t, a, b } = lines[i]
    if (!t) { close(); blank = true; continue }
    const pg = PAGE_LINE.exec(s)
    if (pg) { close(); out.push({ type: 'page', a, b, page: Number(pg[1]) }); blank = true; continue }
    const nxt = lines[i + 1]
    if (!INDENTED.test(s) && t.length <= 70 && nxt && INDENTED.test(nxt.s)) {
      close()
      let j = i + 1
      while (lines[j + 1] && INDENTED.test(lines[j + 1].s)) j++
      out.push({ type: 'field', a, b: lines[j].b, la: a, lb: b, va: nxt.a, vb: lines[j].b })
      i = j; blank = false; continue
    }
    const inline = INLINE.exec(s)
    if (inline) {
      close()
      const la = a + inline[1].length, va = a + s.lastIndexOf(inline[3], s.length - (s.length - s.trimEnd().length))
      out.push({ type: 'field', a, b, la, lb: la + inline[2].length, va, vb: va + inline[3].length })
      blank = false; continue
    }
    const heading = t.length <= 80 && !/[.,;]$/.test(t) && !BULLET.test(s) &&
      (CAPS.test(t) && t.length >= 4 || NUMBERED.test(t) || (blank && t.length <= 60 && /^[A-ZÁÉÍÓÚÑ¿¡]/.test(t) && nxt?.t))
    if (heading) { close(); out.push({ type: 'heading', a, b }); blank = false; continue }
    if (BULLET.test(s)) { close(); out.push({ type: 'item', a, b }); blank = false; continue }
    if (para) para.b = b
    else para = { type: 'para', a, b }
    blank = false
  }
  close()
  // A short last line of a paragraph right before fields titles them ("Contacto", "Clasificación
  // CPV"), unless the paragraph is the content of the heading just above it.
  const titled = []
  out.forEach((x, i) => {
    if (x.type !== 'para' || out[i + 1]?.type !== 'field') return titled.push(x)
    const last = text.lastIndexOf('\n', x.b - 1) + 1
    const line = text.slice(Math.max(last, x.a), x.b)
    const whole = last <= x.a
    if (line.trim().length > 50 || !/^\s*[A-ZÁÉÍÓÚÑ][^.:;,]*$/.test(line) || (whole && out[i - 1]?.type === 'heading')) return titled.push(x)
    if (!whole) titled.push({ ...x, b: last - 1 })
    titled.push({ type: 'heading', sub: true, a: Math.max(last, x.a), b: x.b })
  })
  return titled
}
