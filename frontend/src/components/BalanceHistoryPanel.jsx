import { Component, lazy, Suspense, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/services/api'
import { dayNumber, shiftDay } from '@/lib/balance-history'
import { formatDate, formatMoney, today } from '@/lib/money'

const BalanceHistoryChart = lazy(() => import('./BalanceHistoryChart.jsx'))

class ChartBoundary extends Component {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  render() {
    return this.state.failed ? (
      <p>
        Não foi possível carregar o gráfico. Os valores continuam disponíveis na tabela; recarregue
        a página para tentar carregar o gráfico novamente.
      </p>
    ) : (
      this.props.children
    )
  }
}

export default function BalanceHistoryPanel({ ownerId, onExpired }) {
  const [accountId, setAccountId] = useState('')
  const [dateFrom, setDateFrom] = useState(() => shiftDay(today(), -29))
  const [dateTo, setDateTo] = useState(today)
  const [accounts, setAccounts] = useState({ items: [], has_more: false })
  const [listing, setListing] = useState(true)
  const [listError, setListError] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  const live = useRef(false)
  const loadingAccounts = useRef(true)
  const sending = useRef(false)

  useEffect(() => {
    let current = true
    live.current = true
    api
      .accounts(ownerId)
      .then((page) => {
        if (current) setAccounts(page)
      })
      .catch((failure) => {
        if (!current) return
        if (failure.status === 401) onExpired()
        else setListError(errorMessage(failure, 'Não foi possível carregar as contas da evolução.'))
      })
      .finally(() => {
        if (current) {
          setListing(false)
          loadingAccounts.current = false
        }
      })
    return () => {
      current = false
      live.current = false
    }
  }, [ownerId, onExpired])

  function clearResult() {
    setResult(null)
    setError('')
  }
  async function loadAccounts(reset = false) {
    if (loadingAccounts.current) return
    loadingAccounts.current = true
    setListing(true)
    setListError('')
    if (reset) {
      setAccountId('')
      clearResult()
    }
    try {
      const page = await api.accounts(ownerId, reset ? 0 : accounts.items.length)
      if (live.current)
        setAccounts((previous) => ({
          ...page,
          items: reset ? page.items : [...previous.items, ...page.items],
        }))
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else setListError(errorMessage(failure, 'Não foi possível carregar as contas da evolução.'))
    } finally {
      loadingAccounts.current = false
      if (live.current) setListing(false)
    }
  }
  async function consult(event) {
    event.preventDefault()
    if (sending.current) return
    clearResult()
    const account = accounts.items.find((item) => item.id === accountId)
    const start = dayNumber(dateFrom),
      end = dayNumber(dateTo)
    if (!account || start === null || end === null || end < start || end - start >= 93) {
      setError(
        'Selecione uma conta e um período de 1 a 93 dias, com início igual ou anterior ao fim.',
      )
      return
    }
    if (dateFrom < account.opening_date) {
      setError('O período precisa começar na data de abertura da conta ou depois dela.')
      return
    }
    sending.current = true
    setBusy(true)
    try {
      const response = await api.balanceHistory(ownerId, accountId, dateFrom, dateTo)
      if (!live.current) return
      if (
        response.account_id !== accountId ||
        response.currency !== 'BRL' ||
        response.date_from !== dateFrom ||
        response.date_to !== dateTo ||
        typeof response.account_name !== 'string' ||
        !Array.isArray(response.points) ||
        response.points.length !== end - start + 1 ||
        !response.points.every(
          (point, index) =>
            point.date === shiftDay(dateFrom, index) &&
            typeof point.balance === 'string' &&
            point.balance.length <= 40 &&
            /^-?\d+\.\d{2}$/.test(point.balance),
        )
      )
        throw new Error('Unexpected balance history response')
      setResult(response)
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else
        setError(
          failure.status === 404
            ? 'A conta não está disponível. Atualize as opções e selecione novamente.'
            : failure.status === 422
              ? 'Confira o período: até 93 dias e sem datas anteriores à abertura da conta.'
              : errorMessage(failure, 'Não foi possível consultar a evolução do saldo.'),
        )
    } finally {
      sending.current = false
      if (live.current) setBusy(false)
    }
  }
  const selected = accounts.items.find((item) => item.id === accountId)
  return (
    <section
      className="surface account-form balance-history-panel"
      aria-labelledby="balance-history-heading"
      aria-busy={busy}
    >
      <p className="eyebrow">Uma posição ao final de cada dia</p>
      <h2 id="balance-history-heading">Evolução do saldo</h2>
      <p className="field-hint">
        Saldo inicial mais movimentos registrados como efetivados, incluindo transferências.
        Planejados e lançamentos excluídos ficam fora. Se escolher datas futuras, entram somente os
        efetivados já cadastrados para essas datas.
      </p>
      <form onSubmit={consult} aria-label="Consultar evolução do saldo">
        <fieldset disabled={busy}>
          <legend className="sr-only">Conta e período da evolução</legend>
          <label className="field" htmlFor="history-balance-account">
            Conta da evolução
            <select
              id="history-balance-account"
              required
              disabled={listing}
              value={accountId}
              onChange={(event) => {
                setAccountId(event.target.value)
                clearResult()
              }}
            >
              <option value="">Selecione uma conta</option>
              {accounts.items.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                  {!item.is_active && ' · Arquivada'}
                </option>
              ))}
            </select>
          </label>
          {selected && (
            <p className="field-hint">
              Abertura em {formatDate(selected.opening_date)}. O período deve começar nessa data ou
              depois.
            </p>
          )}
          <label className="field" htmlFor="history-balance-from">
            Evolução a partir de
            <input
              id="history-balance-from"
              type="date"
              required
              value={dateFrom}
              onChange={(event) => {
                setDateFrom(event.target.value)
                clearResult()
              }}
            />
          </label>
          <label className="field" htmlFor="history-balance-to">
            Evolução até
            <input
              id="history-balance-to"
              type="date"
              required
              value={dateTo}
              onChange={(event) => {
                setDateTo(event.target.value)
                clearResult()
              }}
            />
          </label>
          <p className="field-hint">
            De 1 a 93 dias, com as duas datas incluídas. Dias sem movimento repetem a última
            posição. Esta consulta usa os registros atuais, sem reconstituir versões anteriores de
            lançamentos editados.
          </p>
          {listing && <p role="status">Carregando contas da evolução…</p>}
          {listError && (
            <p role="alert" className="notice notice-error">
              {listError}
            </p>
          )}
          {!listing && !listError && !accounts.items.length && (
            <p>Nenhuma conta disponível para consultar a evolução.</p>
          )}
          <div className="account-actions">
            {accounts.has_more && (
              <Button
                type="button"
                variant="outline"
                disabled={listing}
                onClick={() => loadAccounts()}
              >
                Mais contas para evolução
              </Button>
            )}
            <Button
              type="button"
              variant="outline"
              disabled={listing}
              onClick={() => loadAccounts(true)}
            >
              Atualizar contas da evolução
            </Button>
          </div>
          <Button
            type="submit"
            className="wide-button"
            disabled={listing || !accounts.items.length}
          >
            {busy ? 'Consultando evolução…' : 'Consultar evolução'}
          </Button>
        </fieldset>
      </form>
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
      {result && (
        <div className="balance-history-result">
          <p role="status">
            {result.account_name} · {result.points.length} dia(s) · {formatDate(result.date_from)} a{' '}
            {formatDate(result.date_to)}
          </p>
          <p>
            Saldo no fim do período: <strong>{formatMoney(result.points.at(-1).balance)}</strong>
          </p>
          <ChartBoundary>
            <Suspense fallback={<p>Carregando gráfico… Os valores estão disponíveis na tabela.</p>}>
              <BalanceHistoryChart points={result.points} />
            </Suspense>
          </ChartBoundary>
          <p className="field-hint">
            A linha mostra posições de fechamento e liga os dias; não detalha movimentos dentro de
            um dia. Os valores exatos estão na tabela.
          </p>
          <details>
            <summary>Ver valores diários ({result.points.length} dias)</summary>
            <table>
              <caption>Saldos de fechamento de {result.account_name}, em reais</caption>
              <thead>
                <tr>
                  <th scope="col">Data</th>
                  <th scope="col">Saldo efetivado</th>
                </tr>
              </thead>
              <tbody>
                {result.points.map((point) => (
                  <tr key={point.date}>
                    <th scope="row">{formatDate(point.date)}</th>
                    <td>{formatMoney(point.balance)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
          <p className="field-hint">
            Posição consultada com os registros atuais. Consulte novamente para refletir alterações
            posteriores.
          </p>
        </div>
      )}
    </section>
  )
}
