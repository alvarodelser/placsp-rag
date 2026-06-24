/**
 * StatusDiagram — SVG flow diagram of the contract lifecycle.
 *
 * Main flow:  PRE → PUB → EV → ADJ → RES
 *                                      ↓
 *                             [L-elbow] → ANULADA
 *
 * The "any state → ANULADA" path is an L-shaped elbow of unspecified origin.
 */

// ── Layout ───────────────────────────────────────────────────────────
const VW = 660, VH = 205
const NW = 114, NH = 78, NR = 10
const COL = 132  // stride (NW + 18 gap)

// Node left-x positions
const nx   = (i) => 6 + i * COL
const ny   = 12
const ncx  = (i) => nx(i) + NW / 2   // center x
const ncy  = ny + NH / 2             // center y  ≈ 51
const nBot = ny + NH                  // bottom y  = 90

// ANULADA — directly below RES (col 4)
const ANUL_X = nx(4)   // = 534
const ANUL_Y = 117
const ANUL_W = NW      // same width as other nodes
const ANUL_H = 74
const ANUL_CX = ANUL_X + ANUL_W / 2  // = 591
const ANUL_CY = ANUL_Y + ANUL_H / 2  // ≈ 154

// L-elbow "from anywhere" entry point
const ELBOW_X = 430    // vertical leg x  (below main-flow, to the left of RES)
const ELBOW_Y1 = nBot + 8   // top of vertical leg  ≈ 98
const ELBOW_Y2 = ANUL_CY    // meets ANULADA at center-y ≈ 154

const FLOW = [
  { code: 'PRE',  label: 'Anuncio Previo', sub: 'Preaviso',           color: '#8b5cf6', bg: '#f5f0ff', border: '#c4b5fd' },
  { code: 'PUB',  label: 'En Plazo',       sub: 'Abierta a ofertas',  color: '#0ea5e9', bg: '#e0f5fe', border: '#7dd3fc' },
  { code: 'EV',   label: 'Evaluación',     sub: 'Pend. adj.',         color: '#f59e0b', bg: '#fef9ec', border: '#fcd34d' },
  { code: 'ADJ',  label: 'Adjudicada',     sub: 'Contrato adj.',      color: '#10b981', bg: '#e9faf3', border: '#6ee7b7' },
  { code: 'RES',  label: 'Resuelta',       sub: 'Finalizado',         color: '#1f7a4d', bg: '#d4f7e7', border: '#86efac' },
]
const ANUL = { code: 'ANUL', label: 'Anulada', sub: 'Proceso cancelado', color: '#ef4444', bg: '#fff1f1', border: '#fca5a5' }

// ── Helpers ──────────────────────────────────────────────────────────
function fmt(n) {
  if (!n) return null
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10_000 ? 0 : 1)}k`
  return n.toLocaleString('es-ES')
}


function Node({ node, x, y, w = NW, h = NH, active, count, onToggle }) {
  const label = fmt(count)
  const cx = x + w / 2
  const txtColor = active ? '#fff' : node.color
  const subColor = active ? 'rgba(255,255,255,.72)' : '#64748b'
  const cntColor = active ? 'rgba(255,255,255,.9)' : node.color

  // Vertical text layout
  const hasCount = label != null
  const ly  = y + (hasCount ? 23 : 30)
  const sy  = y + (hasCount ? 36 : 47)
  const cny = y + 52

  return (
    <g onClick={onToggle} style={{ cursor: 'pointer' }} role="button" aria-pressed={active}>
      {/* Drop shadow only when active */}
      {active && (
        <rect x={x + 2} y={y + 3} width={w} height={h} rx={NR}
          fill={node.color} opacity={0.18} />
      )}
      <rect
        x={x} y={y} width={w} height={h} rx={NR}
        fill={active ? node.color : node.bg}
        stroke={active ? node.color : node.border}
        strokeWidth={active ? 2.5 : 1.5}
        style={{ transition: 'fill .18s, stroke-width .18s' }}
      />
      {/* Inner highlight ring when active */}
      {active && (
        <rect x={x + 4} y={y + 4} width={w - 8} height={h - 8} rx={NR - 2}
          fill="none" stroke="rgba(255,255,255,.22)" strokeWidth={1} />
      )}
      <text x={cx} y={ly} textAnchor="middle"
        fontSize={11} fontWeight={700} fill={txtColor} fontFamily="inherit">
        {node.label}
      </text>
      <text x={cx} y={sy} textAnchor="middle"
        fontSize={8.5} fill={subColor} fontFamily="inherit">
        {node.sub}
      </text>
      {hasCount && (
        <text x={cx} y={cny} textAnchor="middle"
          fontSize={10.5} fontWeight={700} fill={cntColor} fontFamily="inherit">
          {label}
        </text>
      )}
    </g>
  )
}

// ── Main component ────────────────────────────────────────────────────
export default function StatusDiagram({ value = [], counts = {}, onChange }) {
  function toggle(code) {
    onChange(value.includes(code) ? value.filter((c) => c !== code) : [...value, code])
  }

  return (
    <div className="sd-wrap">
      <div className="sd-hint">Ciclo de vida — haz clic para filtrar por estado</div>
      <svg
        viewBox={`0 0 ${VW} ${VH}`}
        style={{ width: '100%', display: 'block', overflow: 'visible' }}
        aria-label="Diagrama del ciclo de vida del contrato"
      >
        <defs>
          {/* Shared minimal arrowhead — small, gray */}
          <marker id="sd-arr" markerWidth="6" markerHeight="5"
            refX="5" refY="2.5" orient="auto">
            <path d="M0,0 L6,2.5 L0,5 Z" fill="#94a3b8" />
          </marker>
          {/* Same shape, red for elbow */}
          <marker id="sd-arr-red" markerWidth="6" markerHeight="5"
            refX="5" refY="2.5" orient="auto">
            <path d="M0,0 L6,2.5 L0,5 Z" fill="#fca5a5" />
          </marker>
        </defs>

        {/* ── Sequential flow arrows — thin gray lines ── */}
        {FLOW.slice(0, 4).map((_, i) => (
          <line
            key={`flow${i}`}
            x1={nx(i) + NW + 1} y1={ncy}
            x2={nx(i + 1) - 1}  y2={ncy}
            stroke="#cbd5e1" strokeWidth={1}
            markerEnd="url(#sd-arr)"
          />
        ))}

        {/* ── RES → ANULADA (straight vertical, gray) ── */}
        <line
          x1={ANUL_CX} y1={nBot + 1}
          x2={ANUL_CX} y2={ANUL_Y - 1}
          stroke="#cbd5e1" strokeWidth={1}
          markerEnd="url(#sd-arr)"
        />

        {/* ── L-elbow "from any state" — thin dashed, muted red ── */}
        <polyline
          points={`${ELBOW_X},${ELBOW_Y1} ${ELBOW_X},${ELBOW_Y2} ${ANUL_X - 1},${ELBOW_Y2}`}
          fill="none"
          stroke="#fca5a5" strokeWidth={1}
          strokeDasharray="4 3"
          markerEnd="url(#sd-arr-red)"
        />
        {/* ··· floating origin hint */}
        <text x={ELBOW_X} y={ELBOW_Y1 - 5}
          textAnchor="middle" fontSize={9} fill="#fca5a5"
          letterSpacing="2" fontFamily="inherit">
          ···
        </text>
        {/* Label */}
        <text
          x={(ELBOW_X + ANUL_X) / 2} y={ELBOW_Y2 - 5}
          textAnchor="middle" fontSize={7.5} fill="#fca5a5"
          fontStyle="italic" fontFamily="inherit">
          desde cualquier estado
        </text>

        {/* ── Main flow node cards ── */}
        {FLOW.map((s, i) => (
          <Node
            key={s.code} node={s}
            x={nx(i)} y={ny}
            active={value.includes(s.code)}
            count={counts[s.code]}
            onToggle={() => toggle(s.code)}
          />
        ))}

        {/* ── ANULADA node (below RES) ── */}
        <Node
          node={ANUL}
          x={ANUL_X} y={ANUL_Y} w={ANUL_W} h={ANUL_H}
          active={value.includes(ANUL.code)}
          count={counts[ANUL.code]}
          onToggle={() => toggle(ANUL.code)}
        />
      </svg>
    </div>
  )
}
