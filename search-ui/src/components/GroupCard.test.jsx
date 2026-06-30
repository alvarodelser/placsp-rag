import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import GroupCard from './GroupCard.jsx'
import { RESULT_GROUPS, TYPE_GROUPS } from '../facetGroups.js'

const adj = RESULT_GROUPS.find((g) => g.key === 'adj') // 6 codes
const sum = TYPE_GROUPS.find((g) => g.key === 'sum')   // 1 code

describe('GroupCard', () => {
  it('renders the group as a toggle that emits the whole code set', () => {
    const onChange = vi.fn()
    render(<GroupCard group={adj} value={[]} counts={{}} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'Adjudicado' }))
    expect(onChange).toHaveBeenCalledWith(['1', '2', '8', '9', '10', '11'])
  })

  it('shows a caret for multi-code groups and hides it for single-code groups', () => {
    const { rerender } = render(<GroupCard group={adj} value={[]} counts={{}} onChange={() => {}} />)
    expect(screen.getByRole('button', { name: /opciones de Adjudicado/i })).toBeInTheDocument()
    rerender(<GroupCard group={sum} value={[]} counts={{}} onChange={() => {}} />)
    expect(screen.queryByRole('button', { name: /opciones de/i })).not.toBeInTheDocument()
  })

  it('reveals the granular sub-options when the caret is clicked', () => {
    render(<GroupCard group={adj} value={[]} counts={{}} onChange={() => {}} />)
    expect(screen.queryByRole('button', { name: /Formalizado/i })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /opciones de Adjudicado/i }))
    expect(screen.getByRole('button', { name: /^Formalizado/i })).toBeInTheDocument()
  })

  it('toggles a single code when a sub-option is clicked', () => {
    const onChange = vi.fn()
    render(<GroupCard group={adj} value={[]} counts={{}} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: /opciones de Adjudicado/i }))
    fireEvent.click(screen.getByRole('button', { name: /^Formalizado/i }))
    expect(onChange).toHaveBeenCalledWith(['9'])
  })

  it('marks the group card partial when only some codes are selected', () => {
    render(<GroupCard group={adj} value={['9']} counts={{}} onChange={() => {}} />)
    const main = screen.getByRole('button', { name: 'Adjudicado' })
    expect(main).toHaveAttribute('aria-pressed', 'false')
    expect(main.className).toMatch(/partial/)
  })
})
