import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api } from '@/services/api'
import { formatDate, formatMoney } from '@/lib/money'

export default function ReservationAlerts({ ownerId, revision, onExpired }) {
  const [result, setResult] = useState(null)
  const [failure, setFailure] = useState(null)
  const [refresh, setRefresh] = useState(0)
  const version = String(revision) + ':' + refresh
  useEffect(() => {
    let current = true
    api
      .reservationAlerts(ownerId)
      .then((data) => {
        if (current) {
          setResult({ data, version })
          setFailure(null)
        }
      })
      .catch((error) => {
        if (!current) return
        if (error.status === 401) onExpired()
        else setFailure(version)
      })
    return () => {
      current = false
    }
  }, [ownerId, onExpired, version])
  if (failure === version)
    return (
      <div className="notice notice-error reservation-alerts">
        <p role="status">
          Não foi possível conferir reservas. O resultado de outras operações deve ser consultado
          nas suas áreas.
        </p>
        <Button type="button" variant="outline" onClick={() => setRefresh((value) => value + 1)}>
          Conferir alertas de reservas
        </Button>
      </div>
    )
  if (result?.version !== version || !result.data.account_count) return null
  const data = result.data
  return (
    <section className="notice notice-error reservation-alerts" aria-label="Alertas de reservas">
      <p role="alert">
        Reservas comprometidas em {data.account_count} conta(s), na posição de{' '}
        {formatDate(data.as_of)}. As despesas continuam permitidas; nenhuma reserva foi liberada
        automaticamente.
      </p>
      <ul>
        {data.items.map((item) => (
          <li key={item.account.id}>
            {item.account.name}: {formatMoney(item.uncovered_reserved)} da reserva sem cobertura.
            Saldo livre: {formatMoney(item.free_balance)}.
          </li>
        ))}
      </ul>
      {data.account_count > data.items.length && (
        <p>
          Mostrando as primeiras {data.items.length} contas comprometidas. Confira a disponibilidade
          de cada conta em Metas.
        </p>
      )}
      <Button type="button" variant="outline" onClick={() => setRefresh((value) => value + 1)}>
        Conferir alertas de reservas
      </Button>
    </section>
  )
}
