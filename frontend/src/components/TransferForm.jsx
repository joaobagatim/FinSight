import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/services/api'
import { parseMoney, formatMoney, today } from '@/lib/money'

export default function TransferForm({
  ownerId,
  disabled = false,
  accounts,
  loading,
  intent,
  onIntent,
  onExpired,
  onSaved,
  onAttempt,
}) {
  const [fromId, setFromId] = useState(intent?.data.from_account_id ?? '')
  const [toId, setToId] = useState(intent?.data.to_account_id ?? '')
  const [amount, setAmount] = useState(intent?.data.amount.replace('.', ',') ?? '')
  const [date, setDate] = useState(intent?.data.effective_date ?? today())
  const [status, setStatus] = useState(intent?.data.status ?? '')
  const [description, setDescription] = useState(intent?.data.description ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const live = useRef(false)
  const sending = useRef(false)
  const active = accounts.filter((account) => account.is_active)
  useEffect(() => {
    live.current = true
    return () => {
      live.current = false
    }
  }, [])

  async function persist(pending) {
    if (sending.current || disabled) return
    sending.current = true
    onIntent({ ...pending, uncertain: true })
    onAttempt()
    setBusy(true)
    setError('')
    setSuccess('')
    try {
      await api.createTransfer(ownerId, pending.data, pending.key)
      if (!live.current) return
      onIntent(null)
      setAmount('')
      setDescription('')
      setStatus('')
      setSuccess('Transferência cadastrada. Consulte o saldo das duas contas na data desejada.')
      onSaved()
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else {
        onIntent({
          ...pending,
          conflict: failure.status === 409,
          uncertain: pending.uncertain || ![403, 422, 429, 409].includes(failure.status),
          rejected: [403, 422].includes(failure.status),
        })
        setError(
          failure.status === 409
            ? 'Esta tentativa tem dados diferentes dos já recebidos. Confira o histórico antes de iniciar outra.'
            : failure.status === 422
              ? 'Confira se as duas contas estão ativas, são distintas e se a data é posterior à abertura de ambas.'
              : errorMessage(
                  failure,
                  'Não foi possível confirmar o cadastro. Confira o histórico antes de outra tentativa.',
                ),
        )
      }
    } finally {
      sending.current = false
      if (live.current) setBusy(false)
    }
  }

  function submit(event) {
    event.preventDefault()
    if (sending.current || intent || loading || disabled) return
    setError('')
    try {
      const money = parseMoney(amount)
      if (money.startsWith('-') || money === '0.00')
        throw new Error('Informe um valor maior que zero.')
      const from = active.find((account) => account.id === fromId)
      const to = active.find((account) => account.id === toId)
      if (!from || !to || fromId === toId)
        throw new Error('Selecione duas contas ativas e distintas.')
      if (!date || date <= from.opening_date || date <= to.opening_date)
        throw new Error('A data deve ser posterior à abertura das duas contas.')
      if (!['planned', 'posted'].includes(status) || Array.from(description.trim()).length > 255)
        throw new Error('Confira a situação e a descrição (até 255 caracteres).')
      persist({
        ownerId,
        key: crypto.randomUUID(),
        fromName: from.name,
        toName: to.name,
        data: {
          from_account_id: fromId,
          to_account_id: toId,
          amount: money,
          status,
          effective_date: date,
          description: description.trim() || null,
        },
      })
    } catch (failure) {
      setError(failure.message)
    }
  }

  return (
    <section className="surface account-form" aria-labelledby="transfer-form-heading">
      <p className="eyebrow">Entre suas próprias contas</p>
      <h2 id="transfer-form-heading">Nova transferência</h2>
      <p className="field-hint">
        Efetivadas saem de uma conta e entram na outra na mesma data, sem criar receita ou despesa.
        Planejadas não alteram o saldo real.
      </p>
      {success && (
        <p role="status" className="notice notice-success">
          {success}
        </p>
      )}
      <form onSubmit={submit} aria-label="Nova transferência">
        <fieldset disabled={disabled || busy || loading || Boolean(intent)}>
          <legend className="sr-only">Dados da transferência</legend>
          <div className="field">
            <label htmlFor="transfer-from">Conta de origem</label>
            <select
              id="transfer-from"
              required
              value={fromId}
              onChange={(event) => setFromId(event.target.value)}
            >
              <option value="">Selecione uma conta ativa</option>
              {active.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}
                </option>
              ))}
              {intent && !active.some((account) => account.id === fromId) && (
                <option value={fromId}>{intent.fromName}</option>
              )}
            </select>
          </div>
          <div className="field">
            <label htmlFor="transfer-to">Conta de destino</label>
            <select
              id="transfer-to"
              required
              value={toId}
              onChange={(event) => setToId(event.target.value)}
            >
              <option value="">Selecione outra conta ativa</option>
              {active.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}
                </option>
              ))}
              {intent && !active.some((account) => account.id === toId) && (
                <option value={toId}>{intent.toName}</option>
              )}
            </select>
          </div>
          <label className="field" htmlFor="transfer-amount">
            Valor da transferência (R$)
            <input
              id="transfer-amount"
              required
              inputMode="decimal"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
          </label>
          <label className="field" htmlFor="transfer-date">
            Data da transferência
            <input
              id="transfer-date"
              type="date"
              required
              value={date}
              onChange={(event) => setDate(event.target.value)}
            />
          </label>
          <div className="field">
            <label htmlFor="transfer-status">Situação da transferência</label>
            <select
              id="transfer-status"
              required
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            >
              <option value="">Selecione a situação</option>
              <option value="posted">Efetivada</option>
              <option value="planned">Planejada</option>
            </select>
          </div>
          <label className="field" htmlFor="transfer-description">
            Descrição da transferência (opcional)
            <input
              id="transfer-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </label>
          <Button type="submit" className="wide-button">
            {busy ? 'Salvando…' : 'Cadastrar transferência'}
          </Button>
        </fieldset>
      </form>
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
      {intent && (
        <div className="retry-account">
          <p>
            Em conferência: {intent.fromName} → {intent.toName} · {formatMoney(intent.data.amount)}.
          </p>
          <p>
            A tentativa está preservada. Recarregar ou sair perde esta intenção; confira o histórico
            antes de iniciar outra. Encerrar a tentativa não cancela uma transferência já salva.
          </p>
          {!busy && !intent.conflict && (
            <Button type="button" className="wide-button" onClick={() => persist(intent)}>
              Conferir e repetir transferência
            </Button>
          )}
          {!busy && intent.rejected && !intent.uncertain && !intent.conflict && (
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                onIntent(null)
                setError('Revise os dados antes de cadastrar novamente.')
              }}
            >
              Revisar transferência
            </Button>
          )}
          {!busy && (intent.conflict || intent.uncertain) && (
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                onIntent(null)
                setAmount('')
                setDescription('')
                setStatus('')
                setError('')
              }}
            >
              Conferi o histórico: encerrar transferência
            </Button>
          )}
        </div>
      )}
    </section>
  )
}
