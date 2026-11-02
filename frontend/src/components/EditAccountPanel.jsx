import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/services/api'
import { formatDate, formatMoney } from '@/lib/money'

const types = {
  checking: 'Conta corrente',
  savings: 'Poupança',
  cash: 'Dinheiro',
  investment: 'Investimentos',
}

export default function EditAccountPanel({ ownerId, intent, onExpired, onCancel, onSaved }) {
  const [snapshot, setSnapshot] = useState(null)
  const [name, setName] = useState('')
  const [type, setType] = useState('checking')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [blocked, setBlocked] = useState(false)
  const live = useRef(false)
  const sending = useRef(false)
  const heading = useRef(null)

  const load = useCallback(async () => {
    if (sending.current) return
    sending.current = true
    try {
      const result = await api.account(ownerId, intent.id)
      if (!live.current) return
      setSnapshot(result)
      setName(result.data.name)
      setType(result.data.type)
      setBlocked(false)
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else setError(errorMessage(failure, 'Não foi possível consultar esta conta.'))
    } finally {
      sending.current = false
      if (live.current) setLoading(false)
    }
  }, [ownerId, intent.id, onExpired])

  useEffect(() => {
    let current = true
    live.current = true
    sending.current = true
    heading.current?.focus()
    api
      .account(ownerId, intent.id)
      .then((result) => {
        if (!current) return
        setSnapshot(result)
        setName(result.data.name)
        setType(result.data.type)
      })
      .catch((failure) => {
        if (!current) return
        if (failure.status === 401) onExpired()
        else setError(errorMessage(failure, 'Não foi possível consultar esta conta.'))
      })
      .finally(() => {
        if (!current) return
        sending.current = false
        setLoading(false)
      })
    return () => {
      current = false
      live.current = false
    }
  }, [ownerId, intent.id, onExpired])

  async function save(event) {
    event.preventDefault()
    if (sending.current || !snapshot || blocked) return
    if (!intent.archive && (!name.trim() || Array.from(name.trim()).length > 100)) {
      setError('Informe um nome com até 100 caracteres.')
      return
    }
    sending.current = true
    setBusy(true)
    setError('')
    try {
      await api.updateAccount(
        ownerId,
        intent.id,
        intent.archive ? { is_active: intent.active } : { name: name.trim(), type },
        snapshot.etag,
      )
      if (live.current)
        onSaved(intent.archive ? 'Estado da conta atualizado.' : 'Conta atualizada.')
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else {
        setBlocked(true)
        setError(
          failure.status === 412
            ? 'Esta conta foi alterada em outro lugar. Suas alterações não foram salvas. Recarregue os dados e revise antes de salvar.'
            : 'Não foi possível confirmar a alteração. Recarregue os dados para conferir o estado da conta antes de tentar novamente.',
        )
      }
    } finally {
      sending.current = false
      if (live.current) setBusy(false)
    }
  }

  const title = intent.archive
    ? intent.active
      ? 'Reativar conta'
      : 'Arquivar conta'
    : 'Editar conta'
  const alreadyApplied = intent.archive && snapshot?.data.is_active === intent.active
  return (
    <section
      className="surface account-form"
      aria-labelledby="edit-account-heading"
      aria-busy={loading || busy}
    >
      <p className="eyebrow">Cuide das suas contas</p>
      <h2 id="edit-account-heading" tabIndex={-1} ref={heading}>
        {title}
      </h2>
      {loading && <p role="status">Consultando os dados atuais…</p>}
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
      {snapshot && (
        <form onSubmit={save} aria-label={title}>
          <fieldset disabled={busy || loading || blocked || alreadyApplied}>
            <legend className="sr-only">Alteração da conta</legend>
            {intent.archive ? (
              <>
                <p>
                  <strong>{snapshot.data.name}</strong>
                </p>
                <p>
                  {intent.active
                    ? 'A conta voltará a ficar ativa.'
                    : 'A conta ficará arquivada. Seu histórico financeiro será preservado e você poderá reativá-la.'}
                </p>
              </>
            ) : (
              <>
                <label className="field" htmlFor="edit-account-name">
                  Nome da conta
                  <input
                    id="edit-account-name"
                    value={name}
                    required
                    onChange={(event) => setName(event.target.value)}
                  />
                </label>
                <div className="field">
                  <label htmlFor="edit-account-type">Tipo de conta</label>
                  <select
                    id="edit-account-type"
                    value={type}
                    onChange={(event) => setType(event.target.value)}
                  >
                    {Object.entries(types).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </div>
              </>
            )}
            <p className="field-hint">
              Saldo inicial: {formatMoney(snapshot.data.opening_balance)}. Posição ao final de{' '}
              {formatDate(snapshot.data.opening_date)}. Esses dados permanecem protegidos nesta
              edição.
            </p>
            <Button type="submit" className="wide-button">
              {busy ? 'Salvando…' : intent.archive ? 'Confirmar alteração' : 'Salvar alterações'}
            </Button>
          </fieldset>
          {alreadyApplied && <p role="status">A conta já está no estado solicitado.</p>}
        </form>
      )}
      {(!snapshot || blocked) && !loading && (
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            setLoading(true)
            setError('')
            void load()
          }}
        >
          Recarregar dados
        </Button>
      )}
      <Button type="button" variant="outline" disabled={busy || loading} onClick={onCancel}>
        Voltar para contas
      </Button>
    </section>
  )
}
