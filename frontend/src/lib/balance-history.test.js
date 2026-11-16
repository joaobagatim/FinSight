import assert from 'node:assert/strict'
import test from 'node:test'
import { chartPositions, dayNumber, shiftDay } from './balance-history.js'

test('chart preserves exact decimal strings, cent differences and negative values', () => {
  const points = [
    { date: '2026-01-01', balance: '-9999999999999999.99' },
    { date: '2026-01-02', balance: '-9999999999999999.98' },
    { date: '2026-01-03', balance: '-9999999999999999.97' },
  ]
  const chart = chartPositions(points)
  assert.deepEqual(
    chart.map((item) => item.position),
    [0, 50, 100],
  )
  assert.deepEqual(
    chart.map((item) => item.balance),
    points.map((item) => item.balance),
  )
  assert.equal(chartPositions([{ balance: '0.00' }])[0].position, 50)
  assert.deepEqual(
    chartPositions([{ balance: '-0.10' }, { balance: '-0.10' }]).map((item) => item.position),
    [50, 50],
  )
  assert.throws(() => chartPositions([{ balance: 'invalid' }]))
})

test('calendar ranges preserve stored days across leap years and reject malformed dates', () => {
  assert.equal(shiftDay('2024-02-28', 1), '2024-02-29')
  assert.equal(shiftDay('2026-03-01', -1), '2026-02-28')
  assert.equal(shiftDay('0099-12-31', 1), '0100-01-01')
  assert.equal(dayNumber('2026-04-03') - dayNumber('2026-01-01') + 1, 93)
  assert.equal(dayNumber('2026-02-30'), null)
  assert.equal(dayNumber('0000-01-01'), null)
})
