// CPV hierarchy is encoded in the 8 digits: division(2) > group(3) > class(4)
// > category(5) > detail(6-8). We derive level and ancestor path from the code
// itself plus the flat {code: label} map, so no extra data structure is needed.

function normalize(code) {
  return String(code).split('-')[0].padEnd(8, '0').slice(0, 8)
}

export function cpvLevel(code) {
  const d = normalize(code).replace(/0+$/, '')
  return Math.max(d.length, 2)
}

export function cpvPath(code, cpvMap) {
  const d = normalize(code)
  const sig = cpvLevel(code)
  const labels = []
  for (let len = 2; len < sig; len++) {
    const ancestor = d.slice(0, len).padEnd(8, '0')
    if (ancestor !== d && cpvMap[ancestor]) labels.push(cpvMap[ancestor])
  }
  return labels
}

export function cpvChildren(code, cpvMap) {
  const d = normalize(code)
  const parentLen = cpvLevel(code)
  if (parentLen >= 8) return []
  const prefix = d.slice(0, parentLen)
  const childLen = parentLen + 1
  const out = []
  for (const c of Object.keys(cpvMap)) {
    if (cpvLevel(c) === childLen && normalize(c).slice(0, parentLen) === prefix) {
      out.push(c)
    }
  }
  return out.sort()
}
