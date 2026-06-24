import { cpvChildren, cpvLevel } from './cpv.js'

function divisions(cpvMap) {
  return Object.keys(cpvMap).filter((c) => cpvLevel(c) === 2).sort()
}

export function columns(path, cpvMap) {
  const cols = []
  let codes = divisions(cpvMap)
  for (let depth = 0; ; depth++) {
    const activeCode = path[depth] ?? null
    cols.push({
      items: codes.map((code) => ({ code, label: cpvMap[code] || '—' })),
      activeCode,
    })
    if (activeCode == null) break
    const kids = cpvChildren(activeCode, cpvMap)
    if (kids.length === 0) break
    codes = kids
  }
  return cols
}
