# Referência local de desempenho do MVP

Medição em 17/11/2026 (São Paulo), com dados inteiramente fictícios. Os tempos
incluem HTTP real em loopback, autenticação e consultas PostgreSQL. Não incluem
TLS, internet, renderização do navegador ou usuários concorrentes. Esta é uma
referência de desenvolvimento, não um SLA de produção.

| Cenário | Amostras | Mediana | P95 | Máximo | Critério da referência |
| --- | ---: | ---: | ---: | ---: | --- |
| Listar uma conta autenticada | 50 | 48,155 ms | 75,824 ms | 82,168 ms | P95 ≤ 500 ms |
| Dashboard mensal com 10.000 lançamentos | 30 | 129,977 ms | 380,234 ms | 381,187 ms | P95 ≤ 2.000 ms |
| Analisar e guardar prévia de CSV com 5.000 linhas | 3 | 4.527,634 ms | 6.375,839 ms | 6.375,839 ms | Máximo ≤ 15.000 ms |

Os três critérios foram atendidos neste ambiente. Com apenas três amostras de
CSV, o critério usa o pior tempo observado; seu P95 coincide com o máximo e não
é uma estimativa robusta de cauda. Os dados brutos e a configuração estão em
[performance-reference.json](performance-reference.json).

## Ambiente e método

- Windows, Python 3.11.9, oito CPUs lógicas e cerca de 5,88 GiB de RAM no host.
- Docker Desktop com oito CPUs e cerca de 2,78 GiB de RAM disponíveis. O PostgreSQL
  18.6 descartável foi limitado a duas CPUs e 1 GiB; a API nativa não teve limite
  próprio de CPU. Versões exatas das bibliotecas e imagem estão no relatório.
- Migrações reais até `0017_import_confirmation`; cadastro/login/CSRF e
  autorização normais. Somente o limite de requisições autenticadas da instância
  descartável é elevado para 1.000/minuto, para medir processamento sem throttle.
  A configuração padrão do produto permanece em 60/minuto.
- Uma conta, 25 categorias e 10.000 lançamentos efetivados no mês anterior fechado.
  O preparo por SQL ocorre fora dos tempos. Receitas: 166.700,00; despesas:
  66.660,00; resultado: 100.040,00. O medidor confere esses totais, as contagens
  e a soma das 20 categorias detalhadas com as quatro categorias restantes.
- Três aquecimentos por cenário de leitura, além da primeira conferência do
  dashboard; requisições sequenciais e P95 por posto mais próximo, sem interpolar.
- Cada amostra CSV mede obtenção de CSRF, inspeção, criação da prévia mapeada e
  leitura do recibo. Confere 5.000 linhas válidas e zero linhas importadas.
  Não mede a confirmação financeira nem cliques de revisão; os 10.000
  lançamentos originais permanecem inalterados.

## Reproduzir

Com Docker local em modo Linux e dependências do backend instaladas, execute
na raiz do repositório:

```powershell
backend/.venv/Scripts/python.exe tools/benchmark_mvp.py
```

Em Linux, use `backend/.venv/bin/python`. O comando é manual e não integra a
suíte normal de testes. O script cria banco/API próprios, usa porta aleatória
restrita a loopback e credenciais temporárias em memória. Não lê `.env` pessoal,
não aceita URL de banco externo e não usa a demo. Ao terminar, encerra a API e
remove somente o container identificado como seu. O relatório fica em
`.cache/mvp-performance/<identificador>/report.json`, ignorado pelo Git.

O código medido é identificado por SHA-256 no relatório público. A execução
aprovada confirmou `api_stopped` e `container_removed`. Interrupção forçada do
processo pode impedir a limpeza; confira os recursos com o label
`finsight.validation=mvp-performance` antes de qualquer remoção manual.

Resultados variam com hardware, carga e volume. Uma implantação pública exige
medição própria com rede, TLS, concorrência e limites de infraestrutura reais.
