import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { api } from '@/services/api'
import { duplicateReasons } from '@/lib/imports'
import { formatDate, formatMoney } from '@/lib/money'

const emptyAcks = () => ({
  acknowledge_duplicates: false,
  acknowledge_classification: false,
  acknowledge_reservations: false,
})
const issueText = {
  preview_closed: 'Esta prévia não permite mais confirmação.',
  account_unavailable: 'A conta precisa estar ativa e disponível para importar.',
  empty_selection: 'Selecione pelo menos um registro na prévia.',
  invalid_selection: 'Confira os dados e as categorias ativas compatíveis dos selecionados.',
  existing_financial_links: 'A prévia já tem vínculos financeiros; confira o histórico.',
  counter_mismatch: 'Os registros e contadores precisam ser conferidos antes de importar.',
}
const positive = (value) =>
  typeof value === 'string' && /^-?\d+\.\d{2}$/.test(value) && BigInt(value.replace('.', '')) > 0n

function Amounts({ data }) {
  return (
    <>
      <p>
        Conta: {data.account_name}. Arquivo: {data.filename}.
      </p>
      <p>
        Posição em {formatDate(data.as_of)}. Datas posteriores só entram no saldo a partir da data
        original.
      </p>
      <dl className="import-summary">
        {[
          ['Receitas selecionadas', data.income_total],
          ['Despesas selecionadas', data.expense_total],
          ['Saldo antes', data.bank_balance_before],
          ['Saldo após importar', data.bank_balance_after],
          ['Reservas mantidas', data.reserved_amount],
          ['Saldo livre após importar', data.free_balance_after],
          ['Reserva descoberta após importar', data.uncovered_reserved_after],
        ].map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{formatMoney(value)}</dd>
          </div>
        ))}
      </dl>
      {positive(data.uncovered_reserved_after) && (
        <p role="status" className="notice notice-error">
          As despesas comprometem reservas em {formatMoney(data.uncovered_reserved_after)}. Elas não
          serão liberadas nem reduzidas automaticamente.
        </p>
      )}
      {data.future_rows > 0 && (
        <p>
          {data.future_rows} registro(s) com data posterior à posição consultada. Serão efetivados
          com a data original e não entram no saldo dessa posição.
        </p>
      )}
    </>
  )
}

export default function ImportConfirmation({
  ownerId,
  jobId,
  intent,
  onIntent,
  onExpired,
  onCompleted,
  onClose,
}) {
  const [snapshot, setSnapshot] = useState(null)
  const [receipt, setReceipt] = useState(null)
  const [acks, setAcks] = useState(emptyAcks)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [shown, setShown] = useState(50)
  const [consulted, setConsulted] = useState(null)
  const live = useRef(false),
    working = useRef(true),
    heading = useRef(null)
  const pending = intent?.ownerId === ownerId && intent.jobId === jobId ? intent : null
  useEffect(() => {
    let current = true
    live.current = true
    working.current = true
    heading.current?.focus()
    api
      .importConfirmation(ownerId, jobId)
      .then((result) => {
        if (!current) return
        setSnapshot(result)
        setConsulted(result.etag)
        setAcks(emptyAcks())
        setShown(50)
        if (result.data.receipt) {
          setReceipt(result.data.receipt)
          onIntent((previous) =>
            previous?.ownerId === ownerId && previous.jobId === jobId ? null : previous,
          )
          onCompleted()
        }
      })
      .catch((failure) => {
        if (!current) return
        if (failure.status === 401) onExpired()
        else
          setError(
            'Não foi possível consultar a confirmação. Consulte novamente antes de prosseguir; uma falha não significa que nada foi importado.',
          )
      })
      .finally(() => {
        if (current) {
          working.current = false
          setLoading(false)
        }
      })
    return () => {
      current = false
      live.current = false
    }
  }, [ownerId, jobId, onExpired, onIntent, onCompleted, refresh])
  function reload() {
    if (working.current) return
    working.current = true
    setLoading(true)
    setError('')
    setSnapshot(null)
    setConsulted(null)
    setAcks(emptyAcks())
    setRefresh((value) => value + 1)
  }
  async function persist(attempt) {
    if (working.current) return
    working.current = true
    setBusy(true)
    setError('')
    setConsulted(null)
    onIntent(attempt)
    try {
      const result = await api.confirmImport(
        ownerId,
        jobId,
        attempt.data,
        attempt.key,
        attempt.etag,
      )
      if (!live.current) return
      setReceipt(result)
      onIntent((previous) =>
        previous?.ownerId === ownerId && previous.key === attempt.key ? null : previous,
      )
      onCompleted()
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else {
        const rejected = [403, 404, 409, 412, 413, 422].includes(failure.status)
        onIntent((previous) =>
          previous?.ownerId === ownerId && previous.key === attempt.key
            ? { ...previous, rejected }
            : previous,
        )
        setError(
          failure.status === 412
            ? 'A seleção ou a posição financeira mudou. Consulte o resultado e revise a nova versão antes de confirmar.'
            : rejected
              ? 'A tentativa foi recusada. Consulte o resultado antes de revisar ou iniciar outra tentativa.'
              : 'Não foi possível confirmar o resultado. Consulte o recibo ou repita a mesma confirmação; não inicie outra intenção.',
        )
      }
    } finally {
      working.current = false
      if (live.current) setBusy(false)
    }
  }
  function submit(event) {
    event.preventDefault()
    if (
      working.current ||
      pending ||
      !snapshot?.data.eligible ||
      !Object.values(acks).every((value) => value === true)
    )
      return
    const attempt = Object.freeze({
      ownerId,
      jobId,
      key: crypto.randomUUID(),
      etag: snapshot.etag,
      data: Object.freeze({ ...acks }),
      rejected: false,
    })
    persist(attempt)
  }
  const data = snapshot?.data
  const warningItems = data?.duplicates?.items ?? []
  const warningsById = new Map(warningItems.map((item) => [item.row_id, item.reasons]))
  return (
    <section
      className="surface import-confirmation"
      aria-labelledby="import-confirmation-heading"
      aria-busy={loading || busy}
    >
      <h2 id="import-confirmation-heading" ref={heading} tabIndex={-1}>
        {receipt ? 'Recibo da importação' : 'Conferir e confirmar importação'}
      </h2>
      <p className="field-hint">
        Importar cria lançamentos efetivados e encerra esta prévia. Sair da tela não cancela uma
        requisição já enviada. Confira transferências e estornos manualmente antes de selecionar
        receitas e despesas.
      </p>
      {loading && <p role="status">Consultando confirmação…</p>}
      {busy && <p role="status">Enviando a confirmação…</p>}
      {error && (
        <p role="alert" className="notice notice-error">
          {error}
        </p>
      )}
      {receipt ? (
        <>
          <p role="status" className="notice notice-success">
            Importação concluída: {receipt.imported_rows} lançamento(s) criado(s).
          </p>
          <p>
            {receipt.not_imported_rows} registro(s) não importado(s), incluindo{' '}
            {receipt.invalid_rows} inválido(s). Esta prévia está encerrada.
          </p>
          <p>Recibo histórico da confirmação; consulte Saldos para uma posição atual.</p>
          <p>
            Confirmada em{' '}
            <time dateTime={receipt.completed_at}>
              {new Intl.DateTimeFormat('pt-BR', {
                dateStyle: 'short',
                timeStyle: 'medium',
                timeZone: 'America/Sao_Paulo',
              }).format(new Date(receipt.completed_at))}
            </time>{' '}
            (São Paulo).
          </p>
          <Amounts data={receipt} />
        </>
      ) : pending ? (
        <>
          <p className="notice notice-error">
            Há uma tentativa de confirmação para esta prévia. Consultar não cancela uma requisição
            em andamento. Repetir mantém a mesma solicitação e não cria outro lote.
          </p>
          <div className="account-actions">
            <Button type="button" disabled={loading || busy} onClick={reload}>
              Consultar resultado da confirmação
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={loading || busy || pending.rejected}
              onClick={() => persist(pending)}
            >
              Repetir mesma confirmação
            </Button>
            {pending.rejected && snapshot && consulted === snapshot.etag && (
              <Button
                type="button"
                variant="outline"
                disabled={loading || busy}
                onClick={() => {
                  onIntent((previous) =>
                    previous?.ownerId === ownerId && previous.key === pending.key ? null : previous,
                  )
                  setAcks(emptyAcks())
                  setError('')
                }}
              >
                Revisar nova versão
              </Button>
            )}
          </div>
        </>
      ) : (
        data && (
          <>
            <Amounts data={data} />
            <p>
              {data.selected_count} de {data.total_rows} registro(s) selecionado(s). Os demais não
              serão importados, incluindo {data.invalid_rows} inválido(s).
            </p>
            {data.issues.length > 0 && (
              <ul aria-label="Pendências da confirmação">
                {data.issues.map((issue) => (
                  <li key={issue}>
                    {issueText[issue] ?? 'Confira a situação desta prévia antes de confirmar.'}
                  </li>
                ))}
              </ul>
            )}
            {data.matching_files > 0 && (
              <p className="notice notice-error">
                Há outras prévias deste mesmo arquivo nesta conta. Confira se já representam a mesma
                intenção.
              </p>
            )}
            {data.duplicates?.overlapping_period && (
              <p className="notice notice-error">
                Há outra prévia com período sobreposto nesta conta.
              </p>
            )}
            {data.duplicates?.scan_limited && (
              <p role="status" className="notice notice-error">
                A busca de duplicatas é parcial porque atingiu o limite de candidatos. Pode haver
                outras coincidências.
              </p>
            )}
            <p className="field-hint">
              Os avisos são consultivos: compras iguais podem ser legítimas. Ausência de avisos não
              garante ausência de duplicatas.
            </p>
            <ol className="import-rows" aria-label="Registros selecionados para importar">
              {data.selected_rows.slice(0, shown).map((row) => (
                <li className="import-row" key={row.id}>
                  <h3>Registro {row.row_number}</h3>
                  <p>{row.description}</p>
                  <p>
                    {formatDate(row.transaction_date)} ·{' '}
                    {row.type === 'income' ? 'Receita' : 'Despesa'} · {formatMoney(row.amount)} ·{' '}
                    {row.category_name}
                  </p>
                  {row.external_id && <p>Referência: {row.external_id}</p>}
                  {warningsById.has(row.id) && (
                    <ul>
                      {warningsById.get(row.id).map((reason) => (
                        <li key={reason}>
                          {duplicateReasons[reason] ?? 'Confira esta coincidência no histórico.'}
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ol>
            {data.selected_rows.length > shown && (
              <Button
                type="button"
                variant="outline"
                onClick={() => setShown((value) => value + 50)}
              >
                Mostrar mais selecionados
              </Button>
            )}
            <form onSubmit={submit} aria-label="Confirmar seleção CSV">
              <fieldset disabled={loading || busy || !data.eligible}>
                <label className="import-selection">
                  <input
                    type="checkbox"
                    checked={acks.acknowledge_duplicates}
                    onChange={(event) =>
                      setAcks((previous) => ({
                        ...previous,
                        acknowledge_duplicates: event.target.checked,
                      }))
                    }
                  />
                  Revisei os avisos de duplicidade e os limites da busca.
                </label>
                <label className="import-selection">
                  <input
                    type="checkbox"
                    checked={acks.acknowledge_classification}
                    onChange={(event) =>
                      setAcks((previous) => ({
                        ...previous,
                        acknowledge_classification: event.target.checked,
                      }))
                    }
                  />
                  Revisei a classificação e tratei transferências e estornos manualmente.
                </label>
                <label className="import-selection">
                  <input
                    type="checkbox"
                    checked={acks.acknowledge_reservations}
                    onChange={(event) =>
                      setAcks((previous) => ({
                        ...previous,
                        acknowledge_reservations: event.target.checked,
                      }))
                    }
                  />
                  Entendi o impacto no saldo e nas reservas, que não serão liberadas
                  automaticamente.
                </label>
                <Button
                  type="submit"
                  disabled={!Object.values(acks).every((value) => value === true)}
                >
                  Confirmar importação de {data.selected_count} registros
                </Button>
              </fieldset>
            </form>
          </>
        )
      )}
      <div className="account-actions">
        {!pending && (
          <Button type="button" variant="outline" disabled={loading || busy} onClick={reload}>
            Atualizar resultado da importação
          </Button>
        )}
        <Button type="button" variant="outline" disabled={busy} onClick={onClose}>
          Voltar à prévia
        </Button>
      </div>
      <p className="field-hint">
        A tentativa fica apenas na memória durante a navegação. Recarregar o navegador perde esse
        estado: consulte o recibo antes de iniciar outra intenção. Sair da conta limpa a tentativa;
        não desfaz uma importação concluída.
      </p>
    </section>
  )
}
