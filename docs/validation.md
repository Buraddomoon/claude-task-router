# Evidências de validação

Homologação posterior de `/model`, PTY, Ctrl-C e retomada: [issue #20](interactive-qa.md).
As descrições dos smokes anteriores abaixo mantêm seus limites históricos.

## Conferência V1.0

A suíte final contém 59 testes e passou localmente em Linux/Python 3.14.3.
Inclui SIGINT real em grupo de processos, corpus congelado, classificação
local nos limites e os ensaios de instalação/atualização/rollback. Os
[testes do artefato instalado](installation.md) exercitam o pacote fora da
árvore fonte, recusando importação acidental do checkout. A CI #21 passou
em Linux/Python 3.11 e 3.14 e macOS Intel/Python 3.14 no commit ea0f343
([execução](https://github.com/Buraddomoon/claude-task-router/actions/runs/43476570467)).

O [protocolo de avaliação](classifier-evaluation.md) registrou baseline de
17/28 no desenvolvimento e resultado reservado de 28/28 após congelar as
regras. p95 local reservado: 0,0262 ms típico e 18,6683 ms na entrada máxima
de 256 KiB. São métricas de política sintética, não qualidade de respostas
ou faturamento. O benchmark de 24 exemplos continua sendo regressão da
política, com zero divergência após atualizar o caso de renomeação mecânica.

A [conferência final](final-audit.md) mapeia requisitos a código e testes.
O instalador também atualizou a instalação local de 0.1.0 para 1.0.0,
preservando o venv legado para rollback. O entrypoint retornou 1.0.0;
`doctor` aprovou Claude 2.1.323 e o smoke offline fora do checkout confirmou
importação de site-packages e três chamadas simuladas de new/model/resume.
A descrição da release v1.0.0 registra o SHA e a CI aprovados do commit
final, além dos checksums do wheel efetivamente distribuído.

Validação local em 13/11/2026, Linux, Python 3.14.3 e Claude Code 2.1.323.

## Testes automatizados

`python3 -m unittest discover -s tests -v`: 50 testes passaram após #12 (31 na V0.1). A suíte usa apenas biblioteca padrão e uma CLI simulada, sem inferência. Cobre decisões PT/EN, configuração, prompts inválidos, persistência privada, resolução de IDs, migração de schema, argumentos literais, ausência de classificação/configuração na retomada, mudanças manuais, stdout, saída de erro, projeto original e concorrência real entre processos. SIGTERM é encaminhado ao filho, e o lock só é liberado após ele terminar.

Os hooks são exercitados como subprocessos reais, inclusive a partir de diretórios com espaços e apóstrofo. Payloads inválidos e sessões não gerenciadas não injetam saída. A recuperação do modelo não aceita respostas de outra sessão, respostas antigas nem caminhos externos à árvore de transcrições do Claude. Um evento manual observado tem prioridade.

## Benchmark local

`python3 benchmarks/run.py`: 24 exemplos sintéticos, 2.400 classificações, nenhuma divergência da política especificada.

| Medida | Resultado nesta máquina |
| --- | --- |
| Classificação, mediana | 0,0114 ms |
| Classificação, p95 | 0,0155 ms |
| Inicialização completa de `classify`, mediana de 5 processos | 47,72 ms |
| Chamadas de IA do roteador por decisão | 0 |
| Tokens de instruções de roteamento injetados no contexto | 0 |

Esses exemplos verificam a política implementada, não constituem um dataset independente de dificuldade. Os números não demonstram qualidade de resposta, redução de tokens da tarefa ou economia de faturamento; variam com a máquina.

## Contrato com o Claude real — smoke original V0.1

Um smoke inicial executou uma chamada curta em modo print e revelou que SessionStart não trouxe o campo opcional `model`. Esse comportamento motivou a subissue #10 e a leitura local limitada do final da transcrição.

Após a correção, uma tarefa classificada como economy executou com Haiku. O ID efetivo `claude-haiku-4-5-20251001` foi registrado automaticamente. `resume` foi executado como um segundo processo, com o mesmo UUID de sessão e esse ID explícito; retornou normalmente e a escolha persistida permaneceu igual. Ambas as execuções tiveram exit code 0. Ferramentas foram desabilitadas para esse smoke.

Foram três chamadas de inferência no total, contando o smoke inicial. Custos reportados pelo próprio CLI: US$ 0,00058249; US$ 0,015428; US$ 0,0020179. Não são uma medição de faturamento da conta. O roteador não fez chamadas para classificar ou resolver o modelo. O smoke real não exercitou a interface `/model`; esse caminho é coberto pelo contrato oficial e pelos testes com PostModelSwitch simulado.

`ctr doctor` confirmou versão e flags de integração. A instalação em venv dedicado e o comando instalado fora do checkout também foram verificados. O workflow do GitHub executa instalação, suíte, benchmark e entrypoint fora do checkout em Linux (Python 3.11/3.14) e macOS (Python 3.14); seu resultado fica nos checks do repositório.

## Issue #13 — escolha e observação

Regressões offline cobrem auto após resolução, substituição já em SessionStart, fontes manuais command/picker/sdk, restauração resume e retomada com o ID compatível original. O fake Claude executa hooks como subprocessos reais e confirma que switchModelsOnFlag=false não acrescenta uma allowlist. A intenção permanece em model, mesmo quando effective_model diverge. O ID fixado fica em resolved_model.

Controle nativo conferido no --help do Claude 2.1.323 e na documentação oficial de [modelos](https://code.claude.com/docs/en/model-config#ask-before-switching) e [PostModelSwitch](https://code.claude.com/docs/en/hooks#postmodelswitch). Não houve chamada de inferência nesta etapa; as substituições são simuladas, sem alegar garantia de estabilidade do provedor.

## Issue #14 — confirmação por execução

Cada lançamento cria execution_id antes de iniciar o subprocesso; o token segue no comando dos hooks e nos eventos observados. A suíte verifica retomada sem hooks após execução confirmada, payload parcial, hook sem token, hook atrasado da execução anterior ou posterior à saída, e SessionStart atrasado após mudança manual. A leitura da transcrição exige hook da execução atual, timestamps dentro da execução e posteriores ao último hook/override; uma comparação atômica inclui execution_id e revisão da escolha para não sobrescrever alterações concorrentes. O ID já fixado permanece disponível sem ser apresentado como confirmação atual.

## Issue #15 — recuperação e migrações

A suíte cobre falha antes de salvar sessão, sessão excluída, diretório removido, falha em Popen e recuperação explícita sem classificação/configuração nova. Verifica modelo/ID compatível, integridade, vínculo de origem, isolamento da tarefa original, ausência do prompt no banco e ausência de retry. A recuperação também respeita o lock de tarefas em execução. SIGTERM preserva código 143 e só libera o lock após o filho terminar.

Migrações v1/v2 recuperam a escolha manual, incluindo fallback automático da mesma família sem substituir o ID original. A migração v3 mantém escolha e ID fixado e limpa confirmação antiga. Inicialização nova e migrações v1/v2 são disputadas por seis processos reais, preservando todas as tarefas e eventos. integrity_check=ok e foreign_key_check vazio. Uma falha induzida no meio da migração reverte DDL e dados; a execução seguinte migra normalmente. Versão futura não é rebaixada.

Regressões adicionais forçam alterações entre leitura e gravação da reconciliação: nova execução, troca manual que volta ao mesmo modelo e hook parcial. O compare-and-set rejeita as três condições.

### Smoke real após #12

Claude Code 2.1.323, Linux, 13/11/2026, ferramentas desabilitadas e limite explícito de US$ 0,03 por chamada. Uma tarefa criada apenas no banco foi retomada no CLI real: sessão inexistente retornou código 1, metadados preservados e instrução ctr recover, sem repetição automática. recover abriu um UUID substituto, mantendo a escolha haiku, e a resposta confirmou claude-haiku-5-5. Uma retomada subsequente usou esse ID e o mesmo UUID substituto, com novo execution_id e confirmação atual. Recuperação e retomada retornaram código 0 e resposta OK. Duas chamadas de inferência, custos reportados pelo CLI de US$ 0,00058129 e US$ 0,00070073; não são faturamento da conta. Nenhuma chamada para classificar.

Não foram induzidos fallbacks de conteúdo reais nem mudança interativa pelo picker neste smoke; esses caminhos têm regressões simuladas e a homologação interativa continua em #20.

### Execução da CI

A execução 43465530134 passou em Linux/Python 3.11 e 3.14, mas o job macos-latest foi cancelado antes de obter runner. As anotações do GitHub apontaram falta de capacidade nos runners macOS arm64, sem executar qualquer step. A matriz passou a usar macos-15-intel, label x64 oficial do [catálogo de runners](https://github.com/actions/runner-images), para concluir a validação macOS com Python 3.14.
