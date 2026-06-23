import RangeSlider from './RangeSlider.jsx'
import { budgetToPos, posToBudget } from '../filters.js'

const SCALE = { toPos: budgetToPos, fromPos: posToBudget }
const B_MIN = 1000
const B_MAX = 100000000

export default function BudgetRange({ filters, onChange }) {
  const lo = filters.budget_min === '' ? B_MIN : Number(filters.budget_min)
  const hi = filters.budget_max === '' ? B_MAX : Number(filters.budget_max)

  function setRange([nlo, nhi]) {
    onChange({
      budget_min: nlo <= B_MIN ? '' : String(nlo),
      budget_max: nhi >= B_MAX ? '' : String(nhi),
    })
  }

  return (
    <div className="budget-range">
      <RangeSlider value={[lo, hi]} onChange={setRange} scale={SCALE} />
      <div className="range-inputs">
        <label>desde
          <input type="number" min="0" placeholder="0"
            value={filters.budget_min}
            onChange={(e) => onChange({ budget_min: e.target.value })} />
        </label>
        <label>hasta
          <input type="number" min="0" placeholder="100M+"
            value={filters.budget_max}
            onChange={(e) => onChange({ budget_max: e.target.value })} />
        </label>
      </div>
    </div>
  )
}
