# Demonstração local isolada

**Neste Windows, a porta em uso para o banco da demo é `127.0.0.1:5546`.** Se a publicação Docker `5544` não responder ao protocolo PostgreSQL, a ferramenta abre esse encaminhamento alternativo somente em loopback. Ele transporta bytes por `docker exec` para TCP/SCRAM dentro do ID do contêiner validado; não executa SQL, não fornece senha e não altera autenticação. O supervisor controla exclusivamente seus próprios processos e encerra o encaminhamento ao parar a demo. Consulte `.demo/transport.json` para a porta ativa. Não apaga/recria dados para corrigir falhas de publicação do Docker Desktop. A primeira conexão pode ser mais lenta nesse modo.

Esta demonstração usa somente dados fictícios. Não lê o `.env` pessoal nem aplica migrations ao banco pessoal. Requer Docker Desktop com Linux containers, Python/ambiente virtual do backend e dependências Node já instaladas conforme o README.

Na raiz do repositório, em PowerShell:

```powershell
backend\.venv\Scripts\python.exe tools/demo.py start
```

O comando gera credenciais independentes em `.demo/.env` (ignorado pelo Git), cria os recursos exclusivos abaixo, verifica contêiner/volume/porta e a identidade SQL antes de migrar, inicia API/frontend e executa o seed pelo cadastro/login e pelas APIs financeiras normais. Não há bypass de autenticação. O usuário fictício é `demo.finsight@example.com`; consulte `DEMO_PASSWORD` no arquivo local para entrar. Não publique esse arquivo. Os exemplos contêm somente placeholders.

| Recurso              | Destino exclusivo                               |
| -------------------- | ----------------------------------------------- |
| Interface            | http://127.0.0.2:5180                           |
| API / documentação   | http://127.0.0.2:8010/docs                      |
| Saúde                | http://127.0.0.2:8010/health                    |
| Projeto Compose      | `finsight-demo`                                 |
| Contêiner PostgreSQL | `finsight-demo-postgres`                        |
| Volume persistente   | `finsight-demo-data`                            |
| DBeaver              | `127.0.0.1:5544`, banco/usuário `finsight_demo` |

A senha do PostgreSQL é `DEMO_DB_PASSWORD` no arquivo local. `127.0.0.2` é loopback e separa os cookies da demo dos usados em `localhost`/`127.0.0.1`; cookies não são isolados por porta. A exceção HTTP permanece restrita a desenvolvimento/teste, host permitido e cliente loopback. Não altere para usar o host pessoal, não exponha as portas na rede e não use credenciais reais. A faixa “Ambiente de demonstração” permanece visível antes e depois do login.

O seed contém duas contas, quatro categorias e seis lançamentos: quatro efetivados e dois planejados, todos fictícios. Datas são ancoradas na primeira execução e preservadas; saldos iniciais são anteriores aos lançamentos. Na conta corrente, o saldo na data inicial da demo é R$ 3.754,20; na reserva, R$ 2.850,00. Planejados não afetam o saldo real. Chaves de criação/corpos estáveis e IDs de categorias ficam em `.demo/seed.json`: repetir o seed não restaura edições feitas pelo usuário nem cria cópias. Não apague esse arquivo mantendo o banco, pois ele guarda as chaves de idempotência. Trocar a senha do perfil exige atualizar `DEMO_PASSWORD` localmente antes de repetir o seed.

```powershell
# Consultar / repetir o seed (não apaga nem restaura dados editados):
backend\.venv\Scripts\python.exe tools/demo.py status
backend\.venv\Scripts\python.exe tools/demo.py seed

# Parar apenas a demo, conservando o banco e o volume:
backend\.venv\Scripts\python.exe tools/demo.py stop

# Reabrir usando os mesmos dados e credenciais:
backend\.venv\Scripts\python.exe tools/demo.py start

# Verificações diretamente relacionadas:
backend\.venv\Scripts\python.exe -m pytest tools/test_demo.py -q
npx playwright test --config playwright.demo.config.ts
```

O supervisor encerra somente seus próprios subprocessos. Nenhum comando de limpeza é executado automaticamente. O comando `stop` não usa `down -v`, não remove contêineres e não remove volumes. Não use o Compose pessoal para controlar a demo. Se um crash deixar `.demo/running.lock`, confira primeiro os logs e os processos/portas exclusivos; não mate PIDs de um arquivo antigo nem apague o volume para resolver uma falha de inicialização.

Não há comando automático de reset nesta ferramenta. Para remover dados futuramente, pare a demo, confira explicitamente os labels do projeto e o volume `finsight-demo-data` e realize uma operação exclusiva e deliberada. Nunca reutilize esse procedimento no projeto `finsight` ou no volume pessoal. Preserve `.demo/.env` e `.demo/seed.json` enquanto conservar o banco.

Evidências locais sanitizadas: `.demo/migration-result.json`, `seed-result.json`, `preservation-result.json` e logs de serviço. A comprovação de preservação compara bytes dos arquivos pessoais de ambiente, configuração/ciclo de vida dos contêineres não demo e metadados dos volumes não demo; não consulta nem exporta dados financeiros pessoais. `.demo/personal-before.json` contém metadados locais e também não deve ser publicado. Os diretórios de evidências são ignorados pelo Git.
