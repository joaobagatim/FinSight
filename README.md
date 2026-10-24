# FinSight

FinSight é uma plataforma de gestão financeira pessoal desenvolvida com React, Python (FastAPI) e PostgreSQL. Permite controlar receitas e despesas, importar extratos bancários, visualizar dashboards interativos, analisar tendências financeiras e planejar metas com projeções inteligentes.

## Desenvolvimento

O projeto está na Fase 0, de preparação da infraestrutura. As funcionalidades
financeiras descritas acima fazem parte do escopo planejado.

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
unidade. Tailwind CSS e shadcn/ui serão configurados na próxima unidade.

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
`0001_phase0` é uma base vazia: cria somente o controle técnico `alembic_version`,
sem tabelas financeiras. Repetir o upgrade mantém a mesma revisão. A aplicação
não executa migrações automaticamente ao iniciar. `check` compara o banco com
`Base.metadata`, atualmente vazio; tabelas criadas manualmente também podem ser
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

Resultado esperado em um banco inicialmente vazio: nome do banco configurado,
uma linha `0001_phase0` e somente a tabela `alembic_version`. Antes do primeiro
upgrade, essa tabela ainda não existe. As consultas acima são somente de leitura.

O rollback de teste é `downgrade base`: nesta revisão vazia, remove a linha de
versão e mantém a tabela técnica vazia. Migrações futuras podem remover tabelas
ou dados no downgrade; revise-as antes de executar rollback em bancos com dados.
Os testes `--run-postgres` validam upgrade, downgrade e detecção de divergência
somente em seu banco temporário próprio, preservando o banco de desenvolvimento.

Para alterar o esquema no futuro, importe os models em `alembic/env.py`, gere uma
revisão com `revision --autogenerate -m "describe schema change"`, revise o arquivo
em `backend/alembic/versions/` e só então aplique `upgrade head`. Ainda não há models
de domínio nesta fase. Consulte o [tutorial oficial do Alembic](https://alembic.sqlalchemy.org/en/latest/tutorial.html).
