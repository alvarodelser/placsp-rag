// search-ui/src/pilot/ExploreView.jsx — the whole pilot as one graph: tenders, the authorities that
// publish them, the companies that bid for and win them, the qualifications they ask for and their
// sectors. Double-click a tender to unfold its own graph (lots, criteria, requirements, documents)
// in place; double-click a company to open it across expedientes.
import { useEffect, useState } from 'react'
import { corpusGraph, getTenderGraph } from './pilotApi.js'
import { CircleNotch } from '../icons.js'
import ForceCanvas from './ForceCanvas.jsx'
import NodePanel from './NodePanel.jsx'
import { go } from './route.js'

export default function ExploreView() {
  const [graph, setGraph] = useState(null)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)
  const [open, setOpen] = useState(new Set())

  useEffect(() => { corpusGraph().then(setGraph).catch((e) => setError(e.message)) }, [])

  async function unfold(n) {
    if (n.label === 'Organization') return go(`/c/${encodeURIComponent(n.id)}`)
    if (n.label !== 'Tender' || open.has(n.id)) return
    const sub = await getTenderGraph(n.id.replace(/^tender:/, ''))
    setOpen((o) => new Set([...o, n.id]))
    setGraph((g) => {
      const have = new Set(g.nodes.map((x) => x.id))
      const key = (e) => `${e.src}|${e.rel}|${e.dst}`
      const seen = new Set(g.edges.map(key))
      return { nodes: [...g.nodes, ...sub.nodes.filter((x) => !have.has(x.id))],
               edges: [...g.edges, ...sub.edges.filter((e) => !seen.has(key(e)))] }
    })
  }

  if (error) return <div className="err">{error}</div>
  if (!graph) return <div className="loading-state"><CircleNotch size={28} className="spinner" /></div>
  return (
    <div className="tv">
      <div className="tv-head">
        <h2>Explorar el piloto</h2>
        <p className="row">Expedientes, órganos, empresas, acreditaciones y sectores. Doble clic en un expediente para desplegar
          sus lotes, criterios, requisitos y documentos; doble clic en una empresa para verla en todos sus expedientes.
          {open.size > 0 && <> · {open.size} desplegados</>}</p>
      </div>
      <ForceCanvas graph={graph} selected={selected} onSelect={setSelected} onOpen={unfold} height={720} />
      {selected && !selected.startsWith('cpv:') && <NodePanel id={selected} onSelect={setSelected} onClose={() => setSelected(null)} />}
    </div>
  )
}
