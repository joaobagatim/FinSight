import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/services/api'
import { formatDate, formatMoney, parseMoney } from '@/lib/money'

export default function EditTransactionPanel({
  ownerId,
  transactionId,
  references,
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
      .transaction(ownerId, transactionId)
      .then((result) => {
        if (current) setSnapshot(result)
      })
      .catch((failure) => {
        if (!current) return
        if (failure.status === 401) onExpired()
        else setError(errorMessage(failure, 'Não foi possível consultar este lançamento.'))
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
  }, [ownerId, transactionId, onExpired])

  async function reload() {
    if (sending.current) return
    sending.current = true
    setLoading(true)
    setError('')
    try {
      const result = await api.transaction(ownerId, transactionId)
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
      else setError(errorMessage(failure, 'Não foi possível consultar a situação.'))
    } finally {
      sending.current = false
      if (live.current) setLoading(false)
    }
  }

  async function save(data) {
    if (sending.current || blocked || disabled || !snapshot) return
    sending.current = true
    attempted.current = data
    setBusy(true)
    setError('')
    onAttempt()
    try {
      const result = await api.updateTransaction(ownerId, transactionId, data, snapshot.etag)
      if (!live.current) return
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
            ? 'Este lançamento mudou em outra operação. Recarregue a situação e revise os dados antes de salvar.'
            : failure.status === 422
              ? 'Confira conta e categoria ativas, tipo e data posterior à abertura. Lançamentos importados não podem ser editados neste fluxo.'
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
      className="surface account-form posting-panel editing-panel"
      aria-labelledby="edit-heading"
      aria-busy={loading || busy}
    >
      <p className="eyebrow">Revise os dados do movimento</p>
      <h3 id="edit-heading" tabIndex={-1} ref={heading}>
        Editar lançamento
      </h3>
      <p className="field-hint">
        Alterações em efetivados recalculam o saldo nas contas e datas envolvidas. A situação é
        mantida; use Efetivar para confirmar um planejado.
      </p>
      {loading && <p role="status">Consultando a situação atual…</p>}
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
      {saved && snapshot ? (
        <div role="status" className="notice notice-success">
          <p>Os dados conferidos estão salvos neste lançamento.</p>
          <p>
            {snapshot.data.description} · {formatMoney(snapshot.data.amount)} ·{' '}
            {formatDate(snapshot.data.effective_date)}
          </p>
          <p>
            {snapshot.data.account_name} · {snapshot.data.category_name}
          </p>
        </div>
      ) : (
        snapshot &&
        !loading && (
          <EditFields
            key={snapshot.etag}
            item={snapshot.data}
            references={references}
            disabled={busy || blocked || disabled}
            onSave={save}
          />
        )
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
        Voltar ao histórico
      </Button>
    </section>
  )
}

function EditFields({ item, references, disabled, onSave }) {
  const [description, setDescription] = useState(item.description)
  const [amount, setAmount] = useState(item.amount.replace('.', ','))
  const [date, setDate] = useState(item.effective_date)
  const [accountId, setAccountId] = useState(item.account_id)
  const [categoryId, setCategoryId] = useState(item.category_id)
  const [type, setType] = useState(item.type)
  const [notes, setNotes] = useState(item.notes ?? '')
  const [error, setError] = useState('')
  const accounts = references.accounts.filter((row) => row.is_active)
  const categories = references.categories.filter((row) => row.is_active && row.type === type)
  const account = accounts.find((row) => row.id === accountId)
  function submit(event) {
    event.preventDefault()
    if (disabled || references.loading) return
    setError('')
    try {
      const money = parseMoney(amount)
      if (money.startsWith('-') || money === '0.00')
        throw new Error('Informe um valor maior que zero.')
      if (!account || !categories.some((row) => row.id === categoryId))
        throw new Error(
          'Selecione conta ativa e categoria compatível. Atualize ou carregue mais opções abaixo do cadastro.',
        )
      if (!date || date <= account.opening_date)
        throw new Error('A data deve ser posterior à abertura da conta selecionada.')
      if (
        !description.trim() ||
        Array.from(description.trim()).length > 255 ||
        Array.from(notes.trim()).length > 2000
      )
        throw new Error('Confira a descrição (até 255 caracteres) e as observações (até 2000).')
      onSave({
        description: description.trim(),
        amount: money,
        effective_date: date,
        account_id: accountId,
        category_id: categoryId,
        type,
        notes: notes.trim() || null,
      })
    } catch (failure) {
      setError(failure.message)
    }
  }
  return (
    <form onSubmit={submit}>
      <fieldset disabled={disabled || references.loading}>
        <legend className="sr-only">Dados para edição do lançamento</legend>
        <label className="field" htmlFor="edit-description">
          Descrição da edição
          <input
            id="edit-description"
            required
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <label className="field" htmlFor="edit-type">
          Tipo da edição
          <select
            id="edit-type"
            value={type}
            onChange={(event) => {
              setType(event.target.value)
              setCategoryId('')
            }}
          >
            <option value="expense">Despesa</option>
            <option value="income">Receita</option>
          </select>
        </label>
        <label className="field" htmlFor="edit-account">
          Conta da edição
          <select
            id="edit-account"
            required
            value={accountId}
            onChange={(event) => setAccountId(event.target.value)}
          >
            <option value="">Selecione uma conta ativa</option>
            {accounts.map((row) => (
              <option key={row.id} value={row.id}>
                {row.name}
              </option>
            ))}
            {!accounts.some((row) => row.id === item.account_id) && (
              <option value={item.account_id} disabled>
                {item.account_name} (atual; carregue ou escolha outra)
              </option>
            )}
          </select>
        </label>
        <label className="field" htmlFor="edit-category">
          Categoria da edição
          <select
            id="edit-category"
            required
            value={categoryId}
            onChange={(event) => setCategoryId(event.target.value)}
          >
            <option value="">Selecione uma categoria compatível</option>
            {categories.map((row) => (
              <option key={row.id} value={row.id}>
                {row.name}
              </option>
            ))}
            {type === item.type && !categories.some((row) => row.id === item.category_id) && (
              <option value={item.category_id} disabled>
                {item.category_name} (atual; carregue ou escolha outra)
              </option>
            )}
          </select>
        </label>
        <label className="field" htmlFor="edit-amount">
          Valor da edição (R$)
          <input
            id="edit-amount"
            required
            inputMode="decimal"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
          />
        </label>
        <label className="field" htmlFor="edit-date">
          Data da edição
          <input
            id="edit-date"
            type="date"
            required
            value={date}
            onChange={(event) => setDate(event.target.value)}
          />
        </label>
        {account && (
          <p className="field-hint">
            A data deve ser posterior a {formatDate(account.opening_date)}.
          </p>
        )}
        <label className="field" htmlFor="edit-notes">
          Observações da edição
          <textarea
            id="edit-notes"
            rows={3}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
          />
        </label>
        <Button type="submit" className="wide-button">
          Salvar alterações do lançamento
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
