/**
 * StatusDiagram — SVG flow diagram of the contract lifecycle.
 *
 * Main flow:  PRE → PUB → EV → ADJ → RES
 * Escape:     PRE, PUB, EV, ADJ  → ANULADA  (dashed red bus)
 */

// ── Layout ───────────────────────────────────────────────────────────
const VW = 660, VH = 210
const NW = 114, NH = 78, NR = 10
const COL = 132   // horizontal stride (NW + 18px gap)

const FLOW = [
  { code: 'PRE',  label: 'Anuncio Previo', sub: 'Preaviso',            color: '#8b5cf6', bg: '#f5f0ff' },
  { code: 'PUB',  label: 'En Plazo',       sub: 'Abierta a ofertas',   color: '#0ea5e9', bg: '#e0f5fe' },
  { code: 'EV',   label: 'Evaluación',     sub: 'Pend. adjudicación',  color: '#f59e0b', bg: '#fef9ec' },
  { code: 'ADJ',  label: 'Adjudicada',     sub: 'Contrato adj.',       color: '#10b981', bg: '#e9faf3' },
  { code: 'RES',  label: 'Resuelta',       sub: 'Proceso finalizado',  color: '#1f7a4d', bg: '#d4f7e7' },
]
const ANUL = { code: 'ANUL', label: 'Anulada', sub: 'Proceso cancelado', color: '#ef4444', bg: '#fff1f1' }

// Node geometry helpers
const nx  = (i) => 6 + i * COL        // left x of node i
const ny  = 12                         // top y of all main nodes
const ncx = (i) => nx(i) + NW / 2     // center x of node i
const ncy = ny + NH / 2               // center y  (= 51)
const nBot = ny + NH                   // bottom y  (= 90)

// ANULADA geometry (centered under the bus)
const BUS_Y   = 120
const ANUL_W  = 176, ANUL_H = 68, ANUL_R = 10
const ANUL_X  = (VW - ANUL_W) / 2     // centered in viewbox
const ANUL_Y  = 137
const ANUL_CX = ANUL_X + ANUL_W / 2   // = 330  (close enough to bus midpoint)

const GRAY = '#94a3b8'
const RED  = '#fca5a5'

// ── Helpers ──────────────────────────────────────────────────────────
function fmt(n) {
  if (!n) return null
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10_000 ? 0 : 1)}k`
  return n.toLocaleString('es-ES')
}

function Arrow({ x1, y1, x2, y2, marker = 'url(#sd-arr)', dashed = false, color = GRAY }) {
  return (
    <line
      x1={x1} y1={y1} x2={x2} y2={y2}
      stroke={color} strokeWidth={1.6}
      strokeDasharray={dashed ? '5 3.5' : undefined}
      markerEnd={marker}
    />
  )
}

function Node({ node, x, y, w = NW, h = NH, active, count, onToggle }) {
  const label = fmt(count)
  const textColor = active ? '#fff' : node.color
  const subColor  = active ? 'rgba(255,255,255,.7)' : '#64748b'
  const cx = x + w / 2

  // Vertical text distribution: label at ~28%, sub at ~50%, count at ~72%
  const hasCount = label != null
  const ly  = y + (hasCount ? 24 : 30)
  const sy  = y + (hasCount ? 37 : 47)
  const cny = y + 53

  return (
    <g
      onClick={onToggle}
      style={{ cursor: 'pointer' }}
      aria-pressed={active}
      role="button"
    >
      <rect
        x={x} y={y} width={w} height={h} rx={NR}
        fill={active ? node.color : node.bg}
        stroke={node.color}
        strokeWidth={active ? 2.5 : 1.5}
        style={{ transition: 'all .15s' }}
      />
      {/* Subtle inner glow when active */}
      {active && (
        <rect x={x+3} y={y+3} width={w-6} height={h-6} rx={NR-2}
          fill="none" stroke="rgba(255,255,255,.25)" strokeWidth={1} />
      )}
      <text x={cx} y={ly} textAnchor="middle"
        fontSize={11.5} fontWeight={700} fill={textColor} fontFamily="inherit">
        {node.label}
      </text>
      <text x={cx} y={sy} textAnchor="middle"
        fontSize={9} fill={subColor} fontFamily="inherit">
        {node.sub}
      </text>
      {hasCount && (
        <text x={cx} y={cny} textAnchor="middle"
          fontSize={10.5} fontWeight={700} fill={active ? 'rgba(255,255,255,.9)' : node.color} fontFamily="inherit">
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

  // Bus midpoint x (between PRE-center and ADJ-center)
  const busLeft  = ncx(0)   // 63
  const busRight = ncx(3)   // 399
  const busMidX  = Math.round((busLeft + busRight) / 2)  // ~231; we route via ANUL_CX instead

  return (
    <div className="sd-wrap">
      <div className="sd-hint">Ciclo de vida — haz clic para filtrar</div>
      <svg
        viewBox={`0 0 ${VW} ${VH}`}
        style={{ width: '100%', display: 'block', overflow: 'visible' }}
        aria-label="Diagrama del ciclo de vida del contrato"
      >
        <defs>
          {/* Gray arrowhead — sequential flow */}
          <marker id="sd-arr" markerWidth="8" markerHeight="7"
            refX="6" refY="3.5" orient="auto">
            <path d="M0,0 L0,7 L8,3.5 z" fill={GRAY} />
          </marker>
          {/* Red arrowhead — escape to ANULADA */}
          <marker id="sd-arr-red" markerWidth="8" markerHeight="7"
            refX="6" refY="3.5" orient="auto">
            <path d="M0,0 L0,7 L8,3.5 z" fill="#ef4444" />
          </marker>
        </defs>

        {/* ── Sequential flow arrows (horizontal between main nodes) ── */}
        {FLOW.slice(0, 4).map((_, i) => (
          <Arrow key={`flow${i}`}
            x1={nx(i) + NW + 1} y1={ncy}
            x2={nx(i + 1) - 2}  y2={ncy}
            color={GRAY} marker="url(#sd-arr)"
          />
        ))}

        {/* ── Vertical drops from PRE, PUB, EV, ADJ down to bus line ── */}
        {[0, 1, 2, 3].map((i) => (
          <Arrow key={`drop${i}`}
            x1={ncx(i)} y1={nBot + 1}
            x2={ncx(i)} y2={BUS_Y}
            color={RED} marker={undefined} dashed
          />
        ))}

        {/* ── Horizontal bus line ── */}
        <line
          x1={busLeft} y1={BUS_Y}
          x2={busRight} y2={BUS_Y}
          stroke={RED} strokeWidth={1.6} strokeDasharray="5 3.5"
        />

        {/* ── "desde cualquier estado" label on the bus ── */}
        <text
          x={busLeft + (busRight - busLeft) / 2} y={BUS_Y - 5}
          textAnchor="middle" fontSize={8.5} fill={RED}
          fontStyle="italic" fontFamily="inherit"
        >
          desde cualquier estado
        </text>

        {/* ── Connector from bus to ANULADA ── */}
        <line
          x1={ANUL_CX} y1={BUS_Y}
          x2={ANUL_CX} y2={ANUL_Y - 2}
          stroke="#ef4444" strokeWidth={1.6}
          markerEnd="url(#sd-arr-red)"
        />

        {/* ── Main flow nodes ── */}
        {FLOW.map((s, i) => (
          <Node
            key={s.code} node={s}
            x={nx(i)} y={ny}
            active={value.includes(s.code)}
            count={counts[s.code]}
            onToggle={() => toggle(s.code)}
          />
        ))}

        {/* ── ANULADA node (wider, centered below) ── */}
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
