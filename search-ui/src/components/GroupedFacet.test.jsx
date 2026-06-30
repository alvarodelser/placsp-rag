import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import GroupedFacet from './GroupedFacet.jsx'
import { RESULT_GROUPS } from '../facetGroups.js'

const counts = { '1': 5, '2': 3, '8': 2, '9': 1, '3': 4, '4': 7 }

describe('GroupedFacet', () => {
  it('renders one card per group', () => {
    render(<GroupedFacet groups={RESULT_GROUPS} value={[]} counts={counts} onChange={() => {}} />)
    expect(screen.getByRole('button', { name: /^Adjudicado/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Desierto/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Cancelado/ })).toBeInTheDocument()
  })

  it('emits the full code set of a group when toggled on', () => {
    const onChange = vi.fn()
    render(<GroupedFacet groups={RESULT_GROUPS} value={[]} counts={counts} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: /^Adjudicado/ }))
    expect(onChange).toHaveBeenCalledWith(['1', '2', '8', '9', '10', '11'])
  })

  it('shows the summed count of a group', () => {
    render(<GroupedFacet groups={RESULT_GROUPS} value={[]} counts={counts} onChange={() => {}} />)
    // Adjudicado = 5+3+2+1 = 11
    expect(screen.getByRole('button', { name: /^Adjudicado/ })).toHaveTextContent('11')
  })

  it('marks a card active via aria-pressed when all its codes are selected', () => {
    render(
      <GroupedFacet
        groups={RESULT_GROUPS}
        value={['1', '2', '8', '9', '10', '11']}
        counts={counts}
        onChange={() => {}}
      />,
    )
    expect(screen.getByRole('button', { name: /^Adjudicado/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: /^Desierto/ })).toHaveAttribute('aria-pressed', 'false')
  })
})
