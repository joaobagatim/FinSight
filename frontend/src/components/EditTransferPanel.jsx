import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/services/api'
import { formatDate, formatMoney, parseMoney } from '@/lib/money'

export default function EditTransferPanel({
  ownerId,
  transferId,
  accounts,
  loadingAccounts,
  hasMoreAccounts,
  onMoreAccounts,
  disabled,
  onExpired,
  onResolved,
  onAttempt,
  onClose,
}) {
  const [snapshot, setSnapshot] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [blocked, setBlocked] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')
  const heading = useRef(null)
  const live = useRef(false)
  const sending = useRef(false)
  const attempted = useRef(null)
  useEffect(() => {
    let current = true
    live.current = true
    sending.current = true
    heading.current?.focus()
    api
      .transfer(ownerId, transferId)
      .then((result) => {
        if (current) setSnapshot(result)
      })
      .catch((failure) => {
        if (!current) return
        if (failure.status === 401) onExpired()
        else setError(errorMessage(failure, 'Não foi possível consultar esta transferência.'))
      })
      .finally(() => {
        if (current) {
          sending.current = false
          setLoading(false)
        }
      })
    return () => {
      current = false
      live.current = false
    }
  }, [ownerId, transferId, onExpired])
  async function reload() {
    if (sending.current) return
    sending.current = true
    setLoading(true)
    setError('')
    try {
      const result = await api.transfer(ownerId, transferId)
      if (!live.current) return
      const matches =
        attempted.current &&
        Object.entries(attempted.current).every(([key, value]) => result.data[key] === value)
      setSnapshot(result)
      setBlocked(false)
      setSaved(Boolean(matches))
      attempted.current = null
      onResolved(result.data)
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else
        setError(errorMessage(failure, 'Não foi possível consultar a situação da transferência.'))
    } finally {
      sending.current = false
      if (live.current) setLoading(false)
    }
  }
  async function save(data) {
    if (sending.current || blocked || disabled || loadingAccounts || !snapshot) return
    sending.current = true
    attempted.current = data
    setBusy(true)
    setError('')
    onAttempt()
    try {
      const result = await api.updateTransfer(ownerId, transferId, data, snapshot.etag)
      if (!live.current) return
      if (result.data.status !== snapshot.data.status) throw new Error('Unexpected transfer status')
      setSnapshot(result)
      setSaved(true)
      attempted.current = null
      onResolved(result.data)
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else {
        setBlocked(true)
        setError(
          failure.status === 412
            ? 'Esta transferência mudou em outra operação. Recarregue a situação e revise os dados antes de salvar.'
            : failure.status === 422
              ? 'Confira duas contas ativas e distintas, valor positivo e data posterior à abertura de ambas.'
              : 'Não foi possível confirmar o resultado. Recarregue a situação antes de tentar salvar novamente.',
        )
      }
    } finally {
      sending.current = false
      if (live.current) setBusy(false)
    }
  }
  return (
    <section
      className="surface account-form posting-panel transfer-edit-panel"
      aria-labelledby="edit-transfer-heading"
      aria-busy={busy || loading}
    >
      <p className="eyebrow">Revise os dois lados da transferência</p>
      <h3 id="edit-transfer-heading" tabIndex={-1} ref={heading}>
        Editar transferência
      </h3>
      <p className="field-hint">
        A edição mantém a situação atual. Em efetivadas, corrige os saldos das contas e datas
        envolvidas na mesma gravação, sem criar receita ou despesa. Planejadas continuam fora do
        saldo real até a confirmação de efetivação.
      </p>
      {loading && <p role="status">Consultando a situação atual…</p>}
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
      {saved && snapshot ? (
        <div role="status" className="notice notice-success">
          <p>Os dados conferidos estão salvos nesta transferência.</p>
          <p>
            {snapshot.data.from_account_name} → {snapshot.data.to_account_name}
          </p>
          <p>
            {formatMoney(snapshot.data.amount)} · {formatDate(snapshot.data.effective_date)} ·{' '}
            {snapshot.data.status === 'posted' ? 'Efetivada' : 'Planejada'}
          </p>
        </div>
      ) : (
        snapshot &&
        !loading && (
          <EditFields
            key={snapshot.etag}
            item={snapshot.data}
            accounts={accounts}
            disabled={busy || blocked || disabled || loadingAccounts}
            onSave={save}
          />
        )
      )}
      {hasMoreAccounts && (
        <Button
          type="button"
          variant="outline"
          disabled={busy || loadingAccounts || disabled}
          onClick={onMoreAccounts}
        >
          Mais contas para editar transferência
        </Button>
      )}
      {(!snapshot || blocked) && !loading && (
        <>
          <p className="field-hint">
            Recarregar consulta o servidor e substitui o rascunho pelos dados atuais, sem enviar
            outra edição.
          </p>
          <Button type="button" variant="outline" disabled={busy} onClick={reload}>
            Recarregar situação
          </Button>
        </>
      )}
      <Button type="button" variant="outline" disabled={busy || loading} onClick={onClose}>
        Voltar às transferências
      </Button>
    </section>
  )
}

function EditFields({ item, accounts, disabled, onSave }) {
  const [fromId, setFromId] = useState(item.from_account_id)
  const [toId, setToId] = useState(item.to_account_id)
  const [amount, setAmount] = useState(item.amount.replace('.', ','))
  const [date, setDate] = useState(item.effective_date)
  const [description, setDescription] = useState(item.description ?? '')
  const [error, setError] = useState('')
  const active = accounts.filter((account) => account.is_active)
  function submit(event) {
    event.preventDefault()
    if (disabled) return
    setError('')
    try {
      const money = parseMoney(amount)
      const source = active.find((account) => account.id === fromId)
      const target = active.find((account) => account.id === toId)
      if (money.startsWith('-') || money === '0.00')
        throw new Error('Informe um valor maior que zero.')
      if (!source || !target || fromId === toId)
        throw new Error(
          'Selecione duas contas ativas e distintas; carregue mais opções se necessário.',
        )
      if (!date || date <= source.opening_date || date <= target.opening_date)
        throw new Error('A data deve ser posterior à abertura das duas contas.')
      if (Array.from(description.trim()).length > 255)
        throw new Error('Use até 255 caracteres na descrição.')
      onSave({
        from_account_id: fromId,
        to_account_id: toId,
        amount: money,
        effective_date: date,
        description: description.trim() || null,
      })
    } catch (failure) {
      setError(failure.message)
    }
  }
  return (
    <form onSubmit={submit} aria-label="Editar dados da transferência">
      <fieldset disabled={disabled}>
        <legend className="sr-only">Dados para edição da transferência</legend>
        <p className="field-hint">
          Situação atual: {item.status === 'posted' ? 'Efetivada' : 'Planejada'}. Ela não será
          alterada por este formulário.
        </p>
        <label className="field" htmlFor="edit-transfer-from">
          Origem da edição
          <select
            id="edit-transfer-from"
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
            {!active.some((account) => account.id === item.from_account_id) && (
              <option value={item.from_account_id} disabled>
                {item.from_account_name} (atual; carregue ou escolha outra)
              </option>
            )}
          </select>
        </label>
        <label className="field" htmlFor="edit-transfer-to">
          Destino da edição
          <select
            id="edit-transfer-to"
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
            {!active.some((account) => account.id === item.to_account_id) && (
              <option value={item.to_account_id} disabled>
                {item.to_account_name} (atual; carregue ou escolha outra)
              </option>
            )}
          </select>
        </label>
        <label className="field" htmlFor="edit-transfer-amount">
          Valor da edição (R$)
          <input
            id="edit-transfer-amount"
            required
            inputMode="decimal"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
          />
        </label>
        <label className="field" htmlFor="edit-transfer-date">
          Data da edição
          <input
            id="edit-transfer-date"
            type="date"
            required
            value={date}
            onChange={(event) => setDate(event.target.value)}
          />
        </label>
        <label className="field" htmlFor="edit-transfer-description">
          Descrição da edição (opcional)
          <input
            id="edit-transfer-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <Button type="submit" className="wide-button">
          Salvar alterações da transferência
        </Button>
      </fieldset>
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
    </form>
  )
}
