import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api } from '@/services/api'
import { formatDate } from '@/lib/money'

const reasons = {
  same_preview_fingerprint: 'Dados equivalentes a outro registro desta prévia.',
  same_preview_external_id: 'Referência externa repetida nesta prévia.',
  other_preview_fingerprint: 'Dados equivalentes em outra prévia desta conta.',
  other_preview_external_id: 'Mesma referência externa em outra prévia desta conta.',
  transaction_fingerprint: 'Dados equivalentes a um lançamento existente nesta conta.',
  transaction_external_id: 'Mesma referência externa de um lançamento existente nesta conta.',
}

export default function ImportDuplicates({ ownerId, jobId, onExpired }) {
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [shown, setShown] = useState(50)
  const live = useRef(false),
    working = useRef(false)
  useEffect(() => {
    live.current = true
    return () => {
      live.current = false
    }
  }, [])
  async function check() {
    if (working.current) return
    working.current = true
    setBusy(true)
    setError('')
    setResult(null)
    setShown(50)
    try {
      const report = await api.importDuplicates(ownerId, jobId)
      if (live.current) setResult(report)
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else
        setError(
          'Não foi possível conferir duplicatas. Tente novamente; a ausência de um relatório não significa ausência de coincidências.',
        )
    } finally {
      working.current = false
      if (live.current) setBusy(false)
    }
  }
  return (
    <section aria-labelledby="import-duplicates-heading" aria-busy={busy}>
      <h3 id="import-duplicates-heading">Possíveis duplicatas</h3>
      <p className="field-hint">
        Os avisos ajudam na revisão; compras iguais podem ser legítimas. A conferência não exclui,
        desmarca ou confirma registros. Lançamentos planejados também são considerados. Repita após
        novas prévias ou alterações em outra tela.
      </p>
      <Button type="button" variant="outline" disabled={busy} onClick={check}>
        Verificar possíveis duplicatas
      </Button>
      {busy && <p role="status">Conferindo coincidências nesta conta…</p>}
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
      {result && (
        <>
          <p role="status">
            Conferidos {result.checked_rows} registros. {result.unchecked_rows} registros inválidos,
            ignorados ou incompletos ficaram fora da comparação por dados e referência.
          </p>
          {result.period_start && (
            <p>
              Período das datas interpretadas: {formatDate(result.period_start)} a{' '}
              {formatDate(result.period_end)}.
            </p>
          )}
          {result.overlapping_period && (
            <p className="notice notice-error">
              Há outra prévia desta conta com período sobreposto. Isso não comprova duplicidade de
              cada registro.
            </p>
          )}
          {result.scan_limited && (
            <p role="alert" className="notice notice-error">
              A busca atingiu o limite de {result.candidate_limit} candidatos por fonte. O resultado
              é parcial e pode haver outras coincidências.
            </p>
          )}
          {result.items.length === 0 && (
            <p>
              {result.scan_limited
                ? 'Nenhuma coincidência encontrada na parte conferida.'
                : 'Nenhuma coincidência encontrada nos registros conferidos.'}{' '}
              Isso não garante que o arquivo esteja livre de duplicatas.
            </p>
          )}
          <ul aria-label="Avisos de possíveis duplicatas">
            {result.items.slice(0, shown).map((item) => (
              <li key={item.row_id}>
                <strong>Registro {item.row_number}</strong>
                <ul>
                  {item.reasons.map((reason) => (
                    <li key={reason}>
                      {reasons[reason] ?? 'Confira este registro no arquivo e no histórico.'}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
          {result.items.length > shown && (
            <Button type="button" variant="outline" onClick={() => setShown((value) => value + 50)}>
              Mostrar mais avisos de duplicatas
            </Button>
          )}
        </>
      )}
    </section>
  )
}
