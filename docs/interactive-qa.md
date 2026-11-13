# Homologação interativa — #20

Executada em 13/11/2026, Linux, Python 3.14.3, Claude Code 2.1.323,
em PTY real, com autenticação existente. Diretório temporário sem código,
ferramentas desabilitadas (`--tools ''`) e `--no-chrome`.
A suíte offline não precisa de autenticação nem executa este roteiro.

## Roteiro reproduzível

Execute em terminal, usando um diretório de projeto temporário e estado isolado:

```bash
mkdir -p /tmp/ctr-interactive-qa/project
ctr --state-dir /tmp/ctr-interactive-qa/state new 'Responda somente OK.' \
  --cwd /tmp/ctr-interactive-qa/project --model haiku -- --tools '' --no-chrome
```

Confirme o diretório temporário no diálogo nativo. Após a resposta, execute
`/model sonnet` e confirme a troca no diálogo. Inspecione `ctr show UUID`
em outro terminal, usando o mesmo `--state-dir`. Saia com `/exit`.
Retome com `ctr --state-dir /tmp/ctr-interactive-qa/state resume UUID -- --tools '' --no-chrome`.
Digite um rascunho, descarte com Ctrl-C e envie apenas `Responda somente OK.`.
Após a resposta, pressione Ctrl-C duas vezes para sair. Retome novamente
sem prompt e use `/exit`. Inspecione metadados, eventos e ausência de processos.

O `/model` é um comando nativo: nesta versão também salva o modelo padrão
do Claude nas configurações do usuário. Registre esse valor antes do ensaio
e restaure-o depois, ou use um perfil de QA autenticado. Não copie credenciais
ou transcrições para o repositório. O launcher sempre passa a escolha explícita
da tarefa, independentemente desse padrão.

## Resultado observado

UUID de sessão: `1b867cdf-01fb-4f8e-95fc-9c4fedb50c65`.

| Etapa (UTC) | Execução | Solicitado / argumento CLI | Observação |
| --- | --- | --- | --- |
| 17:41:14, new | `bfc1f23a-dd72-4a55-8407-4b2d2bd7b8f7` | haiku / haiku | SessionStart: `claude-haiku-5-5`; resposta OK |
| 17:41:42, /model sonnet | mesma execução | sonnet | PostModelSwitch, source=command: `claude-sonnet-5-5`; revisão da escolha=1 |
| 17:42:04, resume | `20add58f-c640-43c4-a669-32801d7bef62` | sonnet / `claude-sonnet-5-5` | Mesmo UUID e histórico; Ctrl-C descartou o rascunho; continuação respondeu OK |
| 17:42:37, saída por Ctrl-C duplo | mesma execução | sonnet | Código 0 nativo; transcrição da execução confirmou `claude-sonnet-5-5` |
| 17:43:50, resume e /exit sem inferência | `794829c1-f0b7-4866-84ed-0c2e86e065ae` | sonnet / `claude-sonnet-5-5` | Mesmo UUID; código 0; efetivo desconhecido com aviso, ID fixado preservado |

O SessionStart das retomadas omitiu `model`. Com resposta nova, a reconciliação
confirmou o modelo; sem resposta nova, não reutilizou a confirmação anterior.
Durante a execução, `ctr model UUID opus` foi recusado com código 2 e
“Tarefa já está em execução”. Após as saídas, o lock foi adquirido novamente,
nenhum processo Claude com esse UUID permaneceu e `PRAGMA integrity_check`
retornou `ok`. Arquivos `.lock` podem permanecer; o lock de kernel é liberado.

Foram duas respostas curtas de inferência (Haiku e Sonnet), sem ferramentas;
nenhuma chamada para classificar. Não foram medidos faturamento nem fallbacks
de conteúdo. A versão nativa exibiu confirmação antes de trocar para Sonnet;
a troca do modelo não produziu uma resposta de inferência.

## Regressão offline

`test_sigint_keeps_lock_until_child_exits_then_allows_resume` envia SIGINT ao
grupo real de processos: o cliente simulado continua após o primeiro sinal,
o launcher mantém o lock, o segundo sinal encerra com 130 e a retomada usa
o mesmo UUID e ID fixado. O caso complementa a saída nativa por Ctrl-C
(que retornou 0 em modo raw) e a regressão de SIGTERM. Os testes existentes
de PostModelSwitch verificam persistência manual sem usar a conta.
