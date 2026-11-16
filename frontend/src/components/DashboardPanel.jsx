import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/services/api'
import { formatDate, formatMoney } from '@/lib/money'
import { dayNumber } from '@/lib/balance-history'
import DashboardData from '@/components/DashboardData'

const scopes = {
  active: 'Contas ativas atualmente',
  all: 'Todas as contas, incluindo arquivadas',
  selected: 'Contas selecionadas',
}

function todayInSaoPaulo() {
  const parts = new Intl.DateTimeFormat('en', {
    timeZone: 'America/Sao_Paulo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())
  const part = (type) => parts.find((item) => item.type === type).value
  return `${part('year')}-${part('month')}-${part('day')}`
}

function queryError(error) {
  return error.status === 404
    ? 'Uma conta da seleção está indisponível. Atualize as contas e selecione novamente.'
    : error.status === 422
      ? 'Confira o período e as contas: use até 366 dias, sem datas futuras, e de 1 a 100 contas na seleção manual.'
      : errorMessage(error, 'Não foi possível consultar os indicadores. Tente novamente.')
}

export default function DashboardPanel({ ownerId, onExpired }) {
  const [initial] = useState(() => {
    const to = todayInSaoPaulo()
    return { from: `${to.slice(0, 7)}-01`, to, scope: 'active', ids: [] }
  })
  const [filters, setFilters] = useState(initial)
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [accounts, setAccounts] = useState({ items: [], has_more: false })
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState('')
  const live = useRef(false)
  const version = useRef(0)
  const sending = useRef(false)
  const listing = useRef(true)

  useEffect(() => {
    let current = true
    live.current = true
    const requestVersion = ++version.current
    api
      .dashboardBreakdown(ownerId, initial.scope, initial.from, initial.to)
      .then((response) => {
        if (current && requestVersion === version.current) setResult({ ...response, names: [] })
      })
      .catch((failure) => {
        if (!current || requestVersion !== version.current) return
        if (failure.status === 401) onExpired()
        else setError(queryError(failure))
      })
      .finally(() => {
        if (current && requestVersion === version.current) setBusy(false)
      })
    api
      .accounts(ownerId)
      .then((page) => {
        if (current) setAccounts(page)
      })
      .catch((failure) => {
        if (!current) return
        if (failure.status === 401) onExpired()
        else setListError(errorMessage(failure, 'Não foi possível carregar as contas.'))
      })
      .finally(() => {
        if (current) {
          listing.current = false
          setListLoading(false)
        }
      })
    return () => {
      current = false
      live.current = false
    }
  }, [ownerId, onExpired, initial])

  function change(next) {
    version.current++
    sending.current = false
    setBusy(false)
    setResult(null)
    setError('')
    setFilters(next)
  }

  async function loadAccounts(reset = false) {
    if (listing.current) return
    listing.current = true
    setListLoading(true)
    setListError('')
    if (reset) change({ ...filters, ids: [] })
    try {
      const page = await api.accounts(ownerId, reset ? 0 : accounts.items.length)
      if (live.current)
        setAccounts((previous) => ({
          ...page,
          items: reset
            ? page.items
            : [...new Map([...previous.items, ...page.items].map((a) => [a.id, a])).values()],
        }))
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else setListError(errorMessage(failure, 'Não foi possível carregar as contas.'))
    } finally {
      listing.current = false
      if (live.current) setListLoading(false)
    }
  }

  async function consult(event) {
    event.preventDefault()
    if (sending.current) return
    const requestVersion = ++version.current
    setResult(null)
    setError('')
    const fromDay = dayNumber(filters.from),
      toDay = dayNumber(filters.to)
    if (
      fromDay === null ||
      toDay === null ||
      toDay < fromDay ||
      toDay - fromDay >= 366 ||
      filters.to > todayInSaoPaulo()
    ) {
      setBusy(false)
      setError('Escolha um período válido de até 366 dias, sem datas futuras (São Paulo).')
      return
    }
    if (
      filters.scope === 'selected' &&
      (!filters.ids.length || filters.ids.length > 100 || listLoading || listError)
    ) {
      setBusy(false)
      setError('Carregue as contas e selecione de 1 a 100 para consultar.')
      return
    }
    sending.current = true
    setBusy(true)
    const names = accounts.items.filter((a) => filters.ids.includes(a.id)).map((a) => a.name)
    try {
      const response = await api.dashboardBreakdown(
        ownerId,
        filters.scope,
        filters.from,
        filters.to,
        filters.ids,
      )
      if (live.current && requestVersion === version.current) setResult({ ...response, names })
    } catch (failure) {
      if (!live.current || requestVersion !== version.current) return
      if (failure.status === 401) onExpired()
      else setError(queryError(failure))
    } finally {
      if (live.current && requestVersion === version.current) {
        sending.current = false
        setBusy(false)
      }
    }
  }

  return (
    <section className="surface account-form dashboard-panel" aria-labelledby="dashboard-heading">
      <p className="eyebrow">Seu dinheiro, com contexto</p>
      <h2 id="dashboard-heading">Resumo do período</h2>
      <p className="field-hint">
        Receitas e despesas efetivadas. O resultado é a diferença entre elas, não o saldo acumulado
        das contas.
      </p>
      <form onSubmit={consult} aria-label="Filtrar indicadores do dashboard">
        <div className="dashboard-dates">
          <label className="field" htmlFor="dashboard-from">
            Data inicial
            <input
              id="dashboard-from"
              type="date"
              required
              value={filters.from}
              max={initial.to}
              onChange={(event) => change({ ...filters, from: event.target.value })}
            />
          </label>
          <label className="field" htmlFor="dashboard-to">
            Data final
            <input
              id="dashboard-to"
              type="date"
              required
              value={filters.to}
              max={initial.to}
              onChange={(event) => change({ ...filters, to: event.target.value })}
            />
          </label>
        </div>
        <div className="field">
          <label htmlFor="dashboard-scope">Contas incluídas nos indicadores</label>
          <select
            id="dashboard-scope"
            value={filters.scope}
            onChange={(event) => change({ ...filters, scope: event.target.value, ids: [] })}
          >
            {Object.entries(scopes).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <p className="field-hint">
          O período inclui as duas datas e aceita até 366 dias, sem futuro. Contas ativas usa a
          situação atual; escolha todas para incluir arquivadas. A referência de hoje é São Paulo.
        </p>
        {filters.scope === 'selected' && (
          <fieldset className="dashboard-selection">
            <legend>Selecionar contas para os indicadores (até 100)</legend>
            {listLoading && <p role="status">Carregando contas para os indicadores…</p>}
            {listError && (
              <p role="alert" className="notice notice-error">
                {listError}
              </p>
            )}
            {!listLoading && !listError && !accounts.items.length && (
              <p>Nenhuma conta disponível para selecionar.</p>
            )}
            {accounts.items.map((account) => (
              <label className="consolidated-choice" key={account.id}>
                <input
                  type="checkbox"
                  checked={filters.ids.includes(account.id)}
                  disabled={
                    listLoading || (!filters.ids.includes(account.id) && filters.ids.length >= 100)
                  }
                  onChange={(event) =>
                    change({
                      ...filters,
                      ids: event.target.checked
                        ? [...new Set([...filters.ids, account.id])]
                        : filters.ids.filter((id) => id !== account.id),
                    })
                  }
                />
                <span>
                  {account.name}
                  {!account.is_active && ' · Arquivada'}
                </span>
              </label>
            ))}
            <p className="field-hint">
              {filters.ids.length} conta(s) selecionada(s). Há contas de outras páginas quando a
              opção de carregar mais estiver disponível.
            </p>
            <div className="reference-actions">
              {accounts.has_more && (
                <Button
                  type="button"
                  variant="outline"
                  disabled={listLoading}
                  onClick={() => loadAccounts()}
                >
                  Carregar mais contas para os indicadores
                </Button>
              )}
              <Button
                type="button"
                variant="outline"
                disabled={listLoading}
                onClick={() => loadAccounts(true)}
              >
                Atualizar contas e limpar seleção dos indicadores
              </Button>
            </div>
          </fieldset>
        )}
        <Button type="submit" disabled={busy}>
          {busy ? 'Consultando indicadores…' : 'Consultar indicadores'}
        </Button>
      </form>
      {busy && <p role="status">Consultando os indicadores do período…</p>}
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
      {result && (
        <section
          className="dashboard-result"
          aria-labelledby="dashboard-result-heading"
          aria-live="polite"
        >
          <h3 id="dashboard-result-heading">Indicadores consultados</h3>
          <p>
            De {formatDate(result.date_from)} a {formatDate(result.date_to)}, inclusive.
          </p>
          <p>
            {scopes[result.scope]} · {result.account_count} conta(s) · {result.transaction_count}{' '}
            lançamento(s).
          </p>
          {result.scope === 'selected' && (
            <ul aria-label="Contas consultadas nos indicadores">
              {result.names.map((name, i) => (
                <li key={i}>{name}</li>
              ))}
            </ul>
          )}
          <dl className="dashboard-cards">
            {[
              ['Receitas do período', result.income],
              ['Despesas do período', result.expense],
              ['Resultado líquido do período', result.net],
            ].map(([label, amount]) => (
              <div className="dashboard-card" key={label}>
                <dt>{label}</dt>
                <dd>{formatMoney(amount)}</dd>
              </div>
            ))}
          </dl>
          {result.transaction_count === 0 && (
            <p>Nenhum lançamento efetivado neste período para as contas incluídas.</p>
          )}
          <DashboardData result={result} />
          <p className="field-hint">
            Referência da consulta: {formatDate(result.as_of)} (São Paulo). Abertura, transferências
            internas, reservas, planejados e lançamentos removidos não compõem estes totais. O saldo
            acumulado está disponível em Saldos.
          </p>
        </section>
      )}
    </section>
  )
}
