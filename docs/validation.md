# Evidências de validação

Validação local em 13/11/2026, Linux, Python 3.14.3 e Claude Code 2.1.323.

## Testes automatizados

`python3 -m unittest discover -s tests -v`: 31 testes passaram. A suíte usa apenas biblioteca padrão e uma CLI simulada, sem inferência. Cobre decisões PT/EN, configuração, prompts inválidos, persistência privada, resolução de IDs, migração de schema, argumentos literais, ausência de classificação/configuração na retomada, mudanças manuais, stdout, saída de erro, projeto original e concorrência real entre processos. SIGTERM é encaminhado ao filho, e o lock só é liberado após ele terminar.

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

## Contrato com o Claude real

Um smoke inicial executou uma chamada curta em modo print e revelou que SessionStart não trouxe o campo opcional `model`. Esse comportamento motivou a subissue #10 e a leitura local limitada do final da transcrição.

Após a correção, uma tarefa classificada como economy executou com Haiku. O ID efetivo `claude-haiku-4-5-20251001` foi registrado automaticamente. `resume` foi executado como um segundo processo, com o mesmo UUID de sessão e esse ID explícito; retornou normalmente e a escolha persistida permaneceu igual. Ambas as execuções tiveram exit code 0. Ferramentas foram desabilitadas para esse smoke.

Foram três chamadas de inferência no total, contando o smoke inicial. Custos reportados pelo próprio CLI: US$ 0,00058249; US$ 0,015428; US$ 0,0020179. Não são uma medição de faturamento da conta. O roteador não fez chamadas para classificar ou resolver o modelo. O smoke real não exercitou a interface `/model`; esse caminho é coberto pelo contrato oficial e pelos testes com PostModelSwitch simulado.

`ctr doctor` confirmou versão e flags de integração. A instalação em venv dedicado e o comando instalado fora do checkout também foram verificados. O workflow do GitHub executa instalação, suíte, benchmark e entrypoint fora do checkout em Linux (Python 3.11/3.14) e macOS (Python 3.14); seu resultado fica nos checks do repositório.

## Issue #13 — escolha e observação

Regressões offline cobrem auto após resolução, substituição já em SessionStart, fontes manuais command/picker/sdk, restauração resume e retomada com o ID compatível original. O fake Claude executa hooks como subprocessos reais e confirma que switchModelsOnFlag=false não acrescenta uma allowlist. A intenção permanece em model, mesmo quando effective_model diverge. O ID fixado fica em resolved_model.

Controle nativo conferido no --help do Claude 2.1.323 e na documentação oficial de [modelos](https://code.claude.com/docs/en/model-config#ask-before-switching) e [PostModelSwitch](https://code.claude.com/docs/en/hooks#postmodelswitch). Não houve chamada de inferência nesta etapa; as substituições são simuladas, sem alegar garantia de estabilidade do provedor.

## Issue #14 — confirmação por execução

Cada lançamento cria execution_id antes de iniciar o subprocesso; o token segue no comando dos hooks e nos eventos observados. A suíte verifica retomada sem hooks após execução confirmada, payload parcial, hook sem token, hook atrasado da execução anterior ou posterior à saída, e SessionStart atrasado após mudança manual. A leitura da transcrição exige hook da execução atual, timestamps dentro da execução e posteriores ao último hook/override; uma comparação atômica inclui execution_id e revisão da escolha para não sobrescrever alterações concorrentes. O ID já fixado permanece disponível sem ser apresentado como confirmação atual.
