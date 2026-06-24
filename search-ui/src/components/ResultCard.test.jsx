// search-ui/src/components/ResultCard.test.jsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ResultCard from './ResultCard.jsx'

const R = { title: 'Limpieza', contracting_authority: 'Ayto', cpv: ['90910000'] }

describe('ResultCard relevance gutter', () => {
  it('renders the relevance button and toggles', () => {
    const onToggle = vi.fn()
    render(<ResultCard r={R} liked={false} onToggleLike={onToggle} />)
    const btn = screen.getByRole('button', { name: /relevante/i })
    fireEvent.click(btn)
    expect(onToggle).toHaveBeenCalled()
  })
  it('reflects liked state via aria-pressed', () => {
    render(<ResultCard r={R} liked onToggleLike={() => {}} />)
    expect(screen.getByRole('button', { name: /relevante/i })).toHaveAttribute('aria-pressed', 'true')
  })
})
