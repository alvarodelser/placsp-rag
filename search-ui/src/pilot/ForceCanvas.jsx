// search-ui/src/pilot/ForceCanvas.jsx — a force-directed graph on a canvas, after the instances
// graph of Projects/company_dataset (map/graph.js):
//  - what a thing is part of (a criterion of its lot, a lot of its tender, a document of its tender)
//    is a short, stiff spring, so what belongs together sits together; incidental links (a company
//    across tenders, a sector) are long and loose;
//  - a bid is drawn as the link it is, company to lot, not as a node of its own;
//  - a document hangs only from its tender: provenance is read in the document view, not drawn here;
//  - size grows with the logarithm of the links a node has, the subject (pinned) is largest;
//  - names are a budget, given first to what the pointer is on and what it reaches, then by links.
// Drag a node to move it, drag the background to pan, wheel to zoom, click to select, double-click to open.
import { useEffect, useMemo, useRef, useState } from 'react'
import { forceSimulation, forceLink, forceManyBody, forceCollide, forceX, forceY } from 'd3-force'
import { nodeInfo } from './labels.js'

const BELONGS = new Set(['HAS_LOT', 'HAS_CRITERION', 'REQUIRES', 'INCLUDES', 'HAS_RESULT', 'HAS_NOTICE', 'HAS_CONDITION',
  'HAS_DOCUMENT', 'WINNER', 'RESULTED_IN', 'DETAILED_BY', 'ACCEPTS', 'PUBLISHED', 'HAS_CONTRACT', 'CONTRACT_FOR'])
const DROP = new Set(['EXTRACTED_FROM', 'CONCERNS', 'NEXT_DOCUMENT', 'MENTIONED_IN', 'HAS_CHUNK', 'NEXT'])
const NAMES_PER_PX = 1 / 26000      // how many names a screen carries: one per this many square pixels

// Bids become company–lot links; provenance and sequence edges are left to the other views.
export function prepare(graph) {
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
  return { nodes: shown, edges }
}

export default function ForceCanvas({ graph, selected, onSelect, onOpen, pinned, height = 620, toolbar }) {
  const wrap = useRef(null), canvas = useRef(null)
  const st = useRef({ x: 0, y: 0, k: 1, hover: null, drag: null, pan: null, fitted: false, moved: false })
  const [hidden, setHidden] = useState(new Set())
  const [, redraw] = useState(0)
  st.current.selected = selected      // read by draw(), which the simulation calls on every tick
  st.current.pinned = pinned

  const { nodes, links, counts } = useMemo(() => {
    const g = prepare(graph)
    const keep = g.nodes.filter((n) => !hidden.has(n.label))
    const ids = new Set(keep.map((n) => n.id))
    const prev = Object.fromEntries((st.current.nodes || []).map((n) => [n.id, n]))
    const nodes = keep.map((n) => Object.assign(prev[n.id] || {}, n, { deg: 0 }))
    const links = g.edges.filter((e) => ids.has(e.src) && ids.has(e.dst)).map((e) => ({ ...e, source: e.src, target: e.dst }))
    const byId = Object.fromEntries(nodes.map((n) => [n.id, n]))
    for (const l of links) { byId[l.src].deg++; byId[l.dst].deg++ }
    const counts = {}
    for (const n of g.nodes) counts[n.label] = (counts[n.label] || 0) + 1
    return { nodes, links, counts }
  }, [graph, hidden])

  const radius = (n) => (n.label === 'Document' ? 3.5 : 4.5 + 2 * Math.log2(1 + n.deg)) * (n.id === pinned ? 2.2 : 1)

  useEffect(() => {
    const s = st.current
    s.nodes = nodes
    s.byId = Object.fromEntries(nodes.map((n) => [n.id, n]))
    s.adj = {}
    for (const l of links) { (s.adj[l.src] ||= new Set()).add(l.dst); (s.adj[l.dst] ||= new Set()).add(l.src) }
    for (const n of nodes) n.r = radius(n)
    const pin = nodes.find((n) => n.id === pinned)
    if (pin) { pin.fx = 0; pin.fy = 0 }
    const sim = forceSimulation(nodes)
      .force('link', forceLink(links).id((d) => d.id)
        .distance((l) => (BELONGS.has(l.rel) ? 26 : 90) + l.source.r + l.target.r)
        .strength((l) => (BELONGS.has(l.rel) ? 0.7 : 0.06)))
      .force('charge', forceManyBody().strength((n) => -40 - 6 * n.r).distanceMax(500))
      .force('collide', forceCollide((n) => n.r + 3))
      .force('x', forceX(0).strength(0.03)).force('y', forceY(0).strength(0.03))
      .alphaDecay(0.03)
      .on('tick', draw)
      .on('end', () => { if (!s.touched) { fit(); draw() } })   // settle, then frame it, unless the reader moved the view
    s.sim = sim
    s.links = links
    return () => sim.stop()
  }, [nodes, links, pinned]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { draw() }, [selected]) // eslint-disable-line react-hooks/exhaustive-deps

  function fit() {
    const s = st.current, c = canvas.current
    if (!c || !s.nodes?.length) return
    const xs = s.nodes.map((n) => n.x), ys = s.nodes.map((n) => n.y)
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
    const W = c.clientWidth, H = c.clientHeight
    s.k = Math.min(2, 0.9 * Math.min(W / Math.max(40, x1 - x0), H / Math.max(40, y1 - y0)))
    s.x = W / 2 - s.k * (x0 + x1) / 2
    s.y = H / 2 - s.k * (y0 + y1) / 2
  }

  function draw() {
    const s = st.current, c = canvas.current
    if (!c || !s.nodes) return
    const dpr = window.devicePixelRatio || 1, W = c.clientWidth, H = c.clientHeight
    if (c.width !== W * dpr) { c.width = W * dpr; c.height = H * dpr }
    if (!s.fitted && s.sim && s.sim.alpha() < 0.35) { fit(); s.fitted = true }
    const ctx = c.getContext('2d')
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, W, H)
    ctx.translate(s.x, s.y)
    ctx.scale(s.k, s.k)
    const focus = s.hover || (s.selected && s.byId[s.selected]) || null
    const near = focus ? new Set([focus.id, ...(s.adj[focus.id] || [])]) : null
    for (const l of s.links) {
      const on = near && (l.source.id === focus.id || l.target.id === focus.id)
      ctx.globalAlpha = on ? 0.9 : near ? 0.06 : BELONGS.has(l.rel) ? 0.35 : 0.16
      ctx.strokeStyle = on ? '#4f46e5' : l.rel === 'ADJUDICATARIA' ? '#1a7a4d' : '#8b95a7'
      ctx.lineWidth = (on ? 1.6 : l.rel === 'ADJUDICATARIA' ? 1.4 : 0.8) / Math.sqrt(s.k)
      ctx.beginPath(); ctx.moveTo(l.source.x, l.source.y); ctx.lineTo(l.target.x, l.target.y); ctx.stroke()
    }
    for (const n of s.nodes) {
      const col = nodeInfo(n.label).color
      ctx.globalAlpha = near && !near.has(n.id) ? 0.15 : 1
      ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2)
      ctx.fillStyle = n.source === 'documents' ? '#fff' : col
      ctx.fill()
      ctx.lineWidth = (n.id === s.selected ? 3 : 1.4) / s.k
      ctx.strokeStyle = n.id === s.selected ? '#161a23' : col
      ctx.stroke()
      if (n.source === 'feed+documents') {           // half-filled: feed and documents agree it exists
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r * 0.55, 0, Math.PI * 2); ctx.fillStyle = '#fff'; ctx.fill()
      }
    }
    // Names: a budget, first what is in focus, then the most connected.
    const budget = Math.max(8, Math.round(W * H * NAMES_PER_PX))
    const order = [...s.nodes].sort((a, b) => rank(b) - rank(a))
    function rank(n) { return (n.id === s.selected ? 1e7 : 0) + (near?.has(n.id) ? 1e6 : 0) + (n.id === s.pinned ? 1e5 : 0) + n.deg * 10 + n.r }
    ctx.globalAlpha = 1
    ctx.font = `${11 / s.k}px Inter, system-ui, sans-serif`
    ctx.textAlign = 'center'
    ctx.lineJoin = 'round'
    const taken = []
    let shown = 0
    for (const n of order) {
      if (shown >= budget) break
      if (near && !near.has(n.id) && n.id !== s.selected) continue
      const t = short(n)
      if (!t) continue
      const w = ctx.measureText(t).width, y = n.y + n.r + 12 / s.k
      const box = [n.x - w / 2, y - 10 / s.k, n.x + w / 2, y + 2 / s.k]
      if (taken.some((b) => !(box[2] < b[0] || box[0] > b[2] || box[3] < b[1] || box[1] > b[3]))) continue
      taken.push(box)
      ctx.lineWidth = 3 / s.k; ctx.strokeStyle = '#fbfcfe'; ctx.strokeText(t, n.x, y)
      ctx.fillStyle = '#161a23'; ctx.fillText(t, n.x, y)
      shown++
    }
  }

  function at(e) {
    const s = st.current, r = canvas.current.getBoundingClientRect()
    const x = (e.clientX - r.left - s.x) / s.k, y = (e.clientY - r.top - s.y) / s.k
    let best = null, bd = Infinity
    for (const n of s.nodes || []) {
      const d = Math.hypot(n.x - x, n.y - y)
      if (d < n.r + 4 / s.k && d < bd) { best = n; bd = d }
    }
    return { node: best, x, y }
  }
  function down(e) {
    const s = st.current, hit = at(e)
    s.moved = false
    if (hit.node) { s.drag = hit.node; hit.node.fx = hit.node.x; hit.node.fy = hit.node.y; s.sim.alphaTarget(0.2).restart() }
    else s.pan = { x: e.clientX - s.x, y: e.clientY - s.y }
  }
  function move(e) {
    const s = st.current
    if (s.drag) { const p = at(e); s.drag.fx = p.x; s.drag.fy = p.y; s.moved = true; return }
    if (s.pan) { s.x = e.clientX - s.pan.x; s.y = e.clientY - s.pan.y; s.moved = true; s.touched = true; draw(); return }
    const h = at(e).node
    if (h !== s.hover) { s.hover = h; canvas.current.style.cursor = h ? 'pointer' : 'grab'; draw() }
  }
  function up() {
    const s = st.current
    if (s.drag) {
      if (!s.moved) onSelect?.(s.drag.id)
      if (s.drag.id !== pinned) { s.drag.fx = null; s.drag.fy = null }
      s.sim.alphaTarget(0)
    }
    s.drag = null; s.pan = null
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
    <div className="pg" ref={wrap}>
      <div className="pg-legend">
        {toolbar}
        {Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([label, n]) => (
          <button key={label} type="button" className={`pg-key ${hidden.has(label) ? 'off' : ''}`}
            onClick={() => { setHidden((h) => { const x = new Set(h); x.has(label) ? x.delete(label) : x.add(label); return x }); redraw((v) => v + 1) }}>
            <i style={{ background: nodeInfo(label).color }} />{nodeInfo(label).es} <span>{n}</span>
          </button>
        ))}
        <button type="button" className="pg-key" onClick={() => { fit(); draw() }}>Encajar</button>
      </div>
      <canvas ref={canvas} className="fc" style={{ height }} onMouseDown={down} onMouseMove={move} onMouseUp={up}
        onMouseLeave={() => { up(); st.current.hover = null; draw() }}
        onDoubleClick={(e) => { const n = at(e).node; if (n) onOpen?.(n) }} />
    </div>
  )
}

function short(n) {
  if (n.label === 'Lot') return `Lote ${n.number || ''}`.trim()
  const s = n.name || n.title || ''
  return s.length > 30 ? `${s.slice(0, 28)}…` : s
}
