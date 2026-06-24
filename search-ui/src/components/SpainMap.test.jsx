// search-ui/src/components/SpainMap.test.jsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import SpainMap from './SpainMap.jsx'

describe('SpainMap', () => {
  it('renders a level toggle and svg paths', () => {
    const { container } = render(<SpainMap value={[]} counts={{}} onChange={() => {}} />)
    expect(screen.getByRole('button', { name: /comunidades/i })).toBeInTheDocument()
    expect(container.querySelectorAll('svg path').length).toBeGreaterThan(0)
  })
  it('toggles a region on click', () => {
    const onChange = vi.fn()
    const { container } = render(<SpainMap value={[]} counts={{}} onChange={onChange} />)
    fireEvent.click(container.querySelector('svg path'))
    expect(onChange).toHaveBeenCalled()
  })
})
