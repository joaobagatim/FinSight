import { Button } from '@/components/ui/button'

export default function TransactionFilters({
  value,
  onChange,
  onApply,
  onClear,
  references,
  onLoadReferences,
  disabled,
  dirty,
}) {
  const change = (field) => (event) => onChange({ ...value, [field]: event.target.value })
  return (
    <form
      className="surface transaction-filters"
      aria-label="Filtrar lançamentos"
      onSubmit={onApply}
    >
      <fieldset disabled={disabled}>
        <legend>Filtros e pesquisa</legend>
        <label className="field" htmlFor="history-search">
          Pesquisar na descrição
          <input
            id="history-search"
            type="search"
            maxLength={255}
            value={value.q}
            onChange={change('q')}
          />
        </label>
        <p className="field-hint">
          Busca por trecho, sem diferenciar maiúsculas e minúsculas. Acentos e sinais são
          considerados como escritos. Combine os campos para restringir o resultado.
        </p>
        <div className="transaction-filter-grid">
          <label className="field" htmlFor="history-account">
            Conta do histórico
            <select
              id="history-account"
              value={value.account_id}
              onChange={change('account_id')}
              disabled={references.loading}
            >
              <option value="">Todas as contas</option>
              {value.account_id &&
                !references.accounts.some((item) => item.id === value.account_id) && (
                  <option value={value.account_id}>
                    Conta selecionada fora das opções carregadas
                  </option>
                )}
              {references.accounts.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                  {!item.is_active && ' · Arquivada'}
                </option>
              ))}
            </select>
          </label>
          <label className="field" htmlFor="history-category">
            Categoria do histórico
            <select
              id="history-category"
              value={value.category_id}
              onChange={change('category_id')}
              disabled={references.loading}
            >
              <option value="">Todas as categorias</option>
              {value.category_id &&
                !references.categories.some((item) => item.id === value.category_id) && (
                  <option value={value.category_id}>
                    Categoria selecionada fora das opções carregadas
                  </option>
                )}
              {references.categories.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} · {item.type === 'income' ? 'Receita' : 'Despesa'}
                  {!item.is_active && ' · Desativada'}
                </option>
              ))}
            </select>
          </label>
          <label className="field" htmlFor="history-type">
            Tipo do movimento
            <select id="history-type" value={value.type} onChange={change('type')}>
              <option value="">Receitas e despesas</option>
              <option value="income">Receitas</option>
              <option value="expense">Despesas</option>
            </select>
          </label>
          <label className="field" htmlFor="history-status">
            Situação do movimento
            <select id="history-status" value={value.status} onChange={change('status')}>
              <option value="">Planejados e efetivados</option>
              <option value="planned">Planejados</option>
              <option value="posted">Efetivados</option>
            </select>
          </label>
          <label className="field" htmlFor="history-from">
            Data inicial (inclusive)
            <input
              id="history-from"
              type="date"
              value={value.date_from}
              onChange={change('date_from')}
            />
          </label>
          <label className="field" htmlFor="history-to">
            Data final (inclusive)
            <input id="history-to" type="date" value={value.date_to} onChange={change('date_to')} />
          </label>
        </div>
        {references.error && (
          <p className="field-hint">
            As opções de contas e categorias não puderam ser atualizadas. Você pode pesquisar por
            descrição ou tentar atualizar as opções.
          </p>
        )}
        <div className="account-actions">
          <Button type="submit">Aplicar filtros</Button>
          <Button type="button" variant="outline" onClick={onClear}>
            Limpar filtros
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={references.loading}
            onClick={() => onLoadReferences()}
          >
            Atualizar opções dos filtros
          </Button>
          {references.accountMore && (
            <Button
              type="button"
              variant="outline"
              disabled={references.loading}
              onClick={() => onLoadReferences('accounts')}
            >
              Mais contas nos filtros
            </Button>
          )}
          {references.categoryMore && (
            <Button
              type="button"
              variant="outline"
              disabled={references.loading}
              onClick={() => onLoadReferences('categories')}
            >
              Mais categorias nos filtros
            </Button>
          )}
        </div>
        {dirty && (
          <p role="status" className="field-hint">
            Filtros alterados. Aplique para consultar os resultados.
          </p>
        )}
      </fieldset>
    </form>
  )
}
