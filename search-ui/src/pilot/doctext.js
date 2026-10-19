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
