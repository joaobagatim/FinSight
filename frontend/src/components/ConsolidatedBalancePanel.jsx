import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/services/api'
import { formatDate, formatMoney, today } from '@/lib/money'

const scopeNames = {
  active: 'Contas ativas atualmente',
  all: 'Todas as contas, incluindo arquivadas',
  selected: 'Contas selecionadas',
}

export default function ConsolidatedBalancePanel({ ownerId, onExpired }) {
  const [scope, setScope] = useState('active')
  const [date, setDate] = useState(today)
  const [selected, setSelected] = useState([])
  const [accounts, setAccounts] = useState({ items: [], has_more: false })
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  const live = useRef(false)
  const sending = useRef(false)
  const listing = useRef(true)
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
        else
          setListError(errorMessage(failure, 'Não foi possível carregar as contas para seleção.'))
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
  }, [ownerId, onExpired])

  function clearResult() {
    setResult(null)
    setError('')
  }
  async function loadAccounts(reset = false) {
    if (listing.current) return
    listing.current = true
    setListLoading(true)
    setListError('')
    if (reset) {
      setSelected([])
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
      else setListError(errorMessage(failure, 'Não foi possível carregar as contas para seleção.'))
    } finally {
      listing.current = false
      if (live.current) setListLoading(false)
    }
  }

  async function consult(event) {
    event.preventDefault()
    if (sending.current) return
    clearResult()
    if (!date || (scope === 'selected' && (!selected.length || selected.length > 100))) {
      setError('Informe a data e selecione de 1 a 100 contas quando usar a seleção manual.')
      return
    }
    if (
      scope === 'selected' &&
      accounts.items.some((item) => selected.includes(item.id) && date < item.opening_date)
    ) {
      setError('A data precisa ser igual ou posterior à abertura de todas as contas selecionadas.')
      return
    }
    const ids = scope === 'selected' ? [...selected].sort() : []
    const names = accounts.items.filter((item) => ids.includes(item.id)).map((item) => item.name)
    sending.current = true
    setBusy(true)
    try {
      const response = await api.consolidatedBalance(ownerId, scope, date, ids)
      if (!live.current) return
      if (
        response.scope !== scope ||
        response.as_of !== date ||
        response.currency !== 'BRL' ||
        typeof response.balance !== 'string' ||
        !/^-?\d+\.\d{2}$/.test(response.balance) ||
        !Number.isInteger(response.account_count) ||
        response.account_count < 0 ||
        (scope === 'selected' &&
          (response.account_count !== ids.length ||
            JSON.stringify(response.account_ids) !== JSON.stringify(ids)))
      )
        throw new Error('Unexpected consolidated balance response')
      setResult({ ...response, names })
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else
        setError(
          failure.status === 404
            ? 'A seleção inclui uma conta indisponível. Atualize a lista e selecione novamente.'
            : failure.status === 422
              ? 'Confira o filtro e a data: todas as contas incluídas precisam ter abertura igual ou anterior à consulta.'
              : errorMessage(failure, 'Não foi possível consultar o saldo consolidado.'),
        )
    } finally {
      sending.current = false
      if (live.current) setBusy(false)
    }
  }

  return (
    <section
      className="surface account-form consolidated-panel"
      aria-labelledby="consolidated-heading"
      aria-busy={busy}
    >
      <p className="eyebrow">Uma posição com filtro explícito</p>
      <h2 id="consolidated-heading">Saldo consolidado</h2>
      <p className="field-hint">
        Soma dos saldos reais das contas incluídas, na data escolhida. Planejados e lançamentos
        excluídos não entram no total.
      </p>
      <form onSubmit={consult} aria-label="Consultar saldo consolidado">
        <fieldset disabled={busy}>
          <legend className="sr-only">Filtro e data do consolidado</legend>
          <div className="field">
            <label htmlFor="consolidated-scope">Contas incluídas no consolidado</label>
            <select
              id="consolidated-scope"
              value={scope}
              onChange={(event) => {
                setScope(event.target.value)
                clearResult()
              }}
            >
              {Object.entries(scopeNames).map(([value, name]) => (
                <option key={value} value={value}>
                  {name}
                </option>
              ))}
            </select>
          </div>
          <label className="field" htmlFor="consolidated-date">
            Consolidado até a data
            <input
              id="consolidated-date"
              type="date"
              required
              value={date}
              onChange={(event) => {
                setDate(event.target.value)
                clearResult()
              }}
            />
          </label>
          <p className="field-hint">
            O filtro de contas ativas usa a situação atual das contas, mesmo em consultas de datas
            anteriores. Uma conta com abertura posterior à data torna a consulta inválida; escolha
            outra data ou use a seleção manual.
          </p>
          {scope === 'selected' && (
            <fieldset className="consolidated-selection" disabled={listLoading}>
              <legend>Seleção manual de contas (até 100)</legend>
              {listLoading && <p role="status">Carregando contas…</p>}
              {listError && (
                <p role="alert" className="notice notice-error">
                  {listError}
                </p>
              )}
              {!listLoading && !listError && !accounts.items.length && (
                <p>Nenhuma conta disponível para selecionar.</p>
              )}
              {accounts.items.map((account) => (
                <label key={account.id} className="consolidated-choice">
                  <input
                    type="checkbox"
                    checked={selected.includes(account.id)}
                    disabled={!selected.includes(account.id) && selected.length >= 100}
                    onChange={(event) => {
                      const checked = event.target.checked
                      setSelected((previous) =>
                        checked
                          ? [...new Set([...previous, account.id])]
                          : previous.filter((id) => id !== account.id),
                      )
                      clearResult()
                    }}
                  />
                  <span>
                    {account.name}
                    {!account.is_active && ' · Arquivada'}
                  </span>
                </label>
              ))}
              <p className="field-hint">
                {selected.length} conta(s) selecionada(s). Carregue mais opções para incluir contas
                de outras páginas.
              </p>
              {accounts.has_more && (
                <Button type="button" variant="outline" onClick={() => loadAccounts()}>
                  Carregar mais contas para o consolidado
                </Button>
              )}
              <Button type="button" variant="outline" onClick={() => loadAccounts(true)}>
                Atualizar contas e limpar seleção
              </Button>
            </fieldset>
          )}
          <Button
            type="submit"
            className="wide-button"
            disabled={scope === 'selected' && listLoading}
          >
            {busy ? 'Consultando…' : 'Consultar consolidado'}
          </Button>
        </fieldset>
      </form>
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
      {result && (
        <div role="status" className="balance-result consolidated-result">
          <p>
            {scopeNames[result.scope]} · {result.account_count} conta(s) ·{' '}
            {formatDate(result.as_of)}
          </p>
          <strong>{formatMoney(result.balance)}</strong>
          {result.account_count === 0 && <p>Nenhuma conta incluída neste filtro.</p>}
          {result.scope === 'selected' && (
            <ul aria-label="Contas da consulta">
              {result.names.map((name, index) => (
                <li key={index}>{name}</li>
              ))}
            </ul>
          )}
          <p className="field-hint">
            Posição consultada. Consulte novamente para refletir alterações posteriores.
          </p>
        </div>
      )}
      <p className="field-hint">
        Uma transferência entre duas contas incluídas se cancela no total. Se apenas um lado estiver
        incluído, o total filtrado muda pelo valor que entrou ou saiu.
      </p>
    </section>
  )
}
