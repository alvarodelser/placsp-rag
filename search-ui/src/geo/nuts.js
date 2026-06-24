export function nutsLevel(code) {
  return String(code).length >= 5 ? 3 : 2
}
export function truncate(code, level) {
  return String(code).slice(0, level === 2 ? 4 : 5)
}
export function aggregateByLevel(counts, level) {
  const out = {}
  for (const [code, n] of Object.entries(counts)) {
    const key = truncate(code, level)
    out[key] = (out[key] || 0) + n
  }
  return out
}
