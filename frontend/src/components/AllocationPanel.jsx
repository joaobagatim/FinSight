import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api } from '@/services/api'
import { formatDate, formatMoney, parseMoney } from '@/lib/money'

const cents = (value) => BigInt(value.replace('.', ''))

export default function AllocationPanel({
  ownerId,
  goalId,
  intent,
  onIntent,
  onExpired,
  onChanged,
  onClose,
}) {
  const [accounts, setAccounts] = useState({ items: [], has_more: false })
  const [summary, setSummary] = useState(null)
  const [history, setHistory] = useState({ items: [], has_more: false })
  const [accountId, setAccountId] = useState(intent?.data.account_id ?? '')
  const [snapshot, setSnapshot] = useState(null)
  const [kind, setKind] = useState(intent?.data.kind ?? 'reserve')
  const [amount, setAmount] = useState(intent?.data.amount.replace('.', ',') ?? '')
  const [notes, setNotes] = useState(intent?.data.notes ?? '')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const initialAccount = useRef(intent?.data.account_id ?? '')
  const live = useRef(false),
    sending = useRef(false),
    fetching = useRef(true),
    version = useRef(0),
    heading = useRef(null)
  useEffect(() => {
    let current = true
    live.current = true
    heading.current?.focus()
    Promise.all([
      api.accounts(ownerId),
      api.goalFunding(ownerId, goalId),
      api.allocations(ownerId, goalId),
      ...(initialAccount.current
        ? [api.allocationContext(ownerId, goalId, initialAccount.current)]
        : []),
    ])
      .then(([a, f, h, c]) => {
        if (current) {
          setAccounts(a)
          setSummary(f)
          setHistory(h)
          if (c) setSnapshot(c)
        }
      })
      .catch((failure) => {
        if (!current) return
        if (failure.status === 401) onExpired()
        else setError('Não foi possível carregar reservas e contas. Recarregue a situação.')
      })
      .finally(() => {
        if (current) {
          fetching.current = false
          setLoading(false)
        }
      })
    return () => {
      current = false
      live.current = false
    }
  }, [ownerId, goalId, onExpired])

  async function reload() {
    if (fetching.current || sending.current) return
    fetching.current = true
    const request = ++version.current
    setLoading(true)
    setError('')
    setSnapshot(null)
    setSummary(null)
    setHistory({ items: [], has_more: false })
    try {
      const [a, f, h, c] = await Promise.all([
        api.accounts(ownerId),
        api.goalFunding(ownerId, goalId),
        api.allocations(ownerId, goalId),
        ...(accountId ? [api.allocationContext(ownerId, goalId, accountId)] : []),
      ])
      if (!live.current || request !== version.current) return
      setAccounts(a)
      setSummary(f)
      setHistory(h)
      if (c) setSnapshot(c)
      onChanged()
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else setError('Não foi possível conferir a posição das reservas.')
    } finally {
      fetching.current = false
      if (live.current) setLoading(false)
    }
  }
  async function choose(value) {
    if (fetching.current || sending.current) return
    setAccountId(value)
    setSnapshot(null)
    setError('')
    setNotice('')
    if (!value) return
    fetching.current = true
    const request = ++version.current
    setLoading(true)
    try {
      const result = await api.allocationContext(ownerId, goalId, value)
      if (live.current && request === version.current) setSnapshot(result)
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else setError('Não foi possível consultar esta conta e meta na data atual.')
    } finally {
      fetching.current = false
      if (live.current) setLoading(false)
    }
  }
  async function more(type) {
    if (fetching.current || sending.current) return
    fetching.current = true
    setLoading(true)
    setError('')
    try {
      const result =
        type === 'accounts'
          ? await api.accounts(ownerId, accounts.items.length)
          : await api.allocations(ownerId, goalId, history.items.length)
      if (!live.current) return
      const setter = type === 'accounts' ? setAccounts : setHistory
      setter((previous) => ({ ...result, items: [...previous.items, ...result.items] }))
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else setError('Não foi possível carregar mais resultados.')
    } finally {
      fetching.current = false
      if (live.current) setLoading(false)
    }
  }
  async function persist(pending) {
    if (sending.current || fetching.current) return
    sending.current = true
    setBusy(true)
    setError('')
    setNotice('')
    onIntent(pending)
    let saved = false
    try {
      await api.createAllocation(ownerId, goalId, pending.data, pending.key, pending.etag)
      if (!live.current) return
      saved = true
      onIntent(null)
      setAmount('')
      setNotes('')
      setNotice(
        pending.data.kind === 'reserve'
          ? 'Reserva registrada. O saldo bancário não foi reduzido.'
          : 'Retirada registrada. O saldo bancário não foi alterado.',
      )
      onChanged()
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else {
        const rejected = [409, 412, 422].includes(failure.status)
        onIntent({ ...pending, rejected })
        setError(
          failure.status === 412
            ? 'A posição mudou. Recarregue e revise antes de iniciar outra operação.'
            : failure.status === 422
              ? 'Confira a data de hoje, a situação da meta/conta, o saldo livre e a reserva desta meta nesta conta.'
              : 'Não foi possível confirmar o resultado. Preserve esta tentativa para conferir e repetir com a mesma chave.',
        )
      }
    } finally {
      sending.current = false
      if (live.current) setBusy(false)
    }
    if (saved && live.current) await reload()
  }
  function submit(event) {
    event.preventDefault()
    if (!snapshot || intent || busy || loading) return
    setError('')
    try {
      const value = parseMoney(amount),
        data = snapshot.data
      if (value.startsWith('-') || value === '0.00')
        throw new Error('Informe um valor maior que zero.')
      if (
        kind === 'reserve' &&
        (!data.availability.account.is_active ||
          data.funding.goal.status !== 'active' ||
          cents(value) > cents(data.availability.free_balance))
      )
        throw new Error('Nova reserva exige conta e meta ativas e saldo livre suficiente.')
      if (kind === 'withdraw' && cents(value) > cents(data.reserved_in_account))
        throw new Error('A retirada não pode superar a reserva desta meta nesta conta.')
      if (Array.from(notes.trim()).length > 2000)
        throw new Error('Use até 2.000 caracteres nas observações.')
      persist({
        ownerId,
        goalId,
        key: crypto.randomUUID(),
        etag: snapshot.etag,
        accountName: data.availability.account.name,
        data: {
          account_id: accountId,
          kind,
          amount: value,
          allocation_date: data.funding.as_of,
          notes: notes.trim() || null,
        },
      })
    } catch (failure) {
      setError(failure.message)
    }
  }
  const funding = snapshot?.data.funding ?? summary
  const availability = snapshot?.data.availability
  return (
    <section
      className="surface account-form goals-panel allocation-panel"
      aria-labelledby="allocation-heading"
      aria-busy={loading || busy}
    >
      <h3 id="allocation-heading" tabIndex={-1} ref={heading}>
        Reservas e progresso
      </h3>
      <p className="field-hint">
        Reservar compromete parte do dinheiro de uma conta; não cria transferência ou despesa.
        Operações são registradas hoje, na data de São Paulo. Retiradas liberam somente o
        compromisso desta meta e conta. Sair não cancela uma gravação já concluída.
      </p>
      {loading && <p role="status">Consultando reservas…</p>}
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="notice notice-success">
          {notice}
        </p>
      )}
      {funding && (
        <div className="funding-result">
          <h4>{funding.goal.name}</h4>
          <p>Posição de {formatDate(funding.as_of)}</p>
          <p>Reservado na meta: {formatMoney(funding.reserved_amount)}</p>
          <p>Faltante: {formatMoney(funding.remaining_amount)}</p>
          <p>Progresso: {funding.progress_percent.replace('.', ',')}%</p>
          {funding.excess_amount !== '0.00' && (
            <p>Excedente: {formatMoney(funding.excess_amount)}</p>
          )}
        </div>
      )}
      <form onSubmit={submit} aria-label="Reservar ou retirar valor">
        <fieldset disabled={loading || busy || Boolean(intent)}>
          <legend className="sr-only">Operação de reserva</legend>
          <label className="field" htmlFor="reservation-account">
            Conta da reserva
            <select
              id="reservation-account"
              value={accountId}
              required
              onChange={(event) => void choose(event.target.value)}
            >
              <option value="">Selecione uma conta</option>
              {accounts.items.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}
                  {!account.is_active ? ' · Arquivada' : ''}
                </option>
              ))}
              {accountId && !accounts.items.some((account) => account.id === accountId) && (
                <option value={accountId}>
                  {intent?.accountName ?? availability?.account.name ?? 'Conta em conferência'}
                </option>
              )}
            </select>
          </label>
          {availability && (
            <div className="availability-result">
              <p>Saldo bancário: {formatMoney(availability.bank_balance)}</p>
              <p>Reservado na conta: {formatMoney(availability.reserved_amount)}</p>
              <p>Saldo livre: {formatMoney(availability.free_balance)}</p>
              <p>Reserva desta meta na conta: {formatMoney(snapshot.data.reserved_in_account)}</p>
              {availability.uncovered_reserved !== '0.00' && (
                <p>
                  Reserva sem cobertura: {formatMoney(availability.uncovered_reserved)}. Despesas
                  são permitidas; revise seus compromissos.
                </p>
              )}
            </div>
          )}
          <label className="field" htmlFor="allocation-kind">
            Operação
            <select
              id="allocation-kind"
              value={kind}
              onChange={(event) => setKind(event.target.value)}
            >
              <option value="reserve">Reservar</option>
              <option value="withdraw">Retirar reserva</option>
            </select>
          </label>
          <label className="field" htmlFor="allocation-amount">
            Valor da reserva ou retirada (R$)
            <input
              id="allocation-amount"
              required
              inputMode="decimal"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
          </label>
          <label className="field" htmlFor="allocation-notes">
            Observações da reserva (opcional)
            <input
              id="allocation-notes"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
          </label>
          <Button type="submit" className="wide-button" disabled={!snapshot}>
            Confirmar reserva ou retirada
          </Button>
        </fieldset>
      </form>
      {intent && (
        <div className="retry-account">
          <p>
            Em conferência: {intent.data.kind === 'reserve' ? 'reserva' : 'retirada'} de{' '}
            {formatMoney(intent.data.amount)} em {intent.accountName}. Recarregar a página perde
            esta intenção; confira o histórico antes de criar outra.
          </p>
          {!intent.rejected && (
            <Button type="button" disabled={busy || loading} onClick={() => persist(intent)}>
              Conferir e repetir operação de reserva
            </Button>
          )}
          <Button
            type="button"
            variant="outline"
            disabled={busy || loading}
            onClick={() => {
              onIntent(null)
              setError('')
              void reload()
            }}
          >
            Conferi o histórico: encerrar tentativa de reserva
          </Button>
        </div>
      )}
      <Button type="button" variant="outline" disabled={busy || loading} onClick={reload}>
        Recarregar reservas
      </Button>
      {accounts.has_more && (
        <Button
          type="button"
          variant="outline"
          disabled={busy || loading || Boolean(intent)}
          onClick={() => more('accounts')}
        >
          Mais contas para reserva
        </Button>
      )}
      <h4>Histórico de reservas</h4>
      <ul aria-label="Movimentos de reservas">
        {history.items.map((item) => (
          <li key={item.id}>
            {item.amount.startsWith('-') ? 'Retirada' : 'Reserva'} de{' '}
            {formatMoney(item.amount.replace(/^-/, ''))} · {item.account_name} ·{' '}
            {formatDate(item.allocation_date)}
            {item.notes ? ' · ' + item.notes : ''}
          </li>
        ))}
      </ul>
      {!loading && !error && !history.items.length && (
        <p>Nenhuma reserva ou retirada registrada nesta meta.</p>
      )}
      {history.has_more && (
        <Button
          type="button"
          variant="outline"
          disabled={busy || loading}
          onClick={() => more('history')}
        >
          Mais movimentos de reserva
        </Button>
      )}
      <Button type="button" variant="outline" disabled={busy || loading} onClick={onClose}>
        Voltar às metas
      </Button>
    </section>
  )
}
