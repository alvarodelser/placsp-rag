// search-ui/src/pilot/GraphView.jsx — one tender's subgraph, two ways:
//  - Carriles: documents | expediente and lots | what the pliegos set | result and companies, so
//    the structure reads at a glance; dashed blue edges are provenance (which document says it).
//  - Red: the same graph laid out with d3-force, for exploring neighbourhoods.
// Filled nodes come from the feed, outlined ones only from documents, half-filled from both.
import { useMemo, useRef, useState } from 'react'
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide, forceX, forceY } from 'd3-force'
import { nodeInfo } from './labels.js'

const W = 960, H = 640
// Labels hidden by default on large graphs: they dominate the count and hide the structure.
const NOISY = ['AwardCriterion', 'Requirement']

function layout(nodes, edges) {
  const ns = nodes.map((n) => ({ ...n }))
  const ids = new Set(ns.map((n) => n.id))
  const ls = edges.filter((e) => ids.has(e.src) && ids.has(e.dst)).map((e) => ({ ...e, source: e.src, target: e.dst }))
  const deg = {}
  ls.forEach((l) => { deg[l.source] = (deg[l.source] || 0) + 1; deg[l.target] = (deg[l.target] || 0) + 1 })
  ns.forEach((n) => { n.r = n.label === 'Tender' ? 14 : Math.min(11, 4 + Math.sqrt(deg[n.id] || 1) * 1.6) })
  const sim = forceSimulation(ns)
    .force('link', forceLink(ls).id((d) => d.id).distance((l) => (l.rel === 'NEXT_DOCUMENT' ? 30 : 55)).strength(0.5))
    .force('charge', forceManyBody().strength(-140).distanceMax(400))
    .force('collide', forceCollide((d) => d.r + 3))
    .force('center', forceCenter(W / 2, H / 2))
    .force('x', forceX(W / 2).strength(0.04))
    .force('y', forceY(H / 2).strength(0.06))
    .stop()
  for (let i = 0; i < 260; i++) sim.tick()
  // Fit the finished layout into the frame.
  const xs = ns.map((n) => n.x), ys = ns.map((n) => n.y)
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
  const k = Math.min(2, (W - 80) / Math.max(1, x1 - x0), (H - 70) / Math.max(1, y1 - y0))
  ns.forEach((n) => { n.x = W / 2 + (n.x - (x0 + x1) / 2) * k; n.y = H / 2 + (n.y - (y0 + y1) / 2) * k })
  return { nodes: ns, links: ls }
}

export default function GraphView(props) {
  const [mode, setMode] = useState('lanes')
  const modes = (
    <span className="pg-modes">
      <button type="button" className={mode === 'lanes' ? 'on' : ''} onClick={() => setMode('lanes')}>Carriles</button>
      <button type="button" className={mode === 'net' ? 'on' : ''} onClick={() => setMode('net')}>Red</button>
    </span>
  )
  return mode === 'lanes' ? <LaneView {...props} modes={modes} /> : <NetworkView {...props} modes={modes} />
}

const LANES = [
  ['Documentos', ['Document']],
  ['Expediente', ['Tender', 'Lot', 'Notice', 'Guarantee', 'ExecutionCondition', 'Modification']],
  ['Pliegos', ['AwardCriterion', 'Requirement', 'TechnicalRequirement', 'Qualification', 'TeamProfile', 'Deliverable', 'Penalty']],
  ['Resultado y empresas', ['Result', 'Bid', 'Contract', 'Organization', 'JointVenture']],
]
const LANE_OF = Object.fromEntries(LANES.flatMap(([, labels], i) => labels.map((l) => [l, i])))
const LW = 270, ROW = 24, TOP = 44

function fill(n) {
  const c = nodeInfo(n.label).color
  return n.source === 'documents' ? '#fff' : n.source === 'feed+documents' ? `url(#half-${n.label})` : c
}

function LaneView({ graph, selected, onSelect, modes }) {
  const { pos, height, edges, labels } = useMemo(() => {
    const seqOf = {}
    graph.edges.forEach((e) => { if (e.rel === 'HAS_DOCUMENT') seqOf[e.dst] = e.seq })
    const lanes = LANES.map(() => [])
    graph.nodes.forEach((n) => lanes[LANE_OF[n.label] ?? 2].push(n))
    const order = (n) => [LANES[LANE_OF[n.label] ?? 2][1].indexOf(n.label), seqOf[n.id] ?? 0, n.number ? Number(n.number) || 0 : 0, (n.name || n.title || '').toLowerCase()]
    const cmp = (a, b) => { const x = order(a), y = order(b); for (let i = 0; i < x.length; i++) { if (x[i] < y[i]) return -1; if (x[i] > y[i]) return 1 } return 0 }
    const pos = {}
    lanes.forEach((ns, li) => ns.sort(cmp).forEach((n, i) => { pos[n.id] = { x: 16 + li * LW, y: TOP + i * ROW, n } }))
    const height = TOP + Math.max(...lanes.map((l) => l.length), 1) * ROW + 20
    const edges = graph.edges.filter((e) => pos[e.src] && pos[e.dst] && e.rel !== 'NEXT_DOCUMENT')
    return { pos, height, edges, labels: [...new Set(graph.nodes.map((n) => n.label))] }
  }, [graph])

  const near = useMemo(() => {
    if (!selected) return null
    const s = new Set([selected])
    edges.forEach((e) => { if (e.src === selected) s.add(e.dst); if (e.dst === selected) s.add(e.src) })
    return s
  }, [selected, edges])

  function path(e) {
    const a = pos[e.src], b = pos[e.dst]
    const [l, r] = a.x <= b.x ? [a, b] : [b, a]
    if (l.x === r.x) {   // same lane: an arc on the left
      return `M${l.x},${l.y} C${l.x - 40},${l.y} ${r.x - 40},${r.y} ${r.x},${r.y}`
    }
    const x1 = l.x + 8, x2 = r.x - 8, mx = (x1 + x2) / 2
    return `M${x1},${l.y} C${mx},${l.y} ${mx},${r.y} ${x2},${r.y}`
  }

  return (
    <div className="pg">
      <div className="pg-legend">
        {modes}
        <span className="pg-note">relleno = feed · medio = feed + documentos · contorno = solo documentos · azul discontinuo = documento que lo menciona</span>
      </div>
      <div className="lanes-wrap">
        <svg viewBox={`0 0 ${16 + LANES.length * LW} ${height}`} style={{ width: '100%', minWidth: 900, display: 'block' }} role="img" aria-label="Grafo del expediente por carriles">
          <defs>
            {labels.map((l) => (
              <linearGradient key={l} id={`half-${l}`} x1="0" x2="1" y1="0" y2="0">
                <stop offset="50%" stopColor={nodeInfo(l).color} /><stop offset="50%" stopColor="#fff" />
              </linearGradient>
            ))}
          </defs>
          {LANES.map(([title], i) => <text key={title} className="lane-title" x={16 + i * LW} y={22}>{title}</text>)}
          {edges.map((e, i) => {
            const on = near && (e.src === selected || e.dst === selected)
            const prov = e.rel === 'EXTRACTED_FROM'
            if (prov && !on) return null   // provenance shows for the selected node only
            return <path key={i} d={path(e)} className={`lane-edge ${prov ? 'prov' : ''} ${on ? 'on' : near ? 'off' : ''}`}><title>{e.rel}</title></path>
          })}
          {Object.values(pos).map(({ x, y, n }) => (
            <g key={n.id} className={`lane-node ${near && !near.has(n.id) ? 'dim' : ''}`} transform={`translate(${x},${y})`} onClick={() => onSelect(n.id)}>
              <circle r={n.label === 'Tender' ? 7 : 5} fill={fill(n)} stroke={nodeInfo(n.label).color} strokeWidth={n.id === selected ? 3 : 1.5} />
              <text x={10} y={4}>{laneLabel(n)}</text>
              <title>{`${nodeInfo(n.label).es}: ${n.name || n.title || n.id}`}</title>
            </g>
          ))}
        </svg>
      </div>
    </div>
  )
}

function laneLabel(n) {
  if (n.label === 'Lot') return `Lote ${n.number || ''} ${n.name ? '· ' + n.name : ''}`.slice(0, 38)
  if (n.label === 'Notice') return `${n.type_label || n.type || 'Anuncio'} · ${n.published || ''}`.slice(0, 38)
  if (n.label === 'Result') return `Resultado: ${n.result || n.status || ''}`.slice(0, 38)
  const s = n.label === 'Document' ? `${n.title || n.filename || ''}` : (n.name || n.title || '')
  const pts = n.label === 'AwardCriterion' && n.points != null ? ` · ${n.points} pts` : ''
  const t = s.length > 34 - pts.length ? `${s.slice(0, 32 - pts.length)}…` : s
  return t + pts
}

function NetworkView({ graph, selected, onSelect, modes }) {
  const counts = useMemo(() => {
    const c = {}
    graph.nodes.forEach((n) => { c[n.label] = (c[n.label] || 0) + 1 })
    return Object.entries(c).sort((a, b) => b[1] - a[1])
  }, [graph])
  const [hidden, setHidden] = useState(() => new Set(graph.nodes.length > 150 ? NOISY : []))
  const [view, setView] = useState({ x: 0, y: 0, k: 1 })
  const drag = useRef(null)

  const visible = useMemo(() => graph.nodes.filter((n) => n.label === 'Tender' || !hidden.has(n.label)), [graph, hidden])
  const { nodes, links } = useMemo(() => layout(visible, graph.edges), [visible, graph.edges])

  const lotCount = nodes.filter((n) => n.label === 'Lot').length
  const orgCount = nodes.filter((n) => n.label === 'Organization').length
  const near = useMemo(() => {
    if (!selected) return null
    const s = new Set([selected])
    links.forEach((l) => {
      if (l.source.id === selected) s.add(l.target.id)
      if (l.target.id === selected) s.add(l.source.id)
    })
    return s
  }, [selected, links])

  function toggle(label) {
    setHidden((h) => { const n = new Set(h); n.has(label) ? n.delete(label) : n.add(label); return n })
  }
  function onWheel(e) {
    const k = Math.min(4, Math.max(0.3, view.k * (e.deltaY < 0 ? 1.12 : 0.89)))
    setView((v) => ({ ...v, k }))
  }

  return (
    <div className="pg">
      <div className="pg-legend">
        {modes}
        {counts.map(([label, n]) => (
          <button key={label} type="button" className={`pg-key ${hidden.has(label) ? 'off' : ''}`}
            onClick={() => label !== 'Tender' && toggle(label)} title={hidden.has(label) ? 'Mostrar' : 'Ocultar'}>
            <i style={{ background: nodeInfo(label).color }} />{nodeInfo(label).es} <span>{n}</span>
          </button>
        ))}
        <span className="pg-note">relleno = feed · contorno = extraído de documentos</span>
      </div>
      <svg className="pg-svg" viewBox={`0 0 ${W} ${H}`} onWheel={onWheel}
        onMouseDown={(e) => { drag.current = { x: e.clientX, y: e.clientY, v: view } }}
        onMouseMove={(e) => {
          if (!drag.current) return
          const s = W / e.currentTarget.getBoundingClientRect().width
          setView({ ...drag.current.v, x: drag.current.v.x + (e.clientX - drag.current.x) * s, y: drag.current.v.y + (e.clientY - drag.current.y) * s })
        }}
        onMouseUp={() => { drag.current = null }} onMouseLeave={() => { drag.current = null }}
        role="img" aria-label="Grafo del expediente">
        <g transform={`translate(${view.x + (W / 2) * (1 - view.k)},${view.y + (H / 2) * (1 - view.k)}) scale(${view.k})`}>
          {links.map((l, i) => (
            <line key={i} x1={l.source.x} y1={l.source.y} x2={l.target.x} y2={l.target.y}
              className={`pg-edge ${near && !(near.has(l.source.id) && near.has(l.target.id)) ? 'dim' : ''} ${l.rel === 'NEXT_DOCUMENT' ? 'chain' : ''}`}>
              <title>{l.rel}</title>
            </line>
          ))}
          {nodes.map((n) => {
            const c = nodeInfo(n.label).color
            const fromDoc = n.source === 'documents'
            return (
              <g key={n.id} transform={`translate(${n.x},${n.y})`} className={`pg-node ${near && !near.has(n.id) ? 'dim' : ''}`}
                onMouseDown={(e) => e.stopPropagation()} onClick={() => onSelect(n.id)}>
                <circle r={n.r} fill={fromDoc ? '#fff' : c} stroke={c} strokeWidth={fromDoc ? 2 : 1}
                  className={n.id === selected ? 'sel' : ''} />
                {(n.label === 'Tender' || n.id === selected || (near && near.has(n.id)) || (n.label === 'Lot' && lotCount <= 12) || (n.label === 'Organization' && orgCount <= 15)) && (
                  <text y={n.r + 11} textAnchor="middle">{short(n)}</text>
                )}
                <title>{`${nodeInfo(n.label).es}: ${n.name || n.title || n.id}`}</title>
              </g>
            )
          })}
        </g>
      </svg>
    </div>
  )
}

function short(n) {
  if (n.label === 'Lot') return `Lote ${n.number || ''}`.trim()
  const s = n.name || n.title || ''
  return s.length > 28 ? `${s.slice(0, 26)}…` : s
}
