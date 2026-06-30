import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ProcedureAxis from './ProcedureAxis.jsx'
import { PROC_GROUPS } from '../facetGroups.js'

describe('ProcedureAxis', () => {
  it('renders a card for every procedure group', () => {
    render(<ProcedureAxis groups={PROC_GROUPS} value={[]} counts={{}} onChange={() => {}} />)
    for (const g of PROC_GROUPS) {
      expect(screen.getByRole('button', { name: g.label })).toBeInTheDocument()
    }
  })

  it('shows the concurrence axis hint', () => {
    render(<ProcedureAxis groups={PROC_GROUPS} value={[]} counts={{}} onChange={() => {}} />)
    expect(screen.getByText(/concurrencia/i)).toBeInTheDocument()
    expect(screen.getByText(/directo/i)).toBeInTheDocument()
  })

  it('places "Otros" off the axis, separate from the on-axis strip', () => {
    const { container } = render(
      <ProcedureAxis groups={PROC_GROUPS} value={[]} counts={{}} onChange={() => {}} />,
    )
    const offAxis = container.querySelector('.pa-offaxis')
    expect(offAxis).toBeTruthy()
    expect(offAxis).toHaveTextContent('Otros')
    expect(container.querySelector('.pa-strip')).not.toHaveTextContent('Otros')
  })

  it('emits the full code set of a group when toggled', () => {
    const onChange = vi.fn()
    render(<ProcedureAxis groups={PROC_GROUPS} value={[]} counts={{}} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: /Negociado/i }))
    expect(onChange).toHaveBeenCalledWith(['3', '4', '5', '10', '11', '13'])
  })
})
