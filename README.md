# FinSight

FinSight é uma plataforma de gestão financeira pessoal desenvolvida com React, Python (FastAPI) e PostgreSQL. Permite controlar receitas e despesas, importar extratos bancários, visualizar dashboards interativos, analisar tendências financeiras e planejar metas com projeções inteligentes.

## Desenvolvimento

A infraestrutura da Fase 0 está implementada. A Fase 1 adiciona modelos e migrações
de usuários, sessões, contas, categorias, prévias de importação,
transações, transferências, metas e alocações, além do cadastro de usuários.
Há também primitivas de access JWT, serviço interno de sessões com rotação e
revogação por reutilização de refresh, além de helpers de cookies e CSRF.
O ciclo de autenticação HTTP usa cookies protegidos, CSRF e perfil próprio.
As funcionalidades financeiras descritas acima fazem parte do escopo planejado.

A API inicial oferece `GET /health`. Execute na raiz do repositório:

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install --require-hashes -r backend/requirements-dev.txt
backend/.venv/Scripts/python.exe -m uvicorn app.main:create_app --factory --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

## Frontend local

Requisitos: Node.js 24.x e npm 11.x. O frontend utiliza React com JavaScript/JSX
e Vite. Na raiz do repositório:

```powershell
npm --prefix frontend ci
npm --prefix frontend run dev
```

Abra `http://127.0.0.1:5173`. A porta é fixa: se estiver ocupada, o servidor
informa o conflito em vez de escolher outra porta. O acesso fica restrito à
interface local. Encerre o processo com `Ctrl+C`.

A página inicial apresenta o projeto e indica que as funcionalidades financeiras
ainda estão em desenvolvimento. Ela funciona independentemente da API e do banco;
não faz requisições financeiras nem usa dados reais. Não há autenticação nesta
unidade. Tailwind CSS e os componentes locais shadcn/ui formam a base visual.

Verificações e build:

```powershell
npm --prefix frontend run lint
npm --prefix frontend run format:check
npm --prefix frontend run build
npm --prefix frontend run preview
```

O build gera `frontend/dist`, ignorado pelo Git. O preview fica em
`http://127.0.0.1:4173` e serve para conferir o build local, não para hospedagem
de produção. Use `npm --prefix frontend run format` para aplicar a formatação.
O `package-lock.json` é versionado; use `npm ci` para reproduzir as dependências.
Nenhum segredo deve ser incluído no frontend: código e variáveis `VITE_*` são
públicos no navegador. Esta página ainda não exige variáveis de ambiente.

### Tailwind CSS e shadcn/ui

Tailwind CSS 4 utiliza o plugin `@tailwindcss/vite` e o import em
`frontend/src/index.css`; não exige um `tailwind.config.js` nesta configuração.
O mesmo CSS define os tokens de cor usados por utilitários e componentes.
A interface atual utiliza o tema claro do FinSight; não há troca de tema nesta unidade.

Os componentes shadcn/ui ficam no código-fonte em `frontend/src/components/ui/`.
`Button` compõe o link de navegação usando `asChild`, preservando a semântica de
âncora; `Badge` apresenta o estado de desenvolvimento. O helper `cn`, em
`frontend/src/lib/utils.js`, combina classes condicionais e resolve conflitos
entre utilitários Tailwind. O alias `@/` aponta para `frontend/src`, configurado
tanto no Vite quanto no `jsconfig.json`.

`frontend/components.json` mantém `tsx: false` e `rsc: false`, com componentes
JavaScript/JSX e estilo `new-york`. Para adicionar outro componente no futuro:

```powershell
Set-Location frontend
npx --yes shadcn@4.22.1 add nome-do-componente
```

Revise os arquivos e dependências gerados antes de incluí-los no Git. A CLI
fixada ainda consulta o registro remoto; o código já gerado é preservado no
repositório. Não é necessário executar a CLI durante `npm ci`, build ou uso da
aplicação. Consulte as instruções oficiais de
[Tailwind com Vite](https://tailwindcss.com/docs/installation/using-vite) e
[shadcn/ui em JavaScript](https://ui.shadcn.com/docs/javascript).

## Automação com Playwright e TypeScript

A suíte permanente da raiz utiliza Playwright Test com TypeScript, separado do
frontend JavaScript/JSX. Requisitos: Node 24.x, npm 11.x e o ambiente Python
`backend/.venv` com as dependências do backend instaladas conforme o início deste
README. Execute na raiz:

```powershell
npm ci
npm --prefix frontend ci
npx playwright install chromium
npm run typecheck
npm run lint
npm run format:check
npm test
```

O primeiro download do Chromium é feito para o cache de navegadores do usuário.
O projeto utiliza o Chromium distribuído pelo Playwright; a instalação de
Chrome/Edge no Windows não substitui esse passo.

O Playwright inicia o build/preview do frontend em `127.0.0.1:4175` e uma API
temporária em `127.0.0.1:8001`, encerrando os processos ao terminar. As portas
precisam estar livres: servidores existentes não são reutilizados. A suíte
verifica a página renderizada, teclado, navegação e layouts de 320/390/1280 px,
além dos contratos HTTP de saúde, prontidão, OpenAPI e resposta 404.

A API de testes utiliza a fábrica real com settings isolados: não lê o `.env`,
remove variáveis `FINSIGHT_*` somente do processo filho e não abre conexão com
PostgreSQL. Por isso, `/health` retorna 200 e `/health/ready` retorna 503 nesta
suíte. Esses resultados não indicam falha do banco de desenvolvimento. Os testes
reais de banco continuam no Pytest com a opção explícita `--run-postgres`.

Comandos específicos:

```powershell
npm run test:api
npm run test:e2e
npm run test:report
```

Os comandos por projeto também inicializam os dois servidores configurados.
`test:report` abre o último relatório HTML. Resultados JSON ficam em
`test-results/results.json` e HTML em `playwright-report/`; ambos ignorados pelo
Git. Screenshots e traces são retidos somente em falhas. Não utilize dados reais
nesses testes ou publique os artefatos sem revisar seu conteúdo.

`npm run typecheck` executa a verificação TypeScript separadamente, pois o
Playwright transforma os arquivos para execução sem fazer essa verificação.
Use `npm run format` para formatar os arquivos de automação. O lint/formato da
raiz cobre apenas essa infraestrutura; o frontend mantém seus próprios comandos
com `npm --prefix frontend run ...`. Referências: [webServer](https://playwright.dev/docs/test-webserver)
e [TypeScript](https://playwright.dev/docs/test-typescript) do Playwright.

## Integração contínua com GitHub Actions

O workflow `.github/workflows/ci.yml` executa em PRs destinados à `main`, pushes
na `main` e acionamento manual pela aba **Actions**. São três jobs independentes
em Ubuntu 24.04, com Node 24/npm 11.11.0 e Python 3.11 conforme necessário:

| Check | Verificações |
|---|---|
| Backend checks | Instalação com hashes, Ruff, formatação e Pytest com PostgreSQL |
| Frontend checks | Instalação pelo lockfile, ESLint, formatação e build |
| Playwright checks | Tipos/lint/formato, build/preview, API isolada e testes Chromium |

O job de backend cria um serviço PostgreSQL 18.6 descartável no runner, com
credencial sintética exclusiva de CI e porta 5433. A fixture cria/remove somente
seu banco temporário próprio. Nenhum acesso ao PostgreSQL do seu Windows ou ao
seu `.env` local é necessário; esses dados não são enviados para o GitHub.

O job Playwright utiliza a API sem banco configurado, conforme descrito acima.
Ele instala o Chromium do Playwright e suas dependências de sistema no runner.
O workflow utiliza permissões de leitura, actions fixadas por SHA e cache de
downloads baseado nos lockfiles. Novas execuções cancelam as anteriores da mesma
branch ou PR. Não há deploy ou merge automático configurado.

Após publicar o workflow e abrir o PR, acompanhe cada check no próprio PR ou na
aba **Actions**. Abra um job para consultar a etapa que falhou. Relatórios Pytest
e Playwright são retidos como artefatos por sete dias quando disponíveis; dados
usados nos testes devem continuar fictícios.

O status dos checks auxilia a revisão. Exigir aprovação dos checks antes do
merge depende de uma regra de proteção da `main`, configurada separadamente.
O arquivo do workflow e as validações locais não comprovam uma execução remota:
o resultado real só pode ser confirmado após uma execução no GitHub.
Referências: [GitHub Actions](https://docs.github.com/en/actions/get-started/understand-github-actions)
e [CI do Playwright](https://playwright.dev/docs/ci-intro).

## PostgreSQL local e DBeaver

O banco de desenvolvimento roda pelo Docker Compose. Requisitos: Docker Desktop
em execução com contêineres Linux; o servidor PostgreSQL não precisa ser instalado
no Windows. A imagem está fixada em PostgreSQL 18.6 com digest para reprodução.

Na raiz do repositório, copie o exemplo somente se ainda não houver `.env`:

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
```

No `.env` local, substitua `FINSIGHT_DB_PASSWORD` por uma senha longa e aleatória,
exclusiva para desenvolvimento. O arquivo real é ignorado; não publique sua senha.
As credenciais de inicialização devem ser definidas antes da primeira subida.

```powershell
docker compose --env-file .env config --quiet
docker compose --env-file .env up -d --wait postgres
docker compose ps postgres
```

No DBeaver Community, crie uma conexão do tipo **PostgreSQL** com:

| Campo | Valor padrão |
|---|---|
| Host | `localhost` |
| Porta | `5433` |
| Database | `finsight` |
| Usuário | `finsight` |
| Senha | Valor de `FINSIGHT_DB_PASSWORD` no seu `.env` local |

Se necessário, permita que o DBeaver baixe o driver PostgreSQL. Clique em **Testar
conexão** e execute `SELECT 1;`. Em caso de preferência IPv6 para `localhost`, use
`127.0.0.1`: a publicação está restrita ao loopback IPv4. A porta do contêiner é
5432; a porta do Windows é 5433, evitando conflito com serviços existentes.

Se alterar `FINSIGHT_DB_PORT`, use a mesma porta no DBeaver. Variáveis já definidas
no terminal podem prevalecer sobre o `.env`. O host em `.env` é reservado à futura
conexão do backend executado no Windows; entre contêineres, o endereço é
`postgres:5432`.

Para parar e iniciar o mesmo serviço:

```powershell
docker compose stop postgres
docker compose --env-file .env up -d --wait postgres
```

O volume nomeado `finsight_postgres_data` mantém os dados ao parar ou recriar o
contêiner. As variáveis de inicialização não alteram usuários/senhas de um volume
já inicializado. Alterar a senha exige uma operação SQL explícita; não remova o
volume para corrigir credenciais. O usuário configurado pela imagem oficial é o
administrador desse banco local; produção exigirá papéis e permissões próprios.

## Conexão da API e prontidão do banco

Após instalar as dependências atualizadas e iniciar o PostgreSQL, a API lê os
parâmetros `FINSIGHT_DB_*` do `.env` da raiz. Não é necessário montar uma URL com
senha manualmente. SQLAlchemy e psycopg abrem conexões sob demanda; o pool é
encerrado ao desligar a aplicação. Não são criadas tabelas automaticamente.

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/health
Invoke-RestMethod -Uri http://127.0.0.1:8000/health/ready
```

| Endpoint | Resultado |
|---|---|
| `GET /health` | HTTP 200 e `{"status":"ok"}`; disponibilidade da API |
| `GET /health/ready` | HTTP 200 e `{"status":"ok","database":"ok"}` quando `SELECT 1` passa |
| `GET /health/ready` | HTTP 503 e `{"status":"unavailable","database":"unavailable"}` se o banco não responder ou a senha não estiver configurada |

A ausência de senha mantém o processo disponível, mas sem prontidão do banco.
Senha vazia/placeholder e parâmetros inválidos são rejeitados na configuração.
Respostas e logs da prontidão não incluem detalhes da exceção ou credenciais.
Esse endpoint é público, executa somente uma consulta simples e não deve ser
usado como autorização de recursos financeiros. Credenciais/TLS de produção
continuam exigindo configuração específica para o ambiente.

Os limites padrão são 3 segundos para conexão e espera do pool, e 3000 ms para
comandos SQL, configuráveis pelas variáveis de timeout do `.env.example`. O pool
é limitado a cinco conexões mantidas e cinco adicionais por processo. Conexões
retiradas do pool são verificadas antes do uso, e sessões usam fuso UTC.

## Testes do backend

Na raiz do repositório, execute:

```powershell
backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests
backend/.venv/Scripts/python.exe -m ruff check backend
backend/.venv/Scripts/python.exe -m ruff format --check backend
```

Os testes reais de PostgreSQL são opcionais no comando acima e aparecem como
ignorados. Para executá-los, mantenha o banco Docker ativo e o `.env` local
configurado; acrescente `--run-postgres`:

```powershell
backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests --run-postgres
```

Essa opção cria e remove somente um banco temporário próprio com nome aleatório
`finsight_test_*`. Exige permissão de criação de banco, usa somente dados sintéticos
e recusa ambiente de produção, host remoto ou porta 5432. Não altera as tabelas do
banco de desenvolvimento. O nome desse banco temporário não deve ser configurado
manualmente. Os testes verificam conexão, readiness, credenciais inválidas, liberação
de conexões, timeouts da sessão e o ciclo de migrações Alembic em banco isolado.

Se o Pytest encontrar erro de permissão no temporário padrão do Windows, use uma
pasta de testes exclusiva dentro do projeto, que já está ignorada:

```powershell
$taskPytestTemp = Join-Path (Get-Location).Path 'backend/.cache/pytest-temp'
New-Item -ItemType Directory -Path $taskPytestTemp -Force | Out-Null
$env:PYTEST_DEBUG_TEMPROOT = $taskPytestTemp
```

Depois repita o comando Pytest desejado nesse terminal. A variável vale somente
para o terminal atual; o Pytest gerencia seus subdiretórios numerados de teste.

## Migrações Alembic

O Alembic utiliza as mesmas variáveis `FINSIGHT_DB_*` da API e lê o `.env` da
raiz. Não coloque senha ou URL de conexão em `alembic.ini`. Instale as dependências
atualizadas e mantenha o PostgreSQL ativo antes de executar os comandos online.
Na raiz do repositório:

```powershell
backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini heads
backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini current
backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini upgrade head
backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini current
backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini check
```

`upgrade head` modifica o banco indicado pela configuração local. A revisão
`0001_phase0` é uma base vazia; `0002_identity` cria `users` e `user_sessions`;
`0003_accounts_categories` acrescenta `accounts` e `categories`;
`0004_imports` cria `import_jobs` e `import_rows`;
`0005_transactions_transfers` cria `transactions`/`transfers` e acrescenta
a chave composta de proprietário/id/tipo em categorias;
`0006_goals_allocations` cria `financial_goals` e `goal_allocations`;
`0007_refresh_token_history` acrescenta a tabela técnica `refresh_token_history`;
`0008_account_creation_requests` acrescenta `account_creation_requests` para
persistir futuras tentativas de criação de contas por usuário/chave.
O controle técnico `alembic_version` acompanha as revisões. As dez tabelas de
domínio estão modeladas; autenticação HTTP e cadastro/consulta de contas próprias
estão disponíveis. Os demais recursos financeiros ainda serão implementados.
Repetir o upgrade mantém a mesma revisão. A aplicação
não executa migrações automaticamente ao iniciar. `check` compara o banco com
`Base.metadata`, com identidade, contas, categorias, importações, transações,
transferências, metas, alocações, histórico de refresh e chaves de criação de contas;
tabelas manuais podem ser
identificadas como divergências.
Revise qualquer migração gerada antes de aplicá-la.

Para visualizar o SQL sem abrir conexão ou ler credenciais:

```powershell
backend/.venv/Scripts/python.exe -m alembic -c backend/alembic.ini upgrade head --sql
```

Depois de aplicar a revisão, consulte no DBeaver, na conexão PostgreSQL correta:

```sql
SELECT current_database();
SELECT version_num FROM public.alembic_version;
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
ORDER BY table_name;
```

Resultado esperado após `upgrade head`: nome do banco configurado, uma linha
`0008_account_creation_requests` e as treze tabelas `alembic_version`, `users`,
`user_sessions`, `accounts`, `categories`, `import_jobs`, `import_rows`,
`transactions`, `transfers`, `financial_goals`, `goal_allocations` e
`refresh_token_history` e `account_creation_requests`.
Antes do primeiro upgrade, essas tabelas ainda não existem. As consultas acima
são somente de leitura. A migração não cria usuários nem sessões automaticamente.

O rollback de teste `downgrade 0007_refresh_token_history` remove somente as
chaves de criação de contas, preservando contas e demais tabelas. Isso perde a
memória de idempotência e permite duplicar uma criação repetida após o downgrade;
não execute em ambiente com tráfego sem revisão e autorização específica.
`downgrade 0006_goals_allocations` remove também o histórico
de hashes consumidos. Isso elimina informação necessária à detecção de
reutilização; em um ambiente com sessões reais, é necessário analisar e revogar
sessões antes de remover esse histórico, com autorização específica.
`downgrade 0005_transactions_transfers` remove também metas/alocações,
preservando as tabelas anteriores. `downgrade 0004_imports` remove também transações/transferências e a
chave técnica de categoria/tipo acrescentada nesta revisão, preservando os dados
das tabelas anteriores. `downgrade 0003_accounts_categories` remove também jobs/linhas,
preservando identidade, contas e categorias. `downgrade 0002_identity` remove também contas/categorias, preservando
usuários e sessões. `downgrade 0001_phase0` também remove identidade e seus registros.
`downgrade base` remove ainda a linha de versão, mantendo a
tabela técnica vazia. Não execute rollback em bancos com dados sem revisão e
autorização específica; estes comandos são exercitados apenas no banco de teste.
Os testes `--run-postgres` validam upgrade, downgrade e detecção de divergência
somente em seu banco temporário próprio, preservando o banco de desenvolvimento.

Para alterar o esquema no futuro, registre os models em `app.models`, gere uma
revisão com `revision --autogenerate -m "describe schema change"`, revise o arquivo
em `backend/alembic/versions/` e só então aplique `upgrade head`. O Alembic importa
os modelos explicitamente; iniciar a API não cria tabelas nem executa migrações.
Consulte o [tutorial oficial do Alembic](https://alembic.sqlalchemy.org/en/latest/tutorial.html).

### Persistência inicial de identidade

Os modelos SQLAlchemy `User` e `UserSession` usam UUID v4 gerado pela aplicação,
e timestamps PostgreSQL com fuso. A sessão do banco usa UTC. `updated_at` é
atualizado pelas operações SQLAlchemy; não há trigger para atualizações SQL manuais.
O ORM normaliza e-mail com remoção de espaços nas extremidades e minúsculas;
o banco exige essa forma normalizada e unicidade, inclusive em escritas diretas.
Validação completa de e-mail e hashing Argon2id são realizados pelo cadastro abaixo.

As sessões referenciam um usuário, exigem hash de refresh único e expiração
posterior à criação. Revogação e último uso são opcionais e não podem anteceder
a criação. Os campos armazenam hashes; o serviço interno descrito ao final
gera e renova tokens. O schema não verifica criptograficamente um hash.
A exclusão de um usuário com sessões é recusada pelo banco, sem cascade automático.

Para inspecionar a estrutura no DBeaver sem consultar hashes ou dados pessoais:

```sql
SELECT table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name IN ('users', 'user_sessions')
ORDER BY table_name, ordinal_position;

SELECT table_name, constraint_name, constraint_type
FROM information_schema.table_constraints
WHERE table_schema = 'public' AND table_name IN ('users', 'user_sessions')
ORDER BY table_name, constraint_name;
```

Espera-se ver as colunas de identidade/sessão, datas com fuso, chaves primárias,
unicidade e a FK da sessão para o usuário. Nenhuma destas consultas modifica dados.

### Persistência de contas e categorias

`Account` armazena o proprietário, nome, tipo (`checking`, `savings`, `cash`,
`investment`), moeda BRL, saldo/data de abertura e estado ativo. O saldo inicial
aceita negativos e utiliza `NUMERIC(15,2)`/`Decimal`; não há coluna de saldo atual.
O ORM exige `Decimal` finito, dentro do limite de 13 dígitos inteiros e dois
decimais, rejeitando `float` e valores com frações menores que um centavo.
Escritas SQL diretas obedecem à coerção/arredondamento nativos de `NUMERIC(15,2)`;
as constraints também recusam valores não finitos. Veja os
[tipos numéricos do PostgreSQL](https://www.postgresql.org/docs/18/datatype-numeric.html).

`opening_date` persiste uma referência de data. O cálculo de saldo e a regra
temporal de abertura/lançamentos serão definidos na etapa dos serviços financeiros.
Esta entrega não resolve a pendência da especificação sobre início/fim do dia.

`Category` tem proprietário, nome, tipo (`income`/`expense`), cor hexadecimal
opcional no formato `#RRGGBB`, ícone opcional e estado ativo. O nome de exibição
é preservado com remoção de espaços nas extremidades pelo ORM. A unicidade no
banco usa `(user_id, type, lower(btrim(name)))`: ignora caixa/espaços externos na
comparação, preserva acentos e inclui categorias arquivadas. Outro usuário ou
outro tipo pode usar o mesmo nome. Não há categorias globais compartilhadas.

Ambas usam UUIDv4, timestamps com fuso/UTC e FK para usuário com exclusão restrita.
`UNIQUE(user_id, id)` prepara FKs compostas das próximas tabelas para impedir
referências entre proprietários diferentes. Essas garantias não substituem a
autorização HTTP que será implementada posteriormente. `is_active` permite
arquivamento; nenhuma rota de CRUD é adicionada nesta unidade.

Após aplicar a migração em ambiente autorizado, estas consultas DBeaver são
somente de leitura e não selecionam valores financeiros ou hashes:

```sql
SELECT table_name, column_name, data_type, numeric_precision, numeric_scale, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name IN ('accounts', 'categories')
ORDER BY table_name, ordinal_position;

SELECT table_name, constraint_name, constraint_type
FROM information_schema.table_constraints
WHERE table_schema = 'public' AND table_name IN ('accounts', 'categories')
ORDER BY table_name, constraint_name;

SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public' AND tablename IN ('accounts', 'categories')
ORDER BY tablename, indexname;
```

Espera-se `opening_balance` como numeric com precisão 15/escala 2, `opening_date`
como date, chaves de proprietário, checks de tipos/moeda e índice único funcional
das categorias. A aplicação não executa esta migração automaticamente.

### Persistência de prévias de importação

`ImportJob` registra usuário, conta de destino, nome-base sanitizado, tipo CSV,
checksum SHA-256, status, contadores e datas com fuso/UTC. A conta deve pertencer
ao usuário. Os contadores exigem `0 <= imported_rows <= total_rows`; uma data de
conclusão informada não pode anteceder a criação. Checksum não é único: arquivos
repetidos exigirão revisão e regras de idempotência no serviço de importação.

`ImportRow` guarda uma prévia com número de origem positivo e único por job.
Data, descrição, valor, tipo e categoria são opcionais para representar linhas
inválidas. O valor absoluto usa `NUMERIC(15,2)` e `Decimal` finito, não negativo,
exato em centavos no ORM; zero pode existir na prévia. SQL direto segue o
arredondamento nativo do PostgreSQL. Uma transação confirmada terá validações
próprias, incluindo valor positivo. Fingerprints SHA-256 não são únicos.

As chaves técnicas `user_id` e `account_id` da linha são derivadas do job.
FKs compostas impedem misturar proprietário, conta e job, e exigem categoria
sugerida do mesmo usuário. Uma chave única composta prepara o vínculo futuro
com transações da mesma conta e proprietário. Os relacionamentos ORM escrevem
somente as chaves pertinentes; atribuir uma categoria ou conta não troca o
proprietário implicitamente. Veja a documentação do SQLAlchemy sobre
[chaves estrangeiras sobrepostas](https://docs.sqlalchemy.org/en/21/orm/join_conditions.html#overlapping-foreign-keys).
Exclusões de recursos referenciados são restritas, sem cascade destrutivo.

Esta etapa fornece somente persistência. Upload, parser CSV, transições de status,
sanitização de conteúdo/erros, revisão, confirmação e deduplicação serão serviços
posteriores. As constraints não implementam autorização HTTP. Nenhum arquivo
bancário é armazenado ou processado por esta entrega.

Após aplicar a migration em ambiente autorizado, é possível inspecionar apenas
a estrutura no DBeaver:

```sql
SELECT table_name, column_name, data_type, numeric_precision, numeric_scale, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name IN ('import_jobs', 'import_rows')
ORDER BY table_name, ordinal_position;

SELECT table_name, constraint_name, constraint_type
FROM information_schema.table_constraints
WHERE table_schema = 'public' AND table_name IN ('import_jobs', 'import_rows')
ORDER BY table_name, constraint_name;

SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public' AND tablename IN ('import_jobs', 'import_rows')
ORDER BY tablename, indexname;
```

### Persistência de transações e transferências

`Transaction` representa uma receita ou despesa com proprietário, conta, categoria,
descrição obrigatória, valor, tipo `income`/`expense`, estado `planned`/`posted`,
data econômica e observações opcionais. Tipo e estado devem ser informados
explicitamente. `Transfer` representa um movimento entre duas contas próprias e
diferentes, com valor, estado explícito, data e descrição opcional. Uma transferência
persiste em uma única linha; não cria receitas/despesas automaticamente.

Os valores usam `NUMERIC(15,2)`/`Decimal` finito, estritamente positivo e exato em
centavos no ORM. Zero, negativos, `float`, valores fora da faixa e frações menores
que um centavo são rejeitados. SQL direto segue coerção/arredondamento nativos do
PostgreSQL. Ambas as entidades usam UUIDv4 e timestamps com fuso/UTC; `updated_at`
é atualizado por operações SQLAlchemy, sem trigger de atualização para SQL manual.

FKs compostas exigem contas e categorias do mesmo proprietário. A nova chave
`UNIQUE(user_id, id, type)` em categorias permite exigir também que o tipo da
categoria corresponda ao da transação. Uma categoria referenciada não pode ter
seu tipo alterado de forma a invalidar transações existentes; o índice único de
nomes normalizados permanece independente e inalterado.

O vínculo opcional com uma linha importada exige mesmo usuário e conta. Um índice
único parcial em `import_row_id` não nulo permite no máximo uma transação por
linha; várias transações manuais podem manter esse campo nulo. Isso não confirma
um job nem implementa idempotência completa ou validação do estado da prévia.
Relacionamentos ORM escrevem apenas suas referências, preservando proprietário,
tipo e conta explícitos ao atribuir categoria ou linha importada. Referências têm
exclusão restrita, sem cascade destrutivo.

Esta entrega prepara o schema da Fase1. Cálculos de saldo, CRUD, autenticação,
autorização HTTP e fluxos de importação serão implementados nas etapas seguintes.
`effective_date` é uma data obrigatória; a regra temporal em relação a
`opening_date` será aplicada nos serviços após a definição da convenção de
abertura. Atualmente o schema não compara essas datas. Os estados persistidos
não executam cálculos nem mutações de saldo.

Depois de aplicar a migration em ambiente autorizado, estas consultas DBeaver
inspecionam somente a estrutura:

```sql
SELECT table_name, column_name, data_type, numeric_precision, numeric_scale, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name IN ('transactions', 'transfers')
ORDER BY table_name, ordinal_position;

SELECT table_name, constraint_name, constraint_type
FROM information_schema.table_constraints
WHERE table_schema = 'public' AND table_name IN ('transactions', 'transfers', 'categories')
ORDER BY table_name, constraint_name;

SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public' AND tablename IN ('transactions', 'transfers')
ORDER BY tablename, indexname;
```

### Persistência de metas e alocações

`FinancialGoal` guarda proprietário, nome obrigatório, descrição opcional,
valor-alvo positivo em `NUMERIC(15,2)`/`Decimal`, prazo opcional e estado explícito
(`active`, `completed`, `cancelled`). Nomes de metas podem se repetir. O prazo é
uma data e pode representar uma referência passada. A meta usa UUIDv4 e timestamps
UTC; `updated_at` é atualizado pelo ORM, sem trigger para SQL manual.

`GoalAllocation` guarda um movimento de reserva (valor positivo) ou retirada
(valor negativo), com proprietário, meta, conta, data, notas opcionais e criação
UTC. O valor exige `Decimal` finito, diferente de zero, dentro da faixa de
`NUMERIC(15,2)` e exato em centavos no ORM. `float`, zero, não finitos e frações
menores que um centavo são rejeitados. SQL direto mantém coerção/arredondamento
nativos do PostgreSQL. O validador positivo das transações/transferências é preservado.

FKs compostas exigem meta e conta do mesmo proprietário. Atribuir uma meta ou conta
pelo ORM escreve somente a referência, preservando o proprietário explicitamente
informado. Exclusões de entidades referenciadas são restritas, sem cascade
destrutivo. Persistir alocação não cria receita/despesa/transferência, não altera
saldo de abertura e não muda automaticamente o estado da meta.

Esta etapa completa os modelos das dez tabelas de domínio, preparando os serviços
de metas da Fase3. Autenticação HTTP está disponível; autorização financeira, CRUD,
progresso, saldo livre e operações de reserva/retirada não estão disponíveis.
As constraints por linha não garantem soma reservada não negativa ou dentro do
saldo disponível: essas regras exigirão serviço transacional e testes de
concorrência. Bloquear/alertar gastos do dinheiro reservado, progresso acima de
100% e políticas de correção/exclusão dependem de decisões posteriores. Nenhum
bloqueio de despesa ou trigger de total foi implementado. A tabela de movimentos
também não representa auditoria ou imutabilidade prontas.

Após aplicar a migration em ambiente autorizado, consulte apenas a estrutura no DBeaver:

```sql
SELECT table_name, column_name, data_type, numeric_precision, numeric_scale, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name IN ('financial_goals', 'goal_allocations')
ORDER BY table_name, ordinal_position;

SELECT table_name, constraint_name, constraint_type
FROM information_schema.table_constraints
WHERE table_schema = 'public' AND table_name IN ('financial_goals', 'goal_allocations')
ORDER BY table_name, constraint_name;

SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public' AND tablename IN ('financial_goals', 'goal_allocations')
ORDER BY tablename, indexname;
```

## Cadastro de usuários

`POST /api/v1/auth/register` recebe somente JSON com `name`, `email` e `password`.
Nome: string de 1 a 120 caracteres após remover espaços externos. E-mail: endereço
válido, normalizado em minúsculas, até 255 caracteres; não há verificação por e-mail
ou consulta DNS. Senha: 15 a 128 caracteres Unicode válidos, incluindo espaços,
sem truncamento, normalização ou exigência de classes de caracteres; apenas
espaços não são aceitos. Campos extras e tipos incompatíveis são rejeitados.

A senha é armazenada como Argon2id com salt aleatório por hash e parâmetros
`m=19456 KiB, t=2, p=1`. O endpoint usa uma sessão SQLAlchemy por requisição e
`INSERT`/commit; a constraint única de e-mail resolve duplicatas e concorrência.
O cadastro não cria categorias, contas, sessões ou tokens.

Para criação válida e e-mail já cadastrado, a resposta é sempre **HTTP 200**:

```json
{"message":"Solicitação processada. Tente entrar com os dados informados."}
```

Uma duplicata não altera nome, senha ou estado do usuário existente. A resposta
não permite distinguir essas situações por status ou corpo e não confirma que
um login terá sucesso. Não há garantia de tempos de resposta idênticos.
Serviços e endpoints de sessão estão descritos ao final. A interface de cadastro
e demais telas de autenticação permanecem para etapas futuras.

| Status | Situação |
| --- | --- |
| 200 | Solicitação válida processada, inclusive e-mail existente |
| 422 | Dados inválidos ou JSON malformado; erro sanitizado sem ecoar entradas |
| 413 | Corpo acima do limite, inclusive em partes e sem Content-Length confiável |
| 415 | Content-Type diferente de application/json |
| 429 | Limite por cliente ou de hashes simultâneos; inclui Retry-After |
| 503 | Banco não configurado/indisponível ou falha de persistência |

As respostas POST do cadastro usam `Cache-Control: no-store`, sem `Set-Cookie`,
tokens, UUID ou hash. Erros não retornam SQL, detalhes do driver, senhas ou campos
extras fornecidos pelo cliente. CORS permite GET/POST apenas nas origens
configuradas, sem credenciais; CORS não substitui autenticação/autorização.

Os limites padrão, configuráveis no `.env.example`, são 16 KiB de corpo,
cinco requisições por minuto/endereço de cliente, até 4096 clientes no registro
temporário e dois hashes simultâneos. Não há fila de hashing: excesso recebe 429.
O aplicativo usa o endereço recebido do servidor ASGI e não interpreta
`X-Forwarded-For` diretamente. Proxies confiáveis devem ser configurados no servidor.

Esses limites estão na memória de **cada processo**. Antes de produção com
múltiplos workers/instâncias, configurar limite compartilhado ou na borda,
HTTPS e proxies confiáveis. Não há limitador distribuído nesta entrega.

Para testar uma criação, configure o banco e aplique as migrações em um ambiente
autorizado conforme as instruções anteriores. Nunca envie senhas reais como
exemplos ou as registre no terminal/log. Os testes automatizados usam somente
identidades fictícias e PostgreSQL descartável; não consultam o banco pessoal.
Pytest cobre criação, duplicatas e concorrência com PostgreSQL; Playwright
valida contrato/privacidade/OpenAPI e 503 em servidor isolado sem banco.

## Primitivas internas de access JWT

`AccessTokenService`, em `backend/app/core/tokens.py`, emite e verifica access
tokens para uso do serviço interno de sessões. O módulo JWT não consulta o
banco ou define cookies; os endpoints entregam credenciais apenas em cookies. O cadastro
mantém seu contrato.

A assinatura usa PyJWT com **HS256 fixo** e chave de 32 bytes aleatórios. Configure
`FINSIGHT_JWT_SIGNING_KEY` com a representação hexadecimal de 64 caracteres dessa
chave, mantendo o valor somente na configuração privada. O `.env.example` contém
uma instrução comentada e um placeholder não utilizável. O formato validado não
comprova aleatoriedade: a chave deve ser gerada por um gerador criptográfico.
Nenhuma chave padrão é utilizada ou gerada automaticamente pela aplicação.

Sem chave configurada, a API, health e cadastro continuam disponíveis;
instanciar o serviço JWT gera `TokenConfigurationError` com mensagem estática.
Uma chave explicitamente inválida impede carregar Settings, sem ecoar seu valor
no diagnóstico textual. A chave é `SecretStr`, excluída de repr e exportações de
Settings. Nunca registrar configuração sensível ou serializar erros de validação
com seus dados de entrada. Nenhuma chave real precisa ser criada para os testes.

| Variável | Padrão e validação |
| --- | --- |
| `FINSIGHT_JWT_SIGNING_KEY` | Ausente; quando definida, exatamente 64 caracteres hexadecimais |
| `FINSIGHT_JWT_ISSUER` | `finsight-api`, string não vazia até 120 caracteres após trim |
| `FINSIGHT_JWT_AUDIENCE` | `finsight-web`, string não vazia até 120 caracteres após trim |
| `FINSIGHT_JWT_ACCESS_TTL_SECONDS` | 900 segundos; intervalo permitido de 60 a 900 |

`issue(user_id, session_id)` aceita objetos UUIDv4 internos e retorna `SecretStr`.
O token contém somente `sub`, `sid`, `iss`, `aud`, `iat`, `nbf`, `exp`, `jti` e
`token_use=access`, com `typ=finsight-access+jwt`. O `jti` é um novo UUIDv4 a cada
emissão. Não há nome, e-mail, senha, hash ou dados financeiros no payload.
JWT é assinado e legível; não fornece criptografia do conteúdo.
O JSON usa UTF-8 para manter identificadores Unicode válidos, inclusive no limite
de tamanho configurado, dentro do limite de bytes aceito pelo verificador.

`verify(token)` aceita até 4096 bytes ASCII, fixa o algoritmo permitido e confere
assinatura, issuer, audience única, cabeçalho, propósito, campos obrigatórios e
tipos. UUIDs devem ser v4 em formato canônico; datas são inteiros em UTC, sem
aceitar strings/booleanos como timestamps. Exige `nbf=iat`, duração positiva dentro
do TTL, emissão já válida e expiração futura, sem tolerância adicional de relógio.
Cabeçalhos ou claims extras são recusados. A verificação não busca chaves remotas.

O resultado é `AccessTokenClaims`, com identificadores e datas tipados. Tokens
inválidos produzem `InvalidAccessToken` uniforme, sem retornar token, claims ou
detalhes da biblioteca no erro. Não há tokens retornados pela API nesta etapa.

Uma assinatura válida não comprova usuário ativo, sessão não revogada ou acesso
a um recurso. O serviço interno descrito abaixo consulta usuário/sessão; a
dependência HTTP `get_current_user` utiliza essa verificação. A autorização de
cada recurso financeiro ainda será integrada. Cookies/CSRF e refresh possuem helpers próprios; a rotação
operacional de chaves ainda não foi implementada. Alterar a chave
de assinatura invalida a verificação dos tokens emitidos com a chave anterior.

Os testes usam chaves e identidades sintéticas, relógio controlado e assinaturas
reais. Cobrem adulteração, algoritmos indevidos, claims ausentes/malformadas,
expiração, configuração e privacidade, além das regressões existentes.

## Histórico técnico de refresh tokens

A revisão `0007_refresh_token_history` cria uma tabela vazia para guardar digests
de refresh tokens consumidos. As dez tabelas de domínio e seus dados são
preservados. A aplicação não executa migrações automaticamente.

| Campo | Regra |
| --- | --- |
| `id` | UUIDv4 gerado pela aplicação |
| `session_id` | FK obrigatória para `user_sessions.id`, com exclusão RESTRICT e índice |
| `token_hash` | Digest SHA-256 em 64 caracteres hexadecimais minúsculos, obrigatório e único |
| `used_at` | Timestamp com fuso, obrigatório, default do banco; conexões em UTC |

O proprietário é derivado de `UserSession`, sem duplicar `user_id`. A tabela não
armazena token bruto, access JWT, senha, IP ou user-agent. A relação ORM
`UserSession.used_refresh_tokens` mantém a exclusão restrita mesmo quando a
coleção está carregada. Isso não representa uma auditoria imutável.

Em `backend/app/core/refresh_tokens.py`, `generate_refresh_token()` usa
`secrets.token_urlsafe(32)` e retorna `SecretStr`: 32 bytes aleatórios (256 bits),
em 43 caracteres base64url sem padding. `refresh_token_digest()` exige essa
representação canônica antes de calcular SHA-256 do texto ASCII. Erros de formato
são uniformes, sem ecoar a credencial; entradas excessivas são recusadas antes
da decodificação e do hashing. O formato não comprova aleatoriedade: credenciais
emitidas devem vir do gerador criptográfico, e não de exemplos ou fixtures.

Tokens aleatórios têm alta entropia e usam digest para consulta; senhas humanas
continuam protegidas por Argon2id. Nenhum helper grava `.env`, cria sessão,
emite cookie ou expõe token por endpoint nesta etapa.

Essa estrutura sustenta o serviço de sessões e os endpoints de login,
renovação, logout e perfil próprio descritos abaixo.

Não há limpeza automática. O histórico deve permanecer disponível durante a
validade da sessão; a política operacional de retenção/expurgo será definida
antes de produção. Remover a tabela perde digests consumidos. O downgrade para
`0006_goals_allocations` preserva as dez tabelas anteriores, mas requer revisão
de segurança e autorização própria em ambientes com sessões reais.

Os testes usam dados sintéticos e PostgreSQL descartável para validar FK,
unicidade, formato, UTC, restrição de exclusão e preservação dos registros
anteriores no upgrade/downgrade. Não executam migrations no banco pessoal.

## Ciclo interno de sessões e proteção de cookies

`backend/app/services/sessions.py` fornece `SessionService`: login, refresh,
autenticação de access JWT com consulta ao banco e revogação por credencial.
Cada operação possui sua própria sessão SQLAlchemy e transação. O cadastro,
health, CORS e frontend continuam com seus contratos atuais; esses serviços e
helpers são utilizados pelos endpoints descritos na próxima seção.

O login normaliza o e-mail, preserva a senha e verifica Argon2id. Usuários
desconhecidos passam por verificação com hash dummy em memória; isso reduz
diferenças de caminho sem garantir tempos iguais. Usuário inexistente/inativo
ou senha errada recebem a mesma negação interna. Depois da verificação, o
serviço bloqueia e relê usuário/hash para conferir mudanças concorrentes.

Cada login cria uma sessão independente. Refresh usa token opaco aleatório,
guardando somente digest. O prazo padrão é **sete dias absolutos**, configurável
entre uma hora e sete dias por `FINSIGHT_AUTH_REFRESH_TTL_SECONDS`. Renovar não
estende esse prazo. Access JWT mantém o prazo configurado, padrão15minutos; o
acesso efetivo e o cookie também respeitam a expiração da sessão.

Na renovação, o serviço bloqueia User antes de UserSession, relê os dados e
atualiza o digest atual, o histórico consumido e last_used_at atomicamente.
Credenciais só são entregues após o commit. Reutilizar um digest consumido
conhecido revoga a sessão; a revogação é confirmada antes de retornar a negação.
Token desconhecido ou UUID isolado não autoriza revogar uma sessão.

A política de concorrência é estrita: dois refreshes com o mesmo token podem
resultar em uma emissão inicial seguida de revogação da sessão. Isso também
invalida a emissão inicial nas próximas verificações e pode exigir novo login
após uma corrida legítima. O cliente futuro deverá serializar renovações. Não
há janela de tolerância ou armazenamento de tokens brutos para reenvio.

`authenticate()` valida assinatura/claims e consulta o vínculo usuário/sessão:
sub/sid devem corresponder, o usuário deve estar ativo e a sessão deve estar
criada, válida e não revogada. Logout interno exige refresh conhecido ou access
JWT assinado com vínculo válido; é idempotente e não afeta outras sessões.
Novas verificações são negadas após revogação; requisições em andamento não são
canceladas. Resultados internos excluem credenciais de repr e serialização.

`backend/app/core/csrf.py` implementa double-submit assinado HMAC-SHA256,
vinculado a contexto aleatório de pré-login ou sessão verificada pelo servidor,
com propósitos separados. Cookie/header devem coincidir, assinatura e prazo
devem ser válidos. O token é limitado a 256 bytes e não é de uso único. Origens
de mutações precisam constar em `FINSIGHT_AUTH_ALLOWED_ORIGINS`; ausência/null
ou origem desconhecida é negada. SameSite e CORS não substituem CSRF.

Configure `FINSIGHT_AUTH_CSRF_SIGNING_KEY` separadamente da chave JWT: 32 bytes
aleatórios representados por 64 caracteres hexadecimais. As duas chaves não podem ser iguais. Não
há geração automática, chave padrão ou gravação em `.env`. O exemplo comentado
é inutilizável; nunca publique chaves reais. Prazo CSRF padrão de 900 segundos,
configurável entre 60–3600 por `FINSIGHT_AUTH_CSRF_TTL_SECONDS`.

`backend/app/core/auth_cookies.py` define cookies host-only, Path=/,
SameSite=Lax. Em HTTPS seguro usa prefixo `__Host-finsight-` e Secure; access,
refresh e pré-login são HttpOnly. Somente o cookie CSRF é legível pelo cliente
para cópia ao header. Expiração é limitada pelos prazos correspondentes;
exclusão repete os atributos. Cookies duplicados ou cabeçalhos acima de 16 KiB são
recusados, e credenciais não ficam em JSON ou localStorage pelos helpers.

`FINSIGHT_AUTH_COOKIE_SECURE` é true por padrão. O `.env.example` demonstra
false explicitamente para HTTP de desenvolvimento/teste: exige hostname local
e cliente ASGI em loopback, sem confiar em X-Forwarded-*. Nesse caso os nomes
são `finsight_access`, `finsight_refresh`, `finsight_preauth`, `finsight_csrf`.
Produção exige true/HTTPS e origens HTTPS. Proxies precisarão de configuração
de confiança própria antes de produção.

Os endpoints abaixo integram CSRF/cookies, limites de recursos e CORS explícito
com credenciais. Nenhuma tela financeira ou de autenticação foi acrescentada.

## Autenticação HTTP

As rotas ficam sob `/api/v1/auth`. Todas as suas respostas usam `Cache-Control:
no-store`, inclusive erros e preflight. Configure as duas chaves distintas de
assinatura e as origens explícitas do `.env.example` antes de usar as mutações
de sessão. Ausência de configuração retorna erro503 estático; health e cadastro
continuam independentes. Nenhum helper gera chaves reais ou altera seu `.env`.

| Método/rota | Entrada | Sucesso |
| --- | --- | --- |
| `POST /csrf` | JSON `{}`, `Origin` autorizado, `X-CSRF-Bootstrap: 1` | 200 com `csrf_token` e cookies do contexto |
| `POST /login` | JSON `email`/`password`, `Origin`, `X-CSRF-Token` | 204 com cookies de autenticação e novo CSRF |
| `POST /refresh` | JSON `{}`, `Origin`, `X-CSRF-Token` da sessão | 204 com access/refresh rotacionados |
| `POST /logout` | JSON `{}`, `Origin`, `X-CSRF-Token` correspondente | 204 com revogação e exclusão dos cookies |
| `GET /me` | Access no cookie, sessão/usuário válidos | 200 com `id`, `name`, `email` próprios |

O navegador deve fazer bootstrap antes do login, copiando o `csrf_token` ao
header dedicado. O bootstrap usa POST para exigir Origin também na mesma
origem; ele não autentica nem modifica sessões do banco. Login bem-sucedido
remove o contexto pré-login e cria CSRF vinculado à nova sessão. O cliente deve
usar o cookie CSRF atual nas próximas mutações ou solicitar novo bootstrap.
Access/refresh nunca aparecem no JSON, no localStorage ou na URL.

Uma sessão conhecida exige logout antes de outro login (409). Refresh não aceita
tokens ou identificadores no corpo. Reutilização de token consumido com CSRF
válido persiste a revogação antes de401; a política estrita de concorrência
continua valendo. Não reenviar automaticamente POST de refresh após falha.

Para CSRF, uma credencial conhecida pode identificar uma sessão expirada ou
revogada, permitindo logout idempotente e limpeza segura. Esse UUID interno
é apenas vínculo de assinatura, não autorização. Credenciais reconhecidas de
sessões diferentes são recusadas. Sem credencial conhecida, bootstrap autorizado
prepara pré-login e limpa cookies locais; logout com esse contexto apenas apaga
cookies, sem revogar qualquer sessão por UUID fornecido pelo cliente.

`GET /me` deriva o proprietário de credenciais validadas no backend, mesmo que
uma query forneça outro `user_id`. A alteração de senha está descrita abaixo;
edição de perfil, recuperação de senha e autorização financeira seguem pendentes.

| Erro | Significado |
| --- | --- |
| 401 | Credencial/sessão negada; login não distingue usuário inexistente/inativo/senha errada |
| 403 | Origem, CSRF, cookie ambíguo ou política de transporte recusados |
| 409 | Logout necessário antes de iniciar outra sessão |
| 413/415/422 | Corpo excessivo/tipo não JSON/dados inválidos, sem ecoar entradas |
| 429 | Limite atingido, com `Retry-After` |
| 503 | Configuração ou persistência indisponível, sem detalhes internos |

Falhas de origem/CSRF não revogam sessões nem apagam cookies.401 de refresh após
CSRF válido limpa cookies locais;503/429 preservam credenciais para nova tentativa.
Consulta de perfil negada não altera cookies. Cabeçalhos de segurança e cookies
duplicados são recusados antes de decisões mutáveis.

CORS com credenciais se aplica somente às rotas de sessão e alteração de senha, com
`FINSIGHT_AUTH_ALLOWED_ORIGINS`. Cadastro/health mantêm CORS sem credenciais.
O navegador usa `credentials: 'include'`; no desenvolvimento, use o mesmo host
no frontend e API (ambos `localhost` ou ambos `127.0.0.1`). Misturar esses hosts
é incompatível com a política SameSite. Em produção, priorize a mesma origem
HTTPS. Não ampliar para origens arbitrárias ou SameSite=None sem revisar o desenho.

Limites por processo/IP: login5/minuto, demais rotas60/minuto e registro de
clientes limitado4096. Corpo real limitado16KiB no login e1KiB nos outros POST,
inclusive em partes/sem Content-Length confiável. Os nomes das configurações
estão no `.env.example`. Login/cadastro compartilham os dois slots de Argon2;
excesso não entra em fila. Limites compartilhados/borda e proxies confiáveis
continuam necessários antes de produção com múltiplas instâncias.

### Testes de sessão com banco descartável

`npm test` preserva os onze testes iniciais com API sem banco na porta8001.
Execute depois `npm run test:auth` para os fluxos de sessão em API8002 e navegador,
com dois usuários sintéticos. A configuração separada exige Docker Linux e cria
seu próprio PostgreSQL18.6 fixado por digest, nome/DB UUID e porta dinâmica em
loopback, sem acessar `.env` ou banco pessoal. Ambos usam o frontend4175 e devem
rodar sequencialmente; portas ocupadas não são reutilizadas.

O global setup aplica migrations apenas nesse contêiner, gera chaves efêmeras
em memória e cria usuários pelo cadastro HTTP. Teardown encerra somente processo
e contêiner próprios, também em falhas de preparação. Encerramento forçado da
máquina pode impedir cleanup; inspecione o nome UUID específico em
`test-results/auth-cleanup.json` e remova somente esse
recurso depois de confirmar sua propriedade. Nunca execute limpeza global.

Relatórios ficam em `test-results/` e `playwright-report/`, ignorados pelo Git.
Os projetos de sessão desabilitam traces, screenshots, vídeo e persistência de
storageState para não gravar cookies/tokens. Asserções exibem status e campos
sintéticos seguros. O CI executa os dois conjuntos; seu resultado depende da
publicação e aprovação do PR.

## Alterar a própria senha

`POST /api/v1/users/me/change-password` implementa RF-007. Exige access válido no
cookie, usuário/sessão ativos, origem autorizada, CSRF vinculado à sessão e
confirmação da senha atual. O corpo JSON aceita somente `current_password` e
`new_password`, ambas com 15–128 caracteres Unicode válidos. Espaços são preservados;
senha composta apenas por espaços é inválida. Identificadores e tokens no corpo
são recusados. A nova senha deve diferir da atual, sem outras regras de composição
ou histórico de senhas antigas nesta entrega.

Depois de verificar a senha atual com Argon2id, o serviço bloqueia e relê o usuário
e a sessão para conferir expiração, revogação e mudanças concorrentes. Na mesma
transação, substitui o hash e revoga todas as sessões do proprietário, inclusive
a atual. Sessões de outros usuários e timestamps de revogações anteriores são
preservados. Os locks seguem a ordem User antes de UserSession, compartilhada com
login/refresh/logout. Falha de banco/commit ou relógio anterior à criação de uma
sessão a revogar causa rollback integral, sem datas corrigidas silenciosamente.

Sucesso retorna204 sem corpo apenas após commit e apaga os cookies locais. Será
necessário entrar novamente com a nova senha em todos os dispositivos. Tokens
antigos deixam de autenticar nas próximas verificações de banco; requisições em
andamento não são canceladas. Se a resposta se perder depois do commit, não
repetir automaticamente: a sessão antiga estará revogada; tentar novo login com
a nova senha. Não há renovação automática de sessão ou envio de e-mail.

| Resultado | Efeito |
| --- | --- |
| 204 | Senha alterada, sessões próprias revogadas, cookies locais apagados |
| 401 | Senha atual ou autenticação negada; nenhuma mutação/cookie apagado |
| 403 | Origem/CSRF/transporte inválido; nenhuma mutação |
| 422 | Entrada inválida ou nova senha igual à atual após reautenticação |
| 429 | Limite de requisições ou hashes; `Retry-After`, sem mutação |
| 503 | Configuração/persistência/relógio indisponível, sem sucesso parcial |

As respostas e erros usam no-store e não expõem senhas, hashes ou tokens.
`FINSIGHT_AUTH_PASSWORD_CHANGE_REQUESTS_PER_MINUTE` limita cinco tentativas por
minuto/IP/processo por padrão (configurável1–100), em bucket separado de login,
dentro da capacidade total de clientes já existente. O corpo usa o limite de
credenciais de16KiB. Cadastro/login/troca compartilham os mesmos slots de Argon2;
não há fila nem limitação distribuída nesta entrega.

Pytest valida isolamento, rollback e corridas com conexões PostgreSQL próprias.
`npm run test:auth` inclui API/navegador com usuários sintéticos exclusivos por
cenário, sem modificar alice/bob dos testes existentes. Não há UI de produto,
novas dependências, schema ou migrations nesta alteração. Os testes continuam
sem persistir traces, vídeo, screenshots ou estado de autenticação.

## Consultar e editar o próprio perfil

`GET /api/v1/users/me` retorna somente `id`, `name` e `email` do usuário
autenticado. `GET /api/v1/auth/me` permanece disponível com o mesmo contrato.
`PATCH /api/v1/users/me` aceita `name` e/ou `email` em JSON e retorna 204 sem corpo.
Exige sessão ativa, origem autorizada e `X-CSRF-Token` vinculado à sessão.
O proprietário vem da sessão; enviar `user_id` ou outra propriedade desconhecida
é inválido. Campos nulos, corpo vazio e valores inválidos são recusados.

O nome é aparado nas extremidades e tem 1–120 caracteres Unicode válidos. O e-mail
segue a validação do cadastro, com normalização para minúsculas e limite de 255 caracteres.
Atualizar apenas o nome preserva as sessões e não exige senha. Reenviar o mesmo
e-mail normalizado também preserva as sessões. Ao trocar efetivamente o endereço,
inclua `current_password` com a senha atual, preservando seus espaços.
Ela tem a mesma política de 15–128 caracteres do cadastro e nunca é retornada.

Depois da reautenticação, o serviço bloqueia e relê usuário/sessão. Na mesma
transação, altera o e-mail e revoga todas as sessões próprias, preservando outros
usuários e revogações anteriores. Sucesso apaga os cookies locais e exige novo
login com o endereço novo e a senha existente. Erro de banco ou conflito desfaz
também uma alteração de nome enviada junto, sem atualização parcial.

| Status PATCH | Significado |
| --- | --- |
| 204 | Perfil atualizado; troca efetiva de e-mail também encerra sessões |
| 401 | Sessão ou senha atual inválida |
| 403 | Origem/CSRF/transporte inválido |
| 409 | Atualização indisponível por conflito de e-mail; sem dados de terceiros |
| 422 | Entrada inválida ou senha atual ausente na troca de e-mail |
| 429 | Limite de requisições/hashes; observar `Retry-After` |
| 503 | Serviço temporariamente indisponível; sem sucesso parcial |

PATCH compartilha o limite de tentativas da troca de senha, cinco por minuto/IP/processo
por padrão (`FINSIGHT_AUTH_PASSWORD_CHANGE_REQUESTS_PER_MINUTE`), além dos slots de
Argon2 com cadastro/login. O corpo tem limite de 16 KiB. Respostas usam `no-store` e
erros sanitizados. CORS permite GET/PATCH somente nas origens de autenticação
configuradas para esse caminho; não habilita PATCH nas demais rotas.

Ainda não existe confirmação de posse do novo e-mail ou envio de mensagens.
Essa limitação deve ser resolvida antes de disponibilizar troca de e-mail em
produção. Revogação não cancela requisições em andamento; se a resposta se perder
após commit, tente login com o novo e-mail em vez de repetir automaticamente.
Não há interface nova, dependência ou migração nesta entrega.

Durante o desenvolvimento, execute testes novos/diretamente afetados; a suíte
completa permanece no CI. O cenário API desta entrega pode ser selecionado com
`npm run test:auth -- --project=session-api tests/auth-api/profile.spec.ts`.
Ele usa o PostgreSQL descartável e o teardown da configuração de autenticação.

## Preparação da criação idempotente de contas

A revisão `0008_account_creation_requests` persiste tentativas de criação de
contas. A API descrita abaixo usa esse armazenamento para tratar retries.

A tabela técnica `account_creation_requests` guarda `user_id`, `idempotency_key`
(UUIDv4), `request_hash` (SHA-256 em hexadecimal minúsculo), `account_id` e
`created_at` em UTC. A chave primária combina usuário e chave de idempotência:
dois usuários podem usar a mesma chave sem compartilhar dados. A chave estrangeira
composta exige que a conta pertença ao usuário informado. O banco também valida
UUIDv4 e o formato do digest, inclusive para gravações que não passam pelo ORM.
Há índice em usuário/conta para suportar consultas dessa relação.

Não são armazenados corpos JSON, senhas, cookies ou tokens. O serviço calcula o
digest da entrada normalizada e grava conta e chave na mesma transação.
O tratamento de replay/conflito está na API; as restrições do banco reforçam
unicidade e propriedade. Nenhum saldo atual é calculado nesta etapa.

Após aplicar a migração no banco correto, estas consultas de leitura podem ser
usadas no DBeaver:

```sql
SELECT current_database();
SELECT version_num FROM public.alembic_version;

SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'account_creation_requests'
ORDER BY ordinal_position;

SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'public.account_creation_requests'::regclass
ORDER BY conname;

SELECT count(*) AS persisted_creation_requests
FROM public.account_creation_requests;
```

Resultado esperado em um banco recém-migrado: revisão `0008_account_creation_requests`,
cinco colunas não nulas, chave primária composta, duas chaves estrangeiras,
verificações de digest/UUIDv4 e zero registros. Nenhuma conta, usuário ou chave é
criada automaticamente. A API continua sem executar migrations no startup.

`downgrade 0007_refresh_token_history` remove somente essa tabela técnica e seu
índice, preservando contas existentes. Também apaga a memória de retries: quando
a API de criação existir, repetir uma operação antiga após o downgrade poderá
criar outra conta. Retenção e exclusão dessas chaves precisam de política própria;
não há expurgo automático nesta etapa. Não aplique rollback em um banco em uso
sem avaliação e autorização específicas.

## Cadastrar, listar e consultar contas próprias

A primeira entrega da Fase 2 implementa RF-010/RF-013:

| Método e rota | Resultado |
| --- | --- |
| `POST /api/v1/accounts` | 201 com `{"id":"UUID"}` e cabeçalho `Location` |
| `GET /api/v1/accounts` | Lista paginada somente das contas do usuário autenticado |
| `GET /api/v1/accounts/{id}` | Dados da conta própria; conta alheia/inexistente retorna404 |

Todas exigem cookies de autenticação e sessão ativa no banco. A criação exige
também origem autorizada, `X-CSRF-Token` de sessão e `Idempotency-Key` com UUIDv4.
Conhecer a chave de idempotência ou o UUID da conta não concede acesso.
O proprietário vem da sessão; `id`, `user_id` e outros campos não previstos no
corpo são recusados. Não envie tokens ou senhas no JSON.

Exemplo de corpo, somente com dados fictícios:

```json
{
  "name": "Conta de exemplo",
  "type": "checking",
  "currency": "BRL",
  "opening_balance": "-10.25",
  "opening_date": "2026-01-01"
}
```

Nome tem1–100caracteres Unicode válidos, com espaços externos removidos. Os tipos
são `checking`, `savings`, `cash` ou `investment`; moeda é somente `BRL` (padrão).
Dinheiro deve ser string decimal finita, sem notação científica, com até duas
casas e limite `9999999999999.99` em valor absoluto. Saldo inicial negativo é
permitido. Números JSON e valores com mais casas decimais são recusados, sem
arredondamento silencioso. A data deve ser uma data válida em `YYYY-MM-DD`.
A abertura representa a posição ao final da data; não cria receita ou transação.

Para repetir a mesma intenção de criação, preserve a chave e os dados. O serviço
normaliza nome, data, moeda e Decimal antes de calcular SHA-256; `"0.1"` e `"0.10"`
representam a mesma entrada, assim como zero e zero negativo. O mesmo
usuário/chave/entrada retorna novamente201 com o mesmo id/Location, inclusive
usando outra instância da API. Usar a mesma chave com dados diferentes retorna409,
sem criar conta. Outra chave representa outra criação; nomes iguais não são
deduplicados. Cada usuário possui seu próprio espaço de chaves.

Usuário e sessão são relidos dentro da transação. A criação compartilha o lock de
usuário com login/refresh/logout, evitando aceitar revogação concorrente; duas
tentativas simultâneas com a mesma chave criam uma conta e um registro de retry.
Conta e chave são confirmadas juntas. Falha de commit desfaz ambas. A serialização
por usuário é uma escolha para o MVP, sem fila distribuída ou framework adicional.

A listagem aceita `limit` (padrão50,1–100) e `offset` (0–2147483647). Retorna
`items`, `limit`, `offset` e `has_more`, com ordem estável por criação/id. Inclui
contas próprias ativas e arquivadas, com `is_active` explícito; filtros adicionais
ainda não existem. Consulta/listagem retornam id, nome, tipo, moeda, saldo inicial
como string com duas casas, data de abertura e atividade. Não expõem proprietário,
hash de retry ou credenciais. Saldo atual, consolidado e histórico ainda não são
calculados.

Respostas usam `no-store`. CORS credenciado das contas aceitaGET/POST e os
cabeçalhos necessários somente nas origens de autenticação configuradas. Corpos
de criação têm limite16KiB; cabeçalhos duplicados de segurança/idempotência são
recusados. As rotas compartilham o limite existente
`FINSIGHT_AUTH_REQUESTS_PER_MINUTE` e a capacidade de clientes por processo;
`X-Forwarded-For` não muda o cliente sem configuração de proxy confiável.

Erros:401autenticação,403origem/CSRF,404conta ausente/alheia,409chave conflitante,
422entrada/chave/paginação inválida,429limite e503indisponibilidade. As mensagens
não repetem entradas nem dados de terceiros. Não há edição, arquivamento,
exclusão ou interface de contas nesta entrega.

É necessário aplicar a revisão0008 no banco correto antes de usar a criação;
migrations não são executadas no startup. Os testes usam PostgreSQL descartável
e usuários sintéticos. Para selecionar o cenário API novo:
`npm run test:auth -- --project=session-api tests/auth-api/accounts.spec.ts`.
A suíte completa continua no CI; localmente são executados novos/afetados.

## Acessar o FinSight pelo navegador

A página pública possui o botão **Acessar FinSight**. Ele consulta a sessão quando
acionado e apresenta o formulário de login quando necessário. A home não depende
da API de autenticação para carregar. **Criar acesso** envia nome, e-mail e senha;
a resposta é genérica e pede que a pessoa entre, sem afirmar se o e-mail já existia.
Senhas têm15–128caracteres, preservam espaços e são limpas dos campos após o envio.
**Sair** confirma a revogação no servidor antes de limpar a área autenticada.

O frontend lê `VITE_API_BASE_URL` do ambiente ou do `.env` na raiz do repositório.
Essa URL é pública e não pode conter usuário/senha, query ou fragmento. Em produção
use uma origem HTTPS; em desenvolvimento prefira `http://127.0.0.1:8000` e abra
o Vite em `http://127.0.0.1:5173`. Os dois lados devem usar o mesmo hostname local.
Sem URL configurada, a aplicação usa a API local na porta8000 em loopback e a
própria origem em outros ambientes. Alterações na configuração exigem reiniciar
o Vite; o preview precisa de um novo build.

As origens do frontend precisam constar tanto em `FINSIGHT_CORS_ORIGINS`
(cadastro sem credenciais) como em `FINSIGHT_AUTH_ALLOWED_ORIGINS` (sessões).
As chaves de assinatura e a configuração do banco seguem as instruções anteriores.
Não coloque segredos em variáveis `VITE_*`: elas são incorporadas ao código público.

O cliente não lê access/refresh tokens, não os coloca no JSON e não salva credenciais
em localStorage/sessionStorage. Cadastro usa fetch sem cookies; autenticação usa
cookies e o fluxo de bootstrap CSRF. Mutações e renovação são coordenadas entre
abas da mesma origem pela Web Locks API. Antes de renovar, a aba confere se outra
já recuperou a sessão. Se Web Locks não estiver disponível, não há refresh
automático: será necessário entrar novamente. Use uma única origem de frontend
para evitar renovação concorrente entre aplicações independentes.

Falha de rede/servidor é exibida como indisponibilidade, sem confundir com senha
incorreta ou mostrar erros internos. Se a saída não puder ser confirmada, a área
continua identificada como autenticada e oferece nova tentativa. A navegação
desta primeira interface acontece no próprio React, sem novas dependências ou
rotas profundas. Dados reais e credenciais não devem aparecer em evidências.
