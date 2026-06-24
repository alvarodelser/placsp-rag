// search-ui/src/components/DensitySlider.test.jsx
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import DensitySlider from './DensitySlider.jsx'

describe('DensitySlider', () => {
  it('renders two drag handles and a density path', () => {
    const { container } = render(
      <DensitySlider min={0} max={100} low={20} high={80}
        density={[1, 4, 2, 5]} onChange={() => {}} />)
    expect(container.querySelectorAll('.ds-thumb-handle')).toHaveLength(2)
    expect(container.querySelector('svg path')).toBeTruthy()
  })
  it('omits the density path when no data', () => {
    const { container } = render(
      <DensitySlider min={0} max={100} low={0} high={100} density={[]} onChange={() => {}} />)
    // With empty density, densityPath returns '' so both paths have d=""
    const paths = container.querySelectorAll('svg path')
    paths.forEach((p) => expect(p.getAttribute('d') || '').toBe(''))
  })
})
