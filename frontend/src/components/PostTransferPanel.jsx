import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/services/api'
import { formatDate, formatMoney } from '@/lib/money'

export default function PostTransferPanel({
  ownerId,
  transferId,
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
  const [error, setError] = useState('')
  const heading = useRef(null)
  const live = useRef(false)
  const sending = useRef(false)

  useEffect(() => {
    let current = true
    live.current = true
    sending.current = true
    heading.current?.focus()
    api
      .transfer(ownerId, transferId)
      .then((result) => {
        if (!current) return
        setSnapshot(result)
        if (result.data.status === 'posted') onResolved(result.data)
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
  }, [ownerId, transferId, onExpired, onResolved])

  async function reload() {
    if (sending.current) return
    sending.current = true
    setLoading(true)
    setError('')
    try {
      const result = await api.transfer(ownerId, transferId)
      if (!live.current) return
      setSnapshot(result)
      setBlocked(false)
      if (result.data.status === 'posted') onResolved(result.data)
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else setError(errorMessage(failure, 'Não foi possível consultar a situação.'))
    } finally {
      sending.current = false
      if (live.current) setLoading(false)
    }
  }

  async function confirm() {
    if (sending.current || blocked || disabled || snapshot?.data.status !== 'planned') return
    sending.current = true
    setBusy(true)
    setError('')
    onAttempt()
    try {
      const result = await api.postTransfer(ownerId, transferId, snapshot.etag)
      if (!live.current) return
      setSnapshot(result)
      onResolved(result.data)
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else {
        setBlocked(true)
        setError(
          failure.status === 412
            ? 'Os dados desta transferência mudaram. Recarregue a situação e confira novamente antes de confirmar.'
            : failure.status === 422
              ? 'Não foi possível efetivar. Confira se as duas contas estão ativas e se a data é posterior à abertura de ambas.'
              : failure.status === 0 || failure.status >= 500
                ? 'Não foi possível confirmar o resultado. Recarregue a situação para conferir se a transferência já foi efetivada.'
                : errorMessage(
                    failure,
                    'Não foi possível confirmar o resultado. Recarregue a situação antes de tentar novamente.',
                  ),
        )
      }
    } finally {
      sending.current = false
      if (live.current) setBusy(false)
    }
  }

  const item = snapshot?.data
  return (
    <section
      className="surface account-form posting-panel"
      aria-labelledby="transfer-post-heading"
      aria-busy={busy || loading}
    >
      <p className="eyebrow">Confira antes de efetivar</p>
      <h3 id="transfer-post-heading" tabIndex={-1} ref={heading}>
        Efetivar transferência
      </h3>
      {loading && <p role="status">Consultando a situação atual…</p>}
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
      {item && (
        <>
          <p>
            <strong>{item.description || 'Transferência entre contas'}</strong>
          </p>
          <p>
            {item.from_account_name} → {item.to_account_name}
          </p>
          <p>
            Transferência de {formatMoney(item.amount)} em {formatDate(item.effective_date)}.
          </p>
          {item.status === 'posted' ? (
            <p role="status" className="notice notice-success">
              Esta transferência já está efetivada.
            </p>
          ) : (
            <>
              <p className="field-hint">
                A efetivação fará o valor sair da origem e entrar no destino a partir da data
                informada. Valor, contas e data serão mantidos. Não haverá nova transferência ou
                lançamento de receita/despesa.
              </p>
              <Button
                type="button"
                className="wide-button"
                disabled={busy || loading || blocked || disabled}
                onClick={confirm}
              >
                {busy ? 'Efetivando…' : 'Confirmar efetivação'}
              </Button>
            </>
          )}
        </>
      )}
      {(!snapshot || blocked) && !loading && (
        <Button type="button" variant="outline" disabled={busy} onClick={reload}>
          Recarregar situação
        </Button>
      )}
      <Button type="button" variant="outline" disabled={busy || loading} onClick={onClose}>
        Voltar ao histórico
      </Button>
    </section>
  )
}
