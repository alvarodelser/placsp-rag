// Generic dual-thumb slider. Two native range inputs overlaid on a track; the
// `scale` maps domain values <-> 0..1000 slider positions so the same control
// drives both the linear date axis and the logarithmic budget axis.
export default function RangeSlider({ value, onChange, scale }) {
  const loPos = scale.toPos(value[0])
  const hiPos = scale.toPos(value[1])

  function setLo(p) {
    const np = Math.min(Number(p), hiPos)
    onChange([scale.fromPos(np), value[1]])
  }
  function setHi(p) {
    const np = Math.max(Number(p), loPos)
    onChange([value[0], scale.fromPos(np)])
  }

  return (
    <div className="range-slider">
      <div className="range-track" />
      <div className="range-fill" style={{ left: `${loPos / 10}%`, right: `${100 - hiPos / 10}%` }} />
      <input className="range-thumb" type="range" min="0" max="1000" value={loPos} onChange={(e) => setLo(e.target.value)} />
      <input className="range-thumb" type="range" min="0" max="1000" value={hiPos} onChange={(e) => setHi(e.target.value)} />
    </div>
  )
}
