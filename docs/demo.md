# Demonstração local isolada

A demonstração inclui contas, lançamentos, transferências, saldos, **Metas** (com reservas e progresso), **Importações** (CSV com revisão e confirmação) e **Dashboard** (indicadores e gráficos por período). O seed prepara uma meta e uma reserva fictícias e gera um CSV para revisão manual. Não confirma importações automaticamente. O [roteiro integrado](mvp-walkthrough.md) explica os fluxos com dados fictícios.

**A porta principal do banco da demo é `127.0.0.1:5544`.** Se a publicação Docker não responder ao protocolo PostgreSQL, a ferramenta abre um encaminhamento alternativo em `127.0.0.1:5546`, somente em loopback. Ele transporta bytes por `docker exec` para TCP/SCRAM dentro do ID do contêiner validado; não executa SQL, não fornece senha e não altera autenticação. O supervisor controla exclusivamente seus próprios processos e encerra o encaminhamento ao parar a demo. Consulte `.demo/transport.json` para a porta ativa. Não apaga/recria dados para corrigir falhas de publicação do Docker Desktop. A primeira conexão pode ser mais lenta nesse modo.

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

O seed contém duas contas, quatro categorias e seis lançamentos: quatro efetivados e dois planejados, todos fictícios. Datas são ancoradas na primeira execução (calendário de São Paulo para novas demos) e preservadas; saldos iniciais são anteriores aos lançamentos. Na conta corrente, o saldo na data inicial da demo é R$ 3.754,20; na reserva, R$ 2.850,00. Planejados não afetam o saldo real.

A meta **Reserva de emergência fictícia** tem alvo de **R$ 1.000,00** e reserva inicial de **R$ 500,00** na conta **Reserva fictícia**. No exemplo intacto, o progresso é **50%**, o saldo bancário continua **R$ 2.850,00** e o saldo livre é **R$ 2.350,00**. Reservar não cria despesa. Essa extensão também é preparada na próxima execução do seed de uma demo antiga, preservando suas oito chaves originais, datas, categorias e dados editados; depende de saldo livre e estado válidos, verificados pelas APIs normais.

Chaves, corpos de criação, data e ETag da intenção de reserva ficam em `.demo/seed.json` antes do envio. Resposta perdida pode ser repetida com a mesma intenção; uma reserva concluída não é refeita após retirada manual. Não apague esse arquivo mantendo o banco. Se uma intenção pendente ficou obsoleta antes de ser aceita, a API pode recusá-la: confira o estado antes de tentar qualquer recuperação, sem gerar automaticamente outra chave ou apagar dados. Trocar a senha do perfil exige atualizar `DEMO_PASSWORD` localmente antes de repetir o seed.

O arquivo UTF-8 **`.demo/import-example.csv`** contém uma entrada fictícia de R$ 250,00 e uma saída de R$ 50,00, com datas relativas à âncora da demo. Não é sobrescrito se você o editar. Em **Importações**, escolha a conta corrente fictícia, envie o arquivo e mapeie `Date`, `Description` e `Amount` (data ISO, ponto decimal). Classifique os registros com categorias compatíveis, selecione os dois e revise as três ciências antes de confirmar. Os dois lançamentos só são criados por essa confirmação explícita; em uma demo intacta, elevam o saldo da conta corrente a R$ 3.954,20. Consulte a posição em data posterior aos registros e não importe novamente sem revisar possíveis duplicatas.

O seed usa **`.demo/seed.lock`** para recusar comandos simultâneos. Se um processo cair e deixar o lock, confirme que nenhuma execução continua ativa antes de removê-lo manualmente; não apague `seed.json`, credenciais ou o volume para resolver isso. O cenário de navegador abaixo pressupõe os dados sintéticos intactos, sem edições financeiras manuais. Se suas consultas rápidas atingirem o limite HTTP 429 ao carregar reservas, o cenário respeita o `Retry-After` e usa o botão de recarregar uma vez; pode aguardar até um minuto nessa etapa.

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
