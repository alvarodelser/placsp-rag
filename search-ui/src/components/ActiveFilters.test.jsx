import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import ActiveFilters from './ActiveFilters.jsx'
import { EMPTY } from '../filters.js'

const f = (over) => ({ ...EMPTY, ...over })

describe('ActiveFilters grouped facets', () => {
  it('collapses grouped result codes into one chip per group', () => {
    // 1,2 -> Adjudicado ; 3 -> Desierto
    render(<ActiveFilters filters={f({ result: ['1', '2', '3'] })} onRemove={() => {}} />)
    expect(screen.getByText('Adjudicado')).toBeInTheDocument()
    expect(screen.getByText('Desierto')).toBeInTheDocument()
    // not one chip per granular code
    expect(screen.queryByText('Adjudicado Provisionalmente')).not.toBeInTheDocument()
  })

  it('removing a grouped chip removes the whole code set', () => {
    const onRemove = vi.fn()
    render(<ActiveFilters filters={f({ result: ['1', '2', '3'] })} onRemove={onRemove} />)
    const chip = screen.getByText('Adjudicado').closest('.af-chip')
    fireEvent.click(within(chip).getByRole('button', { name: /quitar/i }))
    expect(onRemove).toHaveBeenCalledWith('result', ['1', '2', '8', '9', '10', '11'])
  })

  it('still renders non-grouped fields one chip per value', () => {
    render(<ActiveFilters filters={f({ nuts: ['ES1', 'ES2'] })} onRemove={() => {}} />)
    expect(screen.getByText('Ubicación')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /quitar/i })).toHaveLength(2)
  })
})
