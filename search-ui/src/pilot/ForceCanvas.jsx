// search-ui/src/pilot/ForceCanvas.jsx — the pilot's corpus as a force-directed graph on a canvas,
// drawn like an entity–relationship diagram:
//  - authorities (blue) and companies (green) are circles; a contract (expediente) is the small
//    graphite diamond between them, sized by its amount; its state is in the panel, not the map;
//  - every link is one graphite line: what a link means is plain from what it joins; a bid is
//    drawn as the link it is, company to lot, not as a node;
//  - a contract's documents are not on the map: selecting the contract unfolds them around it as
//    pages, and they fold away when something else is selected;
//  - contracts carry no name, only their expediente number once the reader has selected them,
//    remembered for a while (MEMORY_MS) and fading as it is forgotten;
//  - names are a budget for what is on screen, given first to what the pointer is on and what it
//    reaches, then by links; close up (few nodes in view) a name gets a line of detail.
// `highlight` (search hits) lights those nodes and their neighbours and frames them.
// Drag a node to move it, drag the background to pan, wheel to zoom, click to select, double-click to open.
import { useEffect, useMemo, useRef } from 'react'
import { forceSimulation, forceLink, forceManyBody, forceCollide, forceX, forceY } from 'd3-force'
import { nodeInfo, NOT_DRAWN, roleEs, shortOrg } from './labels.js'

const BELONGS = new Set(['HAS_LOT', 'HAS_CRITERION', 'REQUIRES', 'INCLUDES', 'HAS_RESULT', 'HAS_NOTICE', 'HAS_CONDITION',
  'WINNER', 'RESULTED_IN', 'DETAILED_BY', 'ACCEPTS', 'PUBLISHED', 'HAS_CONTRACT', 'CONTRACT_FOR'])
const DROP = new Set(['EXTRACTED_FROM', 'CONCERNS', 'NEXT_DOCUMENT', 'MENTIONED_IN', 'HAS_CHUNK', 'NEXT'])
const WON = new Set(['WINNER', 'ADJUDICATARIA', 'CONTRACTOR'])
const ORGS = new Set(['Organization', 'Company', 'Authority'])
const SHAPE = { Tender: 'diamond' }       // everything else is a circle
const C = { Authority: nodeInfo('Authority').color, Tender: nodeInfo('Tender').color, Company: nodeInfo('Company').color,
  doc: nodeInfo('Document').color, link: '#4b5563', ink: '#161a23', bg: '#fbfcfe' }
const NAMES_PER_PX = 1 / 26000      // how many names a screen carries: one per this many square pixels
const CLOSE = 25                    // nodes in view below which a name gets a line of detail
const UNFOLD_MS = 320, STAGGER_MS = 28
const MEMORY_MS = 10 * 60e3, MEMORY_MAX = 8

// The contracts the reader selected lately, oldest first: a short memory, kept while the page lives.
const recent = new Map()
function remember(id) {
  recent.delete(id); recent.set(id, Date.now())
  while (recent.size > MEMORY_MAX) recent.delete(recent.keys().next().value)
}
function recall(id) {           // 1 just selected … 0.4 about to be forgotten; 0 forgotten
  const t = recent.get(id)
  if (t == null) return 0
  const age = (Date.now() - t) / MEMORY_MS
  if (age >= 1) { recent.delete(id); return 0 }
  return 1 - 0.6 * age
}

// Bids become company–lot links; documents leave the map for their contract's list (docsOf);
// provenance and sequence edges are left to the other views.
export function prepare(graph) {
  const docs = Object.fromEntries(graph.nodes.filter((n) => n.label === 'Document').map((n) => [n.id, n]))
  const docsOf = {}
  for (const e of graph.edges) if (e.rel === 'HAS_DOCUMENT' && docs[e.dst]) (docsOf[e.src] ||= []).push({ ...docs[e.dst], seq: e.seq })
  for (const l of Object.values(docsOf)) l.sort((a, b) => (a.seq ?? 1e9) - (b.seq ?? 1e9))
  graph = { nodes: graph.nodes.filter((n) => !NOT_DRAWN.has(n.label) && n.label !== 'Document'), edges: graph.edges }
  const byId = Object.fromEntries(graph.nodes.map((n) => [n.id, n]))
  const bids = new Set(graph.nodes.filter((n) => n.label === 'Bid').map((n) => n.id))
  const by = (rel, side) => {
    const m = {}
    for (const e of graph.edges) if (e.rel === rel) (m[e[side]] ||= []).push(e[side === 'src' ? 'dst' : 'src'])
    return m
  }
  const bidders = by('SUBMITTED_BY', 'src'), lotsOf = { ...by('RECEIVED_BID', 'dst') }
  for (const [b, ls] of Object.entries(by('BID_FOR', 'src'))) lotsOf[b] = [...(lotsOf[b] || []), ...ls]
  const edges = [], asLink = new Set()
  for (const b of bids) {
    const os = bidders[b] || [], ls = lotsOf[b] || []
    if (!os.length || !ls.length) continue
    asLink.add(b)
    for (const o of os) for (const l of new Set(ls)) edges.push({ src: o, dst: l, rel: byId[b].winner ? 'ADJUDICATARIA' : 'OFERTA' })
  }
  for (const e of graph.edges) {
    if (DROP.has(e.rel) || asLink.has(e.src) || asLink.has(e.dst) || !byId[e.src] || !byId[e.dst]) continue
    edges.push(e)
  }
  // Authorities and companies are both organizations; on the map they are told apart.
  const shown = graph.nodes.filter((n) => !asLink.has(n.id)).map((n) => {
    if (n.label !== 'Organization') return n
    const k = n.kinds || []
    return { ...n, label: k.includes('Company') ? 'Company' : k.includes('ContractingAuthority') ? 'Authority' : 'Organization' }
  })
  return { nodes: shown, edges, docsOf }
}

export default function ForceCanvas({ graph, selected, onSelect, onOpen, height = 620, toolbar, highlight }) {
  const canvas = useRef(null)
  const st = useRef({ x: 0, y: 0, k: 1, hover: null, drag: null, pan: null, fitted: false, moved: false, sats: [] })
  st.current.selected = selected      // read by draw(), which the simulation calls on every tick
  st.current.highlight = highlight?.length ? new Set(highlight) : null

  const { nodes, links, docsOf, counts } = useMemo(() => {
    const g = prepare(graph)
    const prev = Object.fromEntries((st.current.nodes || []).map((n) => [n.id, n]))
    const all = g.nodes.map((n) => Object.assign(prev[n.id] || {}, n, { deg: 0 }))
    const ids = new Set(all.map((n) => n.id))
    const links = g.edges.filter((e) => ids.has(e.src) && ids.has(e.dst)).map((e) => ({ ...e, source: e.src, target: e.dst }))
    const byId = Object.fromEntries(all.map((n) => [n.id, n]))
    for (const l of links) { byId[l.src].deg++; byId[l.dst].deg++ }
    // Linked to nothing drawn (a company a document only mentions): listed in the panels, not drawn.
    const nodes = all.filter((n) => n.deg > 0 || n.label === 'Tender')
    const counts = {}
    for (const n of nodes) counts[n.label] = (counts[n.label] || 0) + 1
    return { nodes, links, docsOf: g.docsOf, counts }
  }, [graph])

  const radius = (n) => (n.label === 'Tender'
    ? 3 + Math.min(6, Math.max(0, (Math.log10(n.value || 1e4) - 4) * 1.5))
    : 5 + 2 * Math.log2(1 + n.deg))

  useEffect(() => {
    const s = st.current
    s.nodes = nodes
    s.docsOf = docsOf
    s.byId = Object.fromEntries(nodes.map((n) => [n.id, n]))
    s.adj = {}
    for (const l of links) { (s.adj[l.src] ||= new Set()).add(l.dst); (s.adj[l.dst] ||= new Set()).add(l.src) }
    for (const n of nodes) { n.r = radius(n); n.tenders = 0; n.won = new Set() }
    for (const l of links) {
      for (const [a, b] of [[l.src, l.dst], [l.dst, l.src]]) {
        const n = s.byId[a], m = s.byId[b]
        if (m.label === 'Tender') n.tenders++
        if (WON.has(l.rel) && n.label !== 'Tender' && n.label !== 'Lot') n.won.add(b)
      }
    }
    const sim = forceSimulation(nodes)
      .force('link', forceLink(links).id((d) => d.id)
        .distance((l) => (BELONGS.has(l.rel) ? 26 : 90) + l.source.r + l.target.r)
        .strength((l) => (BELONGS.has(l.rel) ? 0.7 : 0.06)))
      .force('charge', forceManyBody().strength((n) => -40 - 6 * n.r).distanceMax(500))
      .force('collide', forceCollide((n) => n.r * 1.25 + 3))
      .force('x', forceX(0).strength(0.03)).force('y', forceY(0).strength(0.03))
      .alphaDecay(0.03)
      .on('tick', draw)
      .on('end', () => { if (!s.touched) { fit(s.highlight ? lit(s) : null); draw() } })   // settle, then frame it, unless the reader moved the view
    s.sim = sim
    s.links = links
    return () => sim.stop()
  }, [nodes, links]) // eslint-disable-line react-hooks/exhaustive-deps

  // Selecting a contract unfolds its documents and remembers it; selecting one of those documents
  // keeps them unfolded; anything else folds them away.
  useEffect(() => {
    const s = st.current
    const n = s.byId?.[selected]
    if (n?.label === 'Tender') {
      if (s.exp?.id !== n.id) s.exp = { id: n.id, t0: performance.now() }
      remember(n.id)
      reveal(n)
    } else if (!s.sats.some((d) => d.id === selected)) s.exp = null
    draw()
  }, [selected]) // eslint-disable-line react-hooks/exhaustive-deps
  // New search hits: frame them and what they touch (once the layout exists), else the whole graph.
  useEffect(() => {
    const s = st.current
    if (!s.nodes) return
    s.touched = false
    fit(s.highlight ? lit(s) : null)
    draw()
  }, [highlight]) // eslint-disable-line react-hooks/exhaustive-deps
  // Remembered numbers fade as time passes, without the reader doing anything.
  useEffect(() => { const t = setInterval(draw, 30e3); return () => clearInterval(t) }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function lit(s) {
    const out = new Set()
    for (const id of s.highlight || []) {
      if (!s.byId[id]) continue
      out.add(id)
      for (const m of s.adj[id] || []) out.add(m)
    }
    return out
  }

  // Slide the view so a selected contract and its documents are clear of the panel over the canvas.
  function reveal(n) {
    const s = st.current, c = canvas.current
    if (!c || n.x == null) return
    const cr = c.getBoundingClientRect(), panel = document.querySelector('.np')?.getBoundingClientRect()
    const right = panel && panel.left < cr.right ? panel.left - cr.left : cr.width
    const m = (n.r * 1.3 + 60) * s.k, px = n.x * s.k + s.x, py = n.y * s.k + s.y
    const dx = px + m > right ? right - m - px : px - m < 0 ? m - px : 0
    const dy = py + m > cr.height ? cr.height - m - py : py - m < 0 ? m - py : 0
    if (!dx && !dy) return
    const x0 = s.x, y0 = s.y, t0 = performance.now()
    const step = () => {
      const p = ease(Math.min(1, (performance.now() - t0) / 360))
      s.x = x0 + dx * p; s.y = y0 + dy * p; draw()
      if (p < 1) requestAnimationFrame(step)
    }
    s.touched = true
    requestAnimationFrame(step)
  }

  function fit(only) {
    const s = st.current, c = canvas.current
    const ns = only?.size ? s.nodes.filter((n) => only.has(n.id)) : s.nodes
    if (!c || !ns?.length || ns.some((n) => n.x == null)) return
    const xs = ns.map((n) => n.x), ys = ns.map((n) => n.y)
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
    const W = c.clientWidth, H = c.clientHeight
    s.k = Math.min(1.3, 0.9 * Math.min(W / Math.max(40, x1 - x0), H / Math.max(40, y1 - y0)))
    s.x = W / 2 - s.k * (x0 + x1) / 2
    s.y = H / 2 - s.k * (y0 + y1) / 2
  }

  function draw() {
    const s = st.current, c = canvas.current
    if (!c || !s.nodes) return
    const dpr = window.devicePixelRatio || 1, W = c.clientWidth, H = c.clientHeight
    if (c.width !== W * dpr) { c.width = W * dpr; c.height = H * dpr }
    if (!s.fitted && s.sim && s.sim.alpha() < 0.35) { fit(s.highlight ? lit(s) : null); s.fitted = true }
    const ctx = c.getContext('2d')
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, W, H)
    ctx.translate(s.x, s.y)
    ctx.scale(s.k, s.k)
    const k = s.k
    const sat = (n) => n?.label === 'Document'
    const asNode = (n) => (sat(n) ? s.byId[n.tender] : n)        // a document stands for its contract
    const focus = asNode(s.hover) || asNode(s.byId[s.selected] || s.sats.find((d) => d.id === s.selected)) || null
    const hits = !focus && s.highlight ? new Set([...s.highlight].filter((id) => s.byId[id])) : null
    const near = focus ? new Set([focus.id, ...(s.adj[focus.id] || [])]) : hits ? lit(s) : null

    for (const l of s.links) {
      const on = focus ? (l.source.id === focus.id || l.target.id === focus.id)
        : hits ? (hits.has(l.source.id) || hits.has(l.target.id)) && near.has(l.source.id) && near.has(l.target.id) : false
      ctx.globalAlpha = on ? 0.9 : near ? 0.05 : 0.22
      ctx.strokeStyle = C.link
      ctx.lineWidth = (on ? 1.6 : 1) / Math.sqrt(k)
      ctx.beginPath(); ctx.moveTo(l.source.x, l.source.y); ctx.lineTo(l.target.x, l.target.y); ctx.stroke()
    }

    for (const n of s.nodes) {
      ctx.globalAlpha = near && !near.has(n.id) ? 0.15 : 1
      if (hits?.has(n.id)) {                         // a search hit: a halo
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r * 1.3 + 5 / k, 0, Math.PI * 2); ctx.fillStyle = '#fde68a'; ctx.fill()
      }
      const col = n.label === 'Tender' ? C.Tender : n.label === 'Authority' ? C.Authority : C.Company
      if (n.id === s.selected || n.id === s.exp?.id) {
        outline(ctx, n, n.r + 4 / k); ctx.lineWidth = 2 / k; ctx.strokeStyle = C.ink; ctx.stroke()
      }
      outline(ctx, n, n.r)
      ctx.fillStyle = col; ctx.fill()
      ctx.lineWidth = 1.5 / k; ctx.strokeStyle = '#fff'; ctx.stroke()      // a rim keeps touching shapes apart
    }

    // The selected contract's documents, unfolding around it.
    s.sats = []
    const t = s.exp && s.byId[s.exp.id]
    if (t) {
      const docs = s.docsOf[t.id] || []
      const age = performance.now() - s.exp.t0
      const R = t.r * 1.3 + 30 + Math.max(0, docs.length - 8) * 2.6
      docs.forEach((d, i) => {
        const p = ease(Math.min(1, Math.max(0, (age - i * STAGGER_MS) / UNFOLD_MS)))
        const a = -Math.PI / 2 + (2 * Math.PI * i) / docs.length
        s.sats.push({ ...d, label: 'Document', tender: t.id, a, p, r: 5.5, x: t.x + Math.cos(a) * R * p, y: t.y + Math.sin(a) * R * p })
      })
      for (const d of s.sats) {
        ctx.globalAlpha = 0.5 * d.p
        ctx.strokeStyle = C.doc; ctx.lineWidth = 0.8 / k
        ctx.beginPath(); ctx.moveTo(t.x, t.y); ctx.lineTo(d.x, d.y); ctx.stroke()
      }
      ctx.font = `${9.5 / k}px Inter, system-ui, sans-serif`
      for (const d of s.sats) {
        const on = d.id === s.selected || d.id === s.hover?.id
        ctx.globalAlpha = d.p
        page(ctx, { x: d.x, y: d.y, r: d.r * (0.4 + 0.6 * d.p) * (on ? 1.3 : 1) }, C.doc, (on ? 2.2 : 1.2) / k)
        const cx = Math.cos(d.a), cy = Math.sin(d.a)
        const tx = d.x + cx * (d.r + 4 / k), ty = d.y + cy * (d.r + 4 / k) + 3.5 / k
        ctx.textAlign = cx > 0.3 ? 'left' : cx < -0.3 ? 'right' : 'center'
        const txt = on ? `${roleEs(d.role)} · ${cut(d.title || '', 40)}` : roleEs(d.role)
        halo(ctx, txt, tx, cy > 0.3 ? ty + 4 / k : cy < -0.3 ? ty - 4 / k : ty, on ? C.ink : '#475569', k)
      }
      if (age < UNFOLD_MS + docs.length * STAGGER_MS && !s.raf) s.raf = requestAnimationFrame(() => { s.raf = 0; draw() })
    }

    // Names: a budget for what is on screen, first what is in focus, then the most connected.
    // A contract is named only by its expediente number, and only once the reader has selected it.
    const x0 = -s.x / k, y0 = -s.y / k, x1 = (W - s.x) / k, y1 = (H - s.y) / k
    const inView = s.nodes.filter((n) => n.x >= x0 && n.x <= x1 && n.y >= y0 && n.y <= y1)
    const close = inView.length <= CLOSE
    const budget = Math.max(8, Math.round(W * H * NAMES_PER_PX / (close ? 2 : 1)))
    const order = inView.sort((a, b) => rank(b) - rank(a))
    function rank(n) { return (n.id === s.selected ? 1e7 : 0) + (hits?.has(n.id) ? 2e6 : 0) + (near?.has(n.id) ? 1e6 : 0) + n.deg * 10 + n.r }
    ctx.textAlign = 'center'
    ctx.lineJoin = 'round'
    const taken = s.sats.map((d) => [d.x - 30 / k, d.y - 10 / k, d.x + 30 / k, d.y + 10 / k])
    let shown = 0
    for (const n of order) {
      if (shown >= budget) break
      if (near && !near.has(n.id)) continue
      let t, sub = '', alpha = 1, mono = false
      if (n.label === 'Tender') {
        if (n.id === s.exp?.id) continue                  // on its pill, below
        alpha = n.id === s.selected || n.id === s.hover?.id ? 1 : recall(n.id)
        if (!alpha) continue
        t = n.expediente || n.id.replace(/^tender:/, ''); mono = true
      } else if (ORGS.has(n.label)) {
        t = shortOrg(n.name, close ? 44 : 26)
        sub = close ? detail(n) : ''
      } else continue
      if (!t) continue
      const y = n.y + n.r * 1.25 + 12 / k
      const font = mono ? `600 ${10.5 / k}px "IBM Plex Mono", ui-monospace, Menlo, monospace` : `${11 / k}px Inter, system-ui, sans-serif`
      ctx.font = font
      let w = ctx.measureText(t).width
      if (sub) { ctx.font = `${10 / k}px Inter, system-ui, sans-serif`; w = Math.max(w, ctx.measureText(sub).width) }
      const box = [n.x - w / 2, y - 10 / k, n.x + w / 2, y + (sub ? 14 : 2) / k]
      if (taken.some((b) => !(box[2] < b[0] || box[0] > b[2] || box[3] < b[1] || box[1] > b[3]))) continue
      taken.push(box)
      ctx.globalAlpha = alpha
      ctx.font = font
      halo(ctx, t, n.x, y, mono ? C.Tender : C.ink, k)
      if (sub) { ctx.font = `${10 / k}px Inter, system-ui, sans-serif`; halo(ctx, sub, n.x, y + 12 / k, '#5b6474', k) }
      shown++
    }
    // The selected contract's number, always, on a pill inside its ring of documents.
    if (t) {
      const label = t.expediente || t.id.replace(/^tender:/, '')
      ctx.globalAlpha = 1
      ctx.font = `600 ${10.5 / k}px "IBM Plex Mono", ui-monospace, Menlo, monospace`
      const w = ctx.measureText(label).width + 10 / k, h = 15 / k, y = t.y + t.r * 1.3 + 5 / k
      ctx.beginPath(); ctx.roundRect ? ctx.roundRect(t.x - w / 2, y, w, h, h / 2) : ctx.rect(t.x - w / 2, y, w, h)
      ctx.fillStyle = C.Tender; ctx.fill()
      ctx.fillStyle = '#fff'; ctx.textAlign = 'center'; ctx.fillText(label, t.x, y + 11 / k)
    }
    ctx.globalAlpha = 1
  }

  function at(e) {
    const s = st.current, r = canvas.current.getBoundingClientRect()
    const x = (e.clientX - r.left - s.x) / s.k, y = (e.clientY - r.top - s.y) / s.k
    let best = null, bd = Infinity
    for (const n of [...s.sats, ...(s.nodes || [])]) {
      const d = Math.hypot(n.x - x, n.y - y)
      if (d < n.r * 1.25 + 4 / s.k && d < bd) { best = n; bd = d }
    }
    return { node: best, x, y }
  }
  function down(e) {
    const s = st.current, hit = at(e)
    s.moved = false
    if (hit.node?.label === 'Document') s.press = hit.node
    else if (hit.node) { s.drag = hit.node; hit.node.fx = hit.node.x; hit.node.fy = hit.node.y; s.sim.alphaTarget(0.2).restart() }
    else s.pan = { x: e.clientX - s.x, y: e.clientY - s.y }
  }
  function move(e) {
    const s = st.current
    if (s.drag) { const p = at(e); s.drag.fx = p.x; s.drag.fy = p.y; s.moved = true; return }
    if (s.pan) { s.x = e.clientX - s.pan.x; s.y = e.clientY - s.pan.y; s.moved = true; s.touched = true; draw(); return }
    const h = at(e).node
    if (h?.id !== s.hover?.id) { s.hover = h; canvas.current.style.cursor = h ? 'pointer' : 'grab'; draw() }
  }
  function up() {
    const s = st.current
    if (s.press) onSelect?.(s.press.id)
    if (s.pan && !s.moved) onSelect?.(null)          // a click on the background lets go of the selection
    if (s.drag) {
      if (!s.moved) onSelect?.(s.drag.id)
      s.drag.fx = null; s.drag.fy = null
      s.sim.alphaTarget(0)
    }
    s.drag = null; s.pan = null; s.press = null
  }
  useEffect(() => {
    const c = canvas.current
    const wheel = (e) => {
      e.preventDefault()
      const s = st.current, r = c.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top
      const k = Math.min(6, Math.max(0.15, s.k * (e.deltaY < 0 ? 1.12 : 0.89)))
      s.x = mx - (mx - s.x) * k / s.k; s.y = my - (my - s.y) * k / s.k; s.k = k; s.touched = true
      draw()
    }
    c.addEventListener('wheel', wheel, { passive: false })
    return () => c.removeEventListener('wheel', wheel)
  }) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="pg">
      <Legend counts={counts}>
        {toolbar}
        <button type="button" className="pg-key" onClick={() => { fit(); draw() }}>Encajar</button>
      </Legend>
      <canvas ref={canvas} className="fc" style={{ height }} onMouseDown={down} onMouseMove={move} onMouseUp={up}
        onMouseLeave={() => { up(); st.current.hover = null; draw() }}
        onDoubleClick={(e) => { const n = at(e).node; if (n) onOpen?.(n) }} />
    </div>
  )
}

// The legend: what each mark is, nothing more.
function Legend({ counts, children }) {
  const n = (k) => counts[k] ? <span className="pg-n">{counts[k]}</span> : null
  return (
    <div className="pg-legend">
      <span className="pg-ent"><Glyph kind="Authority" />Órgano de contratación{n('Authority')}</span>
      <span className="pg-ent"><Glyph kind="Tender" />Expediente{n('Tender')}</span>
      <span className="pg-ent"><Glyph kind="Company" />Empresa{n('Company')}</span>
      <span className="pg-tools">{children}</span>
    </div>
  )
}

function Glyph({ kind }) {
  const col = kind === 'Tender' ? C.Tender : kind === 'Authority' ? C.Authority : C.Company
  return (
    <svg className="pg-glyph" viewBox="0 0 16 16" aria-hidden="true">
      {kind === 'Tender' ? <path d="M8 3 13 8 8 13 3 8Z" fill={col} /> : <circle cx="8" cy="8" r="6" fill={col} />}
    </svg>
  )
}

// A node's outline: a diamond for a contract, else a circle.
function outline(ctx, n, r) {
  const shape = SHAPE[n.label]
  ctx.beginPath()
  if (shape === 'diamond') {
    const d = r * 1.2
    ctx.moveTo(n.x, n.y - d); ctx.lineTo(n.x + d, n.y); ctx.lineTo(n.x, n.y + d); ctx.lineTo(n.x - d, n.y); ctx.closePath()
  } else ctx.arc(n.x, n.y, r, 0, Math.PI * 2)
}

// A document is a page with a folded corner, not a dot.
function page(ctx, n, col, lw) {
  const w = n.r * 1.5, h = n.r * 2, f = w * 0.4, x = n.x - w / 2, y = n.y - h / 2
  ctx.beginPath()
  ctx.moveTo(x, y); ctx.lineTo(x + w - f, y); ctx.lineTo(x + w, y + f); ctx.lineTo(x + w, y + h); ctx.lineTo(x, y + h); ctx.closePath()
  ctx.fillStyle = '#fff'; ctx.fill(); ctx.lineWidth = lw; ctx.strokeStyle = col; ctx.stroke()
  ctx.beginPath(); ctx.moveTo(x + w - f, y); ctx.lineTo(x + w - f, y + f); ctx.lineTo(x + w, y + f); ctx.stroke()
}

function halo(ctx, t, x, y, fill, k) {
  ctx.lineWidth = 3 / k; ctx.strokeStyle = C.bg; ctx.strokeText(t, x, y)
  ctx.fillStyle = fill; ctx.fillText(t, x, y)
}

const ease = (p) => 1 - (1 - p) ** 3
const cut = (s, m) => (s.length > m ? `${s.slice(0, m - 1)}…` : s)

// The second line a name gets close up: what makes the organization worth a look.
function detail(n) {
  const exp = (k) => `${k} exp.`
  if (n.label === 'Authority') return n.tenders ? exp(n.tenders) : ''
  return [n.tenders && exp(n.tenders), n.won.size && `${n.won.size} adjudicad${n.won.size === 1 ? 'o' : 'os'}`].filter(Boolean).join(' · ')
}

