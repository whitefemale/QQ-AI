import { describe, expect, it } from 'vitest'

import { CLEANUP_PHRASE, DELETE_PHRASE, confirmationMatches } from '@/utils/confirmation'

describe('confirmation phrases', () => {
  it('exposes the server-side phrases', () => {
    expect(DELETE_PHRASE).toBe('DELETE')
    expect(CLEANUP_PHRASE).toBe('CLEANUP')
  })

  it('requires an exact match after trimming whitespace', () => {
    expect(confirmationMatches('DELETE', DELETE_PHRASE)).toBe(true)
    expect(confirmationMatches('  DELETE\n', DELETE_PHRASE)).toBe(true)
    expect(confirmationMatches('CLEANUP', CLEANUP_PHRASE)).toBe(true)
  })

  it('is case-sensitive and rejects partial or empty input', () => {
    expect(confirmationMatches('delete', DELETE_PHRASE)).toBe(false)
    expect(confirmationMatches('Delete', DELETE_PHRASE)).toBe(false)
    expect(confirmationMatches('DELET', DELETE_PHRASE)).toBe(false)
    expect(confirmationMatches('DELETEX', DELETE_PHRASE)).toBe(false)
    expect(confirmationMatches(' DELETE X ', DELETE_PHRASE)).toBe(false)
    expect(confirmationMatches('', DELETE_PHRASE)).toBe(false)
    expect(confirmationMatches('   ', DELETE_PHRASE)).toBe(false)
    expect(confirmationMatches(null, DELETE_PHRASE)).toBe(false)
    expect(confirmationMatches(undefined, DELETE_PHRASE)).toBe(false)
  })

  it('does not treat one phrase as the other', () => {
    expect(confirmationMatches('DELETE', CLEANUP_PHRASE)).toBe(false)
    expect(confirmationMatches('CLEANUP', DELETE_PHRASE)).toBe(false)
  })
})
