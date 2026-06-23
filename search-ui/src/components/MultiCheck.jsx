export default function MultiCheck({ map, value, onChange }) {
  function toggle(code) {
    onChange(value.includes(code) ? value.filter((c) => c !== code) : [...value, code])
  }
  return (
    <div className="checks">
      {Object.entries(map).map(([code, name]) => (
        <label key={code} className="check">
          <input type="checkbox" checked={value.includes(code)} onChange={() => toggle(code)} />
          {name}
        </label>
      ))}
    </div>
  )
}
