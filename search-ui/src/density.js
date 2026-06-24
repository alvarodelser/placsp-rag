export function linearPos(value, min, max) {
  if (max <= min) return 0
  return Math.max(0, Math.min(1, (value - min) / (max - min)))
}
export function linearValue(pos, min, max) {
  return min + Math.max(0, Math.min(1, pos)) * (max - min)
}

// Smoothed filled area for a sparkline-style density. Uses a simple Catmull-Rom-ish
// midpoint smoothing — quiet and good enough for a subtle backdrop.
export function densityPath(values, width, height) {
  const n = values.length
  if (n === 0) return ''
  const max = Math.max(...values, 1)
  const xs = (i) => (n === 1 ? width : (i / (n - 1)) * width)
  const ys = (v) => height - (v / max) * height
  let d = `M0 ${ys(values[0]).toFixed(2)}`
  for (let i = 1; i < n; i++) {
    const xm = ((xs(i - 1) + xs(i)) / 2).toFixed(2)
    d += ` Q${xm} ${ys(values[i - 1]).toFixed(2)} ${xs(i).toFixed(2)} ${ys(values[i]).toFixed(2)}`
  }
  d += ` L${width} ${height} L0 ${height} Z`
  return d
}
