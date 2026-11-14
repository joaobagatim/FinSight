import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import ImportUpload from '@/components/ImportUpload'
import ImportPreview from '@/components/ImportPreview'
import { api } from '@/services/api'
import { importStatuses } from '@/lib/imports'

export default function ImportsPanel({ ownerId, intent, onIntent, onExpired }) {
  const [page, setPage] = useState({ items: [], has_more: false })
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [refresh, setRefresh] = useState(0)
  const live = useRef(false),
    fetching = useRef(true)
  useEffect(() => {
    let current = true
    live.current = true
    fetching.current = true
    api
      .imports(ownerId)
      .then((result) => {
        if (current) setPage(result)
      })
      .catch((failure) => {
        if (!current) return
        if (failure.status === 401) onExpired()
        else setError('Não foi possível listar as prévias. Tente atualizar o histórico.')
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
  }, [ownerId, onExpired, refresh])
  function reload() {
    if (fetching.current) return
    fetching.current = true
    setLoading(true)
    setError('')
    setRefresh((value) => value + 1)
  }
  async function more() {
    if (fetching.current) return
    fetching.current = true
    setLoading(true)
    setError('')
    try {
      const result = await api.imports(ownerId, page.items.length)
      if (live.current)
        setPage((previous) => ({ ...result, items: [...previous.items, ...result.items] }))
    } catch (failure) {
      if (!live.current) return
      if (failure.status === 401) onExpired()
      else setError('Não foi possível carregar mais prévias.')
    } finally {
      fetching.current = false
      if (live.current) setLoading(false)
    }
  }
  return (
    <div className="imports-panel">
      <div className="section-bar">
        <h2>Importações de CSV</h2>
        <Button type="button" variant="outline" disabled={loading} onClick={reload}>
          Atualizar histórico de prévias
        </Button>
      </div>
      <p className="field-hint">
        Analise seu arquivo, escolha as colunas e guarde uma prévia para conferência. Esta etapa não
        altera os saldos das contas.
      </p>
      {notice && (
        <p role="status" className="notice notice-success">
          {notice}
        </p>
      )}
      {intent && selected && (
        <Button type="button" onClick={() => setSelected(null)}>
          Retomar tentativa de prévia
        </Button>
      )}
      {selected ? (
        <ImportPreview
          key={selected}
          ownerId={ownerId}
          jobId={selected}
          onExpired={onExpired}
          onClose={() => setSelected(null)}
          onUpdated={(summary) =>
            setPage((previous) => ({
              ...previous,
              items: previous.items.map((item) => (item.id === summary.id ? summary : item)),
            }))
          }
        />
      ) : (
        <ImportUpload
          ownerId={ownerId}
          intent={intent}
          onIntent={onIntent}
          onExpired={onExpired}
          onSaved={(id) => {
            setSelected(id)
            setNotice('Prévia guardada. Nenhum lançamento foi criado.')
            setError('')
            setLoading(true)
            setRefresh((value) => value + 1)
          }}
        />
      )}
      <section aria-labelledby="import-history-heading" aria-busy={loading}>
        <h3 id="import-history-heading">Histórico de prévias</h3>
        {loading && <p role="status">Carregando histórico…</p>}
        {error && (
          <p role="alert" className="notice notice-error">
            {error}
          </p>
        )}
        {!loading && !error && page.items.length === 0 && <p>Nenhuma prévia guardada.</p>}
        <ul className="account-cards" aria-label="Prévias guardadas">
          {page.items.map((item) => (
            <li key={item.id} className="surface account-card">
              <h4>{item.filename}</h4>
              <p>
                {importStatuses[item.status] ?? 'Consultar situação'} · {item.total_rows} registros
                · {item.invalid_rows} inválidos · {item.imported_rows} lançamentos criados
              </p>
              {item.matching_files > 0 && <p>Há outras prévias deste mesmo arquivo nesta conta.</p>}
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setNotice('')
                  setSelected(item.id)
                }}
              >
                Consultar prévia
              </Button>
            </li>
          ))}
        </ul>
        {page.has_more && (
          <Button type="button" variant="outline" disabled={loading} onClick={more}>
            Carregar mais prévias
          </Button>
        )}
      </section>
    </div>
  )
}
