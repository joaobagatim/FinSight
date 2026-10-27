# FinSight

FinSight é uma plataforma de gestão financeira pessoal desenvolvida com React, Python (FastAPI) e PostgreSQL. Permite controlar receitas e despesas, importar extratos bancários, visualizar dashboards interativos, analisar tendências financeiras e planejar metas com projeções inteligentes.

## Desenvolvimento

A infraestrutura da Fase 0 está implementada. A Fase 1 adiciona modelos e migrações
de usuários, sessões, contas, categorias e prévias de importação;
cadastro e autenticação ainda serão implementados.
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
`0004_imports` cria `import_jobs` e `import_rows`, além do controle técnico
`alembic_version`. Os demais modelos serão adicionados em unidades seguintes.
Repetir o upgrade mantém a mesma revisão. A aplicação
não executa migrações automaticamente ao iniciar. `check` compara o banco com
`Base.metadata`, com usuários, sessões, contas, categorias e importações; tabelas manuais podem ser
identificadas como divergências. Revise qualquer migração gerada antes de aplicá-la.

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
`0004_imports` e as sete tabelas `alembic_version`, `users`, `user_sessions`,
`accounts`, `categories`, `import_jobs` e `import_rows`.
Antes do primeiro upgrade, essas tabelas ainda não existem. As consultas acima
são somente de leitura. A migração não cria usuários nem sessões automaticamente.

O rollback de teste `downgrade 0003_accounts_categories` remove jobs/linhas,
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
Validação completa de e-mail e hashing Argon2id serão responsabilidades do cadastro.

As sessões referenciam um usuário, exigem hash de refresh único e expiração
posterior à criação. Revogação e último uso são opcionais e não podem anteceder
a criação. Os campos armazenam hashes; ainda não existe serviço que gere,
valide ou renove tokens. O schema não verifica criptograficamente um hash.
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
