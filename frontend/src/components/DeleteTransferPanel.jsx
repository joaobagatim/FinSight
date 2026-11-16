import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api, errorMessage } from '@/services/api'
import { formatDate, formatMoney } from '@/lib/money'

export default function DeleteTransferPanel({
  ownerId,
  transferId,
  disabled,
  onExpired,
  onRemoved,
  onAttempt,
  onClose,
}) {
  const [snapshot, setSnapshot] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [blocked, setBlocked] = useState(false)
  const [removed, setRemoved] = useState(false)
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
        if (current) setSnapshot(result)
      })
      .catch((failure) => {
        if (!current) return
        if (failure.status === 401) onExpired()
        else if (failure.status === 410) {
          setRemoved(true)
          onRemoved(transferId)
        } else setError(errorMessage(failure, 'Não foi possível consultar esta transferência.'))
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
  }, [ownerId, transferId, onExpired, onRemoved])

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
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else if (failure.status === 410) {
        setRemoved(true)
        onRemoved(transferId)
      } else setError(errorMessage(failure, 'Não foi possível consultar a situação.'))
    } finally {
      sending.current = false
      if (live.current) setLoading(false)
    }
  }

  async function confirm() {
    if (sending.current || blocked || disabled || removed || !snapshot) return
    sending.current = true
    setBusy(true)
    setError('')
    onAttempt()
    try {
      await api.deleteTransfer(ownerId, transferId, snapshot.etag)
      if (!live.current) return
      setRemoved(true)
      onRemoved(transferId)
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else {
        setBlocked(true)
        setError(
          failure.status === 412
            ? 'Os dados mudaram. Recarregue a situação e confira novamente antes de excluir.'
            : failure.status === 422
              ? 'Esta transferência não pode ser excluída por este fluxo.'
              : 'Não foi possível confirmar o resultado. Recarregue a situação antes de tentar excluir novamente.',
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
      className="surface account-form posting-panel deletion-panel transfer-deletion-panel"
      aria-labelledby="delete-transfer-heading"
      aria-busy={loading || busy}
    >
      <p className="eyebrow">Confira antes de excluir</p>
      <h3 id="delete-transfer-heading" tabIndex={-1} ref={heading}>
        Excluir transferência
      </h3>
      {loading && <p role="status">Consultando a situação atual…</p>}
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
      {removed ? (
        <p role="status" className="notice notice-success">
          Esta transferência não consta mais no histórico nem nos cálculos de saldo.
        </p>
      ) : (
        item && (
          <>
            <p>
              <strong>{item.description || 'Transferência entre contas'}</strong>
            </p>
            <p>
              {item.from_account_name} → {item.to_account_name}
            </p>
            <p>
              Transferência de {formatMoney(item.amount)} em {formatDate(item.effective_date)} ·{' '}
              {item.status === 'posted' ? 'Efetivada' : 'Planejada'}.
            </p>
            <p className="field-hint">
              A transferência sairá do histórico. Efetivadas deixam de compor o saldo das duas
              contas e as datas envolvidas; planejadas deixam a projeção. Esta ação não pode ser
              desfeita pela interface.
            </p>
            <p className="field-hint">
              Os dados desta transferência permanecem retidos internamente para impedir duplicidades
              em tentativas antigas de cadastro. A exclusão não apaga esses dados definitivamente.
            </p>
            <Button
              type="button"
              className="wide-button"
              disabled={busy || loading || blocked || disabled}
              onClick={confirm}
            >
              {busy ? 'Excluindo…' : 'Confirmar exclusão da transferência'}
            </Button>
          </>
        )
      )}
      {(!snapshot || blocked) && !loading && !removed && (
        <Button type="button" variant="outline" disabled={busy} onClick={reload}>
          Recarregar situação
        </Button>
      )}
      <Button type="button" variant="outline" disabled={busy || loading} onClick={onClose}>
        {removed ? 'Voltar às transferências' : 'Cancelar exclusão e voltar'}
      </Button>
    </section>
  )
}
