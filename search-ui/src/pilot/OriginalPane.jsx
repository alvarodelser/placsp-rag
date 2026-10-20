// search-ui/src/pilot/OriginalPane.jsx — the original where it was published (PLACSP), in a frame:
// the pilot keeps no copy. A PDF opens at `page` (the browser's viewer reads #page=N); a notice
// shows as published; other formats (.doc, .docx, .zip…) can only be downloaded from there, and
// a file that came inside an archive (`archive`) only as that archive.
import { ArrowUpRight } from '../icons.js'

const FRAMED = new Set(['pdf', 'html', 'htm', 'txt', 'png', 'jpg', 'jpeg'])

export default function OriginalPane({ url, ext, page, title, archive = false }) {
  const kind = (ext || '').toLowerCase()
  if (!url) return <div className="op-empty"><p>Este documento no tiene enlace al original.</p></div>
  if (archive) {
    return (
      <div className="op-empty">
        <p>Este documento venía dentro de un archivo comprimido publicado en la Plataforma.</p>
        <a href={url} target="_blank" rel="noreferrer">Descargar el archivo <ArrowUpRight size={13} className="ico" /></a>
      </div>
    )
  }
  if (!FRAMED.has(kind)) {
    return (
      <div className="op-empty">
        <p>Un documento <b>.{kind || '?'}</b> no se puede mostrar en el navegador.</p>
        <a href={url} target="_blank" rel="noreferrer">Descargarlo de la Plataforma <ArrowUpRight size={13} className="ico" /></a>
      </div>
    )
  }
  // Keyed by page: a new #page on the same URL does not move an already open PDF viewer.
  return <iframe key={page || 1} className="op-frame" title={title || 'Documento original'}
    src={kind === 'pdf' && page ? `${url}#page=${page}` : url} />
}
