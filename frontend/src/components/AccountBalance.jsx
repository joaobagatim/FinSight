import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/services/api'
import { formatDate, formatMoney, today } from '@/lib/money'

export default function AccountBalance({ ownerId, accounts, loading, onExpired, revision }) {
  const [accountId, setAccountId] = useState('')
  const [date, setDate] = useState(today)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const live = useRef(false)
  const sending = useRef(false)
  useEffect(() => {
    live.current = true
    return () => {
      live.current = false
    }
  }, [])

  async function consult(event) {
    event.preventDefault()
    if (sending.current) return
    setResult(null)
    setError('')
    const account = accounts.find((item) => item.id === accountId)
    if (!account || !date || date < account.opening_date) {
      setError('Selecione uma conta e uma data igual ou posterior à abertura.')
      return
    }
    sending.current = true
    setBusy(true)
    try {
      const response = await api.balance(ownerId, accountId, date)
      if (live.current) {
        if (response.account_id !== accountId || response.as_of !== date)
          throw new Error('Unexpected balance response')
        setResult({ ...response, accountName: account.name, revision })
      }
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else setError(errorMessage(failure, 'Não foi possível consultar o saldo desta conta.'))
    } finally {
      sending.current = false
      if (live.current) setBusy(false)
    }
  }

  return (
    <section
      className="surface account-form balance-panel"
      aria-labelledby="balance-heading"
      aria-busy={busy}
    >
      <p className="eyebrow">Uma posição, uma data</p>
      <h2 id="balance-heading">Saldo real da conta</h2>
      <form onSubmit={consult} aria-label="Consultar saldo">
        <fieldset disabled={busy || loading}>
          <legend className="sr-only">Conta e data do saldo</legend>
          <div className="field">
            <label htmlFor="balance-account">Conta para consultar saldo</label>
            <select
              id="balance-account"
              value={accountId}
              onChange={(event) => {
                setAccountId(event.target.value)
                setResult(null)
                setError('')
              }}
              required
            >
              <option value="">Selecione uma conta</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}
                  {!account.is_active && ' · Arquivada'}
                </option>
              ))}
            </select>
          </div>
          <label className="field" htmlFor="balance-as-of">
            Saldo até a data
            <input
              id="balance-as-of"
              type="date"
              value={date}
              onChange={(event) => {
                setDate(event.target.value)
                setResult(null)
                setError('')
              }}
              required
            />
          </label>
          <Button type="submit" variant="outline" disabled={!accountId}>
            {busy ? 'Consultando…' : 'Consultar saldo'}
          </Button>
        </fieldset>
      </form>
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
      {result && result.revision === revision && (
        <div className="balance-result" role="status">
          <p>
            {result.accountName} · Saldo efetivado em {formatDate(result.as_of)}
          </p>
          <strong>{formatMoney(result.balance)}</strong>
          <p className="field-hint">
            Abertura: {formatMoney(result.opening_balance)} ao final de{' '}
            {formatDate(result.opening_date)}.
          </p>
        </div>
      )}
      <p className="field-hint">
        Inclui apenas efetivados até a data consultada. Planejados não entram neste saldo.
      </p>
    </section>
  )
}
