// search-ui/src/pilot/GraphView.jsx — one tender's subgraph, two ways:
//  - Red: a force-directed canvas (ForceCanvas.jsx), the tender pinned in the middle.
//  - Carriles: documents | expediente and lots | what the pliegos set | result and companies, so
//    the structure reads at a glance; dashed blue edges are provenance (which document says it).
// Filled nodes come from the feed, outlined ones only from documents, half-filled from both.
import { useMemo, useState } from 'react'
import { nodeInfo } from './labels.js'
import ForceCanvas from './ForceCanvas.jsx'


export default function GraphView(props) {
  const [mode, setMode] = useState('net')
  const modes = (
    <span className="pg-modes">
      <button type="button" className={mode === 'net' ? 'on' : ''} onClick={() => setMode('net')}>Red</button>
      <button type="button" className={mode === 'lanes' ? 'on' : ''} onClick={() => setMode('lanes')}>Carriles</button>
    </span>
  )
  const tender = props.graph.nodes.find((n) => n.label === 'Tender')?.id
  return mode === 'lanes' ? <LaneView {...props} modes={modes} />
    : <ForceCanvas graph={props.graph} selected={props.selected} onSelect={props.onSelect} pinned={tender} toolbar={modes} />
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

