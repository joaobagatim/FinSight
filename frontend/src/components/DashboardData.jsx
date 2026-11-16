import { Component, lazy, Suspense } from 'react'
import { categoryRows } from '@/lib/dashboard'
import { formatDate, formatMoney } from '@/lib/money'

const DashboardCharts = lazy(() => import('./DashboardCharts.jsx'))

class ChartsBoundary extends Component {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  render() {
    return this.state.failed ? (
      <p role="status">
        Não foi possível carregar os gráficos. Os cartões e tabelas continuam disponíveis.
        Recarregue a página para tentar carregar os gráficos novamente.
      </p>
    ) : (
      this.props.children
    )
  }
}

export default function DashboardData({ result }) {
  const categories = categoryRows(result)
  return (
    <section className="dashboard-data" aria-labelledby="dashboard-data-title">
      <h3 id="dashboard-data-title">Gráficos e valores conferíveis</h3>
      {result.transaction_count > 0 ? (
        <ChartsBoundary>
          <Suspense
            fallback={
              <p role="status">Carregando gráficos; os valores já estão disponíveis nas tabelas.</p>
            }
          >
            <DashboardCharts result={result} />
          </Suspense>
        </ChartsBoundary>
      ) : (
        <p>Sem movimentos efetivados para desenhar os gráficos neste período.</p>
      )}
      <p className="field-hint">
        Cartões, gráficos e tabelas usam a mesma consulta. As barras mostram proporções; parcelas
        muito pequenas podem não ser visíveis na escala, mas seus valores exatos estão nas tabelas.
      </p>
      <details>
        <summary>Conferir valores diários</summary>
        <div
          className="dashboard-table-scroll"
          role="region"
          aria-label="Tabela diária com rolagem"
          tabIndex={0}
        >
          <table>
            <caption>Valores diários do período</caption>
            <thead>
              <tr>
                <th scope="col">Data</th>
                <th scope="col">Receitas</th>
                <th scope="col">Despesas</th>
                <th scope="col">Resultado</th>
                <th scope="col">Lançamentos</th>
              </tr>
            </thead>
            <tbody>
              {result.daily.map((point) => (
                <tr key={point.date}>
                  <th scope="row">{formatDate(point.date)}</th>
                  <td>{formatMoney(point.income)}</td>
                  <td>{formatMoney(point.expense)}</td>
                  <td>{formatMoney(point.net)}</td>
                  <td>{point.transaction_count}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row">Total do período</th>
                <td>{formatMoney(result.income)}</td>
                <td>{formatMoney(result.expense)}</td>
                <td>{formatMoney(result.net)}</td>
                <td>{result.transaction_count}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </details>
      <details>
        <summary>Conferir despesas por categoria</summary>
        <p>
          {result.expense_category_count} categoria(s) com despesa. Até 20 são detalhadas; o
          excedente é agrupado em Demais categorias, sem descartar valores.
        </p>
        <div
          className="dashboard-table-scroll"
          role="region"
          aria-label="Tabela de categorias com rolagem"
          tabIndex={0}
        >
          <table>
            <caption>Despesas por categoria do período</caption>
            <thead>
              <tr>
                <th scope="col">Identificação</th>
                <th scope="col">Categoria ou agrupamento</th>
                <th scope="col">Despesa</th>
                <th scope="col">Lançamentos</th>
              </tr>
            </thead>
            <tbody>
              {categories.map((category, index) => (
                <tr key={category.key}>
                  <th scope="row">{index + 1}</th>
                  <td>{category.name}</td>
                  <td>{formatMoney(category.amount)}</td>
                  <td>{category.transaction_count}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row" colSpan={2}>
                  Total de despesas
                </th>
                <td>{formatMoney(result.expense)}</td>
                <td>{categories.reduce((sum, category) => sum + category.transaction_count, 0)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </details>
    </section>
  )
}
