// search-ui/src/pilot/OriginalPane.jsx — the stored original beside the text the pipeline read.
// PDFs render with pdf.js, page by page as they scroll into view; `target` ({page, quote}) scrolls
// to a page and marks the quote on it, found in the page's own text layer. A web page (a PLACSP
// notice) shows in a sandbox; other formats (.doc, .docx…) can only be downloaded.
import { useEffect, useRef, useState } from 'react'
import PdfWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?worker'
import { fileUrl } from './pilotApi.js'
import { CircleNotch } from '../icons.js'

let pdfjs = null
async function lib() {
  if (!pdfjs) {
    pdfjs = await import('pdfjs-dist')
    // A bundled worker (a .js file): nginx serves .mjs as application/octet-stream, which a
    // module worker refuses.
    pdfjs.GlobalWorkerOptions.workerPort = new PdfWorker()
  }
  return pdfjs
}

export default function OriginalPane({ sha, ext, target, onPage }) {
  const kind = (ext || '').toLowerCase()
  if (kind === 'pdf') return <PdfPane sha={sha} target={target} onPage={onPage} />
  if (kind === 'html' || kind === 'htm') return <HtmlPane sha={sha} target={target} />
  return (
    <div className="op-empty">
      <p>Un documento <b>.{kind || '?'}</b> no se puede mostrar en el navegador.</p>
      <a href={fileUrl(sha)} download>Descargar el original</a>
    </div>
  )
}

// A published notice: its HTML without scripts, in a frame that can run none ("allow-same-origin"
// only lets this page reach in to mark the quote and scroll to it).
function HtmlPane({ sha, target }) {
  const frame = useRef(null)
  const [html, setHtml] = useState(null)
  const [ready, setReady] = useState(0)
  useEffect(() => {
    let live = true
    fetch(fileUrl(sha), { credentials: 'include' }).then((r) => r.text())
      .then((t) => live && setHtml(t.replace(/<script[\s\S]*?<\/script>/gi, '').replace(/\son\w+="[^"]*"/gi, '')))
      .catch(() => live && setHtml(''))
    return () => { live = false }
  }, [sha])
  useEffect(() => {
    const doc = frame.current?.contentDocument
    if (!doc?.body || !target?.quote) return
    doc.querySelectorAll('mark[data-hl] > span').forEach((t) => t.remove())       // the old tag, then its frame
    doc.querySelectorAll('mark[data-hl]').forEach((m) => m.replaceWith(...m.childNodes))
    const words = norm(target.quote).split(' ').slice(0, 8).join(' ')
    const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT)
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (!norm(n.textContent).includes(words)) continue
      const m = doc.createElement('mark')
      m.dataset.hl = '1'
      m.style.cssText = 'position:relative;display:inline-block;background:#fffdf5;border:2px solid #d97706;border-radius:6px;padding:16px 6px 4px'
      if (target.tag) {
        const t = doc.createElement('span')
        t.textContent = target.tag
        t.style.cssText = 'position:absolute;top:0;left:0;background:#d97706;color:#fff;font:700 10.5px system-ui,sans-serif;padding:1px 7px 2px;border-radius:4px 0 6px 0'
        m.appendChild(t)
      }
      n.replaceWith(m); m.appendChild(n)
      m.scrollIntoView({ block: 'center' })
      break
    }
  }, [target, ready])
  if (html == null) return <div className="op-empty"><CircleNotch size={22} className="spinner" /></div>
  return <iframe ref={frame} className="op-frame" title="Original" srcDoc={html} sandbox="allow-same-origin" referrerPolicy="no-referrer"
    onLoad={() => setReady((x) => x + 1)} />
}

const norm = (s) => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, ' ').trim()

function PdfPane({ sha, target, onPage }) {
  const box = useRef(null)
  const st = useRef({ doc: null, pages: [], rendered: new Map(), width: 0 })
  const [info, setInfo] = useState({ status: 'loading' })
  const [current, setCurrent] = useState(1)

  useEffect(() => {
    let live = true
    const s = st.current
    s.rendered = new Map()
    ;(async () => {
      try {
        const lib_ = await lib()
        const doc = await lib_.getDocument({ url: fileUrl(sha), withCredentials: true }).promise
        if (!live) return
        const first = await doc.getPage(1)
        s.doc = doc
        s.ratio = first.getViewport({ scale: 1 }).height / first.getViewport({ scale: 1 }).width
        setInfo({ status: 'done', n: doc.numPages })
      } catch (e) {
        if (live) setInfo({ status: 'error', e: e.message })
      }
    })()
    return () => { live = false; s.doc?.destroy(); s.doc = null }
  }, [sha])

  // Render what comes into view; track the page at the top for the counter.
  useEffect(() => {
    if (info.status !== 'done') return
    const root = box.current
    const io = new IntersectionObserver((es) => {
      for (const e of es) if (e.isIntersecting) render(Number(e.target.dataset.page))
    }, { root, rootMargin: '600px 0px' })
    root.querySelectorAll('.op-page').forEach((el) => io.observe(el))
    const onScroll = () => {
      const pages = [...root.querySelectorAll('.op-page')]
      const top = root.scrollTop + 40
      const p = pages.find((el) => el.offsetTop + el.offsetHeight > top)
      if (p) setCurrent(Number(p.dataset.page))
    }
    root.addEventListener('scroll', onScroll, { passive: true })
    return () => { io.disconnect(); root.removeEventListener('scroll', onScroll) }
  }, [info]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { onPage?.(current) }, [current]) // eslint-disable-line react-hooks/exhaustive-deps

  // A target: to its page, then the quote marked once the page has its text.
  useEffect(() => {
    if (info.status !== 'done' || !target?.page) return
    const el = box.current.querySelector(`.op-page[data-page="${target.page}"]`)
    if (el) box.current.scrollTo({ top: el.offsetTop - 8, behavior: target.follow ? 'auto' : 'smooth' })
    if (target.follow) return                         // following the text: keep the last mark
    box.current.querySelectorAll('.op-hl').forEach((x) => x.remove())
    if (target.quote) {
      ;(async () => {
        for (const p of [target.page, target.page + 1, target.page - 1]) {
          if (p < 1 || p > info.n) continue
          await render(p)
          if (await mark(p, target.quote, target.tag)) {
            const hl = box.current.querySelector(`.op-page[data-page="${p}"] .op-hl`)
            if (hl) box.current.scrollTo({ top: hl.parentElement.offsetTop + hl.offsetTop - 120, behavior: 'smooth' })
            return
          }
        }
      })()
    }
  }, [target, info]) // eslint-disable-line react-hooks/exhaustive-deps

  async function render(n) {
    const s = st.current
    if (!s.doc) return
    if (s.rendered.has(n)) return s.rendered.get(n)
    const job = (async () => {
      const page = await s.doc.getPage(n)
      const el = box.current?.querySelector(`.op-page[data-page="${n}"]`)
      if (!el) return null
      const width = el.clientWidth
      const base = page.getViewport({ scale: 1 })
      const vp = page.getViewport({ scale: width / base.width })
      const dpr = window.devicePixelRatio || 1
      const canvas = document.createElement('canvas')
      canvas.width = Math.floor(vp.width * dpr); canvas.height = Math.floor(vp.height * dpr)
      canvas.style.width = `${vp.width}px`; canvas.style.height = `${vp.height}px`
      el.style.height = `${vp.height}px`
      el.querySelector('canvas')?.remove()
      el.prepend(canvas)
      await page.render({ canvasContext: canvas.getContext('2d'), viewport: vp, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null }).promise
      const text = await page.getTextContent()
      return { page, vp, items: text.items.filter((it) => 'str' in it) }
    })()
    s.rendered.set(n, job)
    return job
  }

  // The quote's words found in the page's text items (spacing and accents aside); the items it
  // covers get a box. A long quote is matched by its first words.
  async function mark(n, quote, tag) {
    const r = await st.current.rendered.get(n)
    if (!r) return false
    let flat = ''
    const spans = []
    for (const [i, it] of r.items.entries()) {
      const t = norm(it.str)
      if (!t) continue
      spans.push([flat.length, flat.length + t.length, i])
      flat += `${t} `
    }
    const words = norm(quote).split(' ')
    for (const len of [words.length, 12, 6]) {
      const q = words.slice(0, Math.min(len, words.length)).join(' ')
      if (q.length < 4) continue
      const at = flat.indexOf(q)
      if (at < 0) continue
      // One rectangle around everything the reference covers, its tag on the top left.
      const el = box.current.querySelector(`.op-page[data-page="${n}"]`)
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
      for (const [a, b, i] of spans) {
        if (b <= at || a >= at + q.length) continue
        const it = r.items[i]
        const tx = pdfjs.Util.transform(r.vp.transform, it.transform)
        const h = Math.hypot(tx[2], tx[3]), w = it.width * r.vp.scale
        x0 = Math.min(x0, tx[4]); x1 = Math.max(x1, tx[4] + w); y0 = Math.min(y0, tx[5] - h); y1 = Math.max(y1, tx[5] + h * 0.25)
      }
      if (x0 === Infinity) return false
      const d = document.createElement('div')
      d.className = 'op-hl'
      Object.assign(d.style, { left: `${x0 - 4}px`, top: `${y0 - 4}px`, width: `${x1 - x0 + 8}px`, height: `${y1 - y0 + 8}px` })
      if (tag) {
        const t = document.createElement('span')
        t.className = 'ref-tag'
        t.textContent = tag
        d.appendChild(t)
      }
      el.appendChild(d)
      return true
    }
    return false
  }

  if (info.status === 'loading') return <div className="op-empty"><CircleNotch size={22} className="spinner" /></div>
  if (info.status === 'error') return <div className="op-empty err">No se pudo abrir el PDF: {info.e}</div>
  return (
    <div className="op">
      <div className="op-bar">
        <span>Página <b>{current}</b> de {info.n}</span>
        <a href={fileUrl(sha, current)} target="_blank" rel="noreferrer">Abrir aparte ↗</a>
      </div>
      <div className="op-scroll" ref={box}>
        {Array.from({ length: info.n }, (_, i) => (
          <div key={i} className="op-page" data-page={i + 1} style={{ aspectRatio: `1 / ${st.current.ratio || 1.414}` }}>
            <span className="op-num">{i + 1}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
