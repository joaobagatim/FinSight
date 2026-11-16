import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { chartPositions } from '@/lib/balance-history'
import { formatDate, formatMoney } from '@/lib/money'

function BalanceTooltip({ active, payload }) {
  const point = payload?.[0]?.payload
  if (!active || !point) return null
  return (
    <div className="surface history-tooltip">
      <p>{formatDate(point.date)}</p>
      <strong>{formatMoney(point.balance)}</strong>
    </div>
  )
}

export default function BalanceHistoryChart({ points }) {
  const data = chartPositions(points)
  return (
    <>
      <p className="field-hint">
        Mínimo: {formatMoney(data.find((point) => point.isMinimum).balance)} · Máximo:{' '}
        {formatMoney(data.find((point) => point.isMaximum).balance)}. Escala vertical ajustada a
        esse intervalo.
      </p>
      <div className="history-chart" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={data}
            accessibilityLayer={false}
            margin={{ top: 16, right: 16, bottom: 8, left: 16 }}
          >
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={(value) => formatDate(value).slice(0, 5)}
              minTickGap={36}
              tick={{ fontSize: 12 }}
              interval="preserveStartEnd"
            />
            <YAxis hide domain={[0, 100]} />
            <Tooltip content={<BalanceTooltip />} />
            <Line
              type="linear"
              dataKey="position"
              stroke="#14594c"
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </>
  )
}
