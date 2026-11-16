# Supervisão nativa da conversa — #38/#39

Verificado em 16/11/2026, Linux x86_64, Python 3.14.3, Claude Code 2.1.325,
PTY real e autenticação existente. Ferramentas desabilitadas. A
[ADR revisada](adr/0001-conversation-task-boundaries.md) seleciona esta integração.

## Mecanismo demonstrado

Um `UserPromptSubmit` público chama um helper. O helper encaminha o prompt
por socket Unix em diretório 0700, junto da identidade de tarefa/execução e
token efêmero. Não escreve o texto em arquivo. Continuações recebem liberação
silenciosa. Pedidos incertos recebem aviso visível e mantêm tarefa/modelo.

Ao reconhecer `Nova tarefa: ...` ou `New task: ...`, o supervisor mantém o
helper esperando, envia SIGTERM ao processo Claude que iniciou e espera sua
saída. Assim, o prompt não chega à inferência na sessão antiga. Só depois
classifica localmente, cria outra tarefa e inicia a CLI pública com novo UUID,
modelo e o prompt original. O replay inicial do prompt é liberado uma vez,
sem provocar outra fronteira. A TUI reaparece no mesmo terminal.

O banco registra apenas metadados e os vínculos `handoff_to` / `handoff_from`.
A criação e os vínculos são uma única transação. O lock anterior é liberado
antes de executar o novo cliente; o lease da instalação cobre toda a sequência.
Não há proxy, alteração do binário, endpoint privado, teclas automatizadas,
skills de roteamento ou instruções de classificação no contexto.

Se o cliente exigir SIGKILL, houver interrupção ou falha de estado, não se
inicia automaticamente a próxima sessão. Falhas do helper bloqueiam o prompt
e mostram como retomar; não fazem retry remoto. O modo exige Claude 2.1.295+
porque usa o contrato público `onFailure: "block"`.
Fontes: [hooks](https://code.claude.com/docs/en/hooks#block-the-action-when-a-hook-fails),
[CLI](https://code.claude.com/docs/en/cli-reference),
[sessões](https://code.claude.com/docs/en/sessions).
O supervisor POSIX é código do roteador; não é um setter oculto do Claude.

## Evidência observada

[JSON sanitizado](../evaluation/native-supervisor-evidence.json), sem prompts,
conteúdo das respostas, caminhos de transcrição ou credenciais.

| Ensaio | Tarefa anterior | Nova tarefa | Observação |
| --- | --- | --- | --- |
| PT, integração inicial | `a22a9edb-7bcf-45af-a6b6-a341b0f41018`, Haiku | `17d8c0f8-46c9-4b02-96dd-28581b14c6e5`, Sonnet | Prompt digitado na TUI criou a nova tarefa; primeira resposta em Sonnet |
| Picker e continuação | Mesma nova tarefa | Haiku escolhido pelo picker com `s` | Continuação respondeu em Haiku sem criar outra tarefa |
| Retomada da anterior | Mesmo UUID anterior | `--resume` com ID Haiku fixado | Histórico reapareceu; saída sem inferência preservou ID e deixou efetivo desconhecido com aviso |
| EN, fonte final | `9bbbd562-afc2-4743-bb36-b8812e3a395c`, Haiku | `735a6bd6-293e-4173-8f64-942481664e2c`, Sonnet | Fronteira digitada na TUI, resposta única na nova sessão, rascunho descartado e saída 0 |

Os dois estados tiveram `integrity_check=ok` e locks livres após a saída.
O ensaio PT verificou a liberação do lock anterior enquanto a nova tarefa
ainda executava. Foram três respostas no ensaio PT e duas no EN, sem ferramentas
efetivamente executadas. O primeiro pedido PT usava uma edição de README;
sem ferramentas, o modelo produziu texto simulando ferramentas. Isso não
alterou arquivos e não é evidência de qualidade da resposta. O roteiro abaixo
usa apenas constantes para evitar essa distração.

O protótipo anterior à integração encontrou um erro de replay: o prompt
encaminhado tentava abrir outra fronteira. O helper bloqueou antes da resposta.
A liberação única do prompt inicial corrigiu o problema, com regressão para
mensagem idêntica enviada novamente mais tarde. Não se apresenta a primeira
tentativa como teste aprovado.

## Reprodução na versão experimental

Use o checkout `main`, ou reinstale esse checkout. A tag v1.1.0 não contém
esta opção. Prepare estado e projeto temporários próprios e execute:

```bash
python3 -m claude_task_router --state-dir /tmp/ctr-conversation-qa/state \
  new 'Responda somente INICIO.' --model haiku --conversation-routing \
  --cwd /tmp/ctr-conversation-qa/project -- --tools '' --no-chrome
```

Crie os dois diretórios antes. Confirme a confiança apenas no projeto temporário
criado por você. Após INICIO, digite `Nova tarefa: responda somente NOVA.`.
Confira o aviso do roteador, o novo UUID e a nova TUI. Digite
`Continue: responda somente FIM.` e confira que o UUID/modelo se mantêm.
Para verificar override, use `/model`, selecione outro modelo e pressione `s`,
confirme a troca nativa e repita a continuação. Saia com `/exit`.
Use `ctr show UUID` com o mesmo estado para inspecionar vínculos, e
`ctr resume UUID` para recuperar a tarefa anterior. Cada resposta consome IA;
mantenha o ensaio curto. Não há teto em dólares no modo interativo.

## Limites e aceite

O controle de processo foi comprovado. A detecção é conservadora, exige
marcador explícito com dois-pontos e permanece experimental. A
[avaliação congelada](../evaluation/conversation-boundary-protocol.md) registrou
2/8 novas tarefas reconhecidas, nenhum falso positivo de fronteira e seis
falsos negativos. Não atingiu recall de 90%; não se encerra #32/#39/#40.

A suíte final tem 90 testes, incluindo classificação única, replay, override,
falha de helper, criação atômica, erro sem retry, saída forçada e locks.
Ainda faltam o E2E nativo completo de erros/interrupções durante transição,
melhor detecção livre e a homologação macOS #30. A origem dos eventos de prompt
também não permite distinguir todas as mensagens humanas de eventos internos;
agendamentos e retornos de agentes não foram homologados neste modo.
