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
de conexões e timeouts da sessão. Alembic permanece para a próxima unidade.

Se o Pytest encontrar erro de permissão no temporário padrão do Windows, use uma
pasta de testes exclusiva dentro do projeto, que já está ignorada:

```powershell
$taskPytestTemp = Join-Path (Get-Location).Path 'backend/.cache/pytest-temp'
New-Item -ItemType Directory -Path $taskPytestTemp -Force | Out-Null
$env:PYTEST_DEBUG_TEMPROOT = $taskPytestTemp
```

Depois repita o comando Pytest desejado nesse terminal. A variável vale somente
para o terminal atual; o Pytest gerencia seus subdiretórios numerados de teste.
