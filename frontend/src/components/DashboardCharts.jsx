import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { dashboardPlotData } from '@/lib/dashboard'
import { formatDate, formatMoney } from '@/lib/money'

function DailyTooltip({ active, payload }) {
  const point = payload?.[0]?.payload
  if (!active || !point) return null
  return (
    <div className="surface history-tooltip">
      <p>{formatDate(point.date)}</p>
      <p>Receitas: {formatMoney(point.income)}</p>
      <p>Despesas: {formatMoney(point.expense)}</p>
    </div>
  )
}

function CategoryTooltip({ active, payload }) {
  const category = payload?.[0]?.payload
  if (!active || !category) return null
  return (
    <div className="surface history-tooltip">
      <p>{category.name}</p>
      <strong>{formatMoney(category.amount)}</strong>
      <p>{category.transaction_count} lançamento(s).</p>
    </div>
  )
}

export default function DashboardCharts({ result }) {
  const data = dashboardPlotData(result)
  return (
    <div className="dashboard-plots">
      <figure aria-labelledby="dashboard-daily-chart-title">
        <figcaption id="dashboard-daily-chart-title">Entradas e saídas por dia</figcaption>
        <p className="field-hint">
          Escala diária: maior valor {formatMoney(data.dailyMaximum)}. Confira os valores exatos nas
          tabelas abaixo.
        </p>
        <div className="dashboard-plot" aria-hidden="true">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={data.daily}
              accessibilityLayer={false}
              margin={{ top: 12, right: 8, bottom: 8, left: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={(value) => formatDate(value).slice(0, 5)}
                minTickGap={32}
                interval="preserveStartEnd"
                tick={{ fontSize: 12 }}
              />
              <YAxis hide domain={[0, 100]} />
              <Tooltip content={<DailyTooltip />} />
              <Legend />
              <Bar
                dataKey="incomePosition"
                name="Receitas"
                fill="#14594c"
                isAnimationActive={false}
              />
              <Bar
                dataKey="expensePosition"
                name="Despesas"
                fill="#7d2e41"
                isAnimationActive={false}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </figure>
      {data.categories.length > 0 ? (
        <figure aria-labelledby="dashboard-category-chart-title">
          <figcaption id="dashboard-category-chart-title">Despesas por categoria</figcaption>
          <p className="field-hint">
            Escala das categorias: maior valor {formatMoney(data.categoryMaximum)}. Nomes completos
            e valores estão na tabela de categorias.
          </p>
          <div
            className="dashboard-plot"
            style={{ height: Math.max(200, data.categories.length * 30) }}
            aria-hidden="true"
          >
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={data.categories}
                layout="vertical"
                accessibilityLayer={false}
                margin={{ top: 8, right: 16, bottom: 8, left: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" hide domain={[0, 100]} />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={100}
                  tick={{ fontSize: 11 }}
                  tickFormatter={(name) =>
                    Array.from(name).length > 14
                      ? `${Array.from(name).slice(0, 14).join('')}…`
                      : name
                  }
                />
                <Tooltip content={<CategoryTooltip />} />
                <Bar dataKey="position" name="Despesas" fill="#7d2e41" isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </figure>
      ) : (
        <p>Não há despesas por categoria neste período.</p>
      )}
    </div>
  )
}
