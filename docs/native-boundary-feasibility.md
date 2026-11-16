# Viabilidade nativa — #38

Este é o relatório da investigação inicial. A conclusão de bloqueio foi
revista após a [prova com supervisor POSIX](native-supervisor-proof.md), que
demonstrou uma alternativa sem setter de modelo no hook. Os eventos e
resultados históricos abaixo continuam válidos.

Executado em 16/11/2026, 12:23–12:24 UTC, Linux x86_64, Python 3.14.3,
Claude Code 2.1.325, PTY real e autenticação existente. A
[ADR 0001](adr/0001-conversation-task-boundaries.md) registra a decisão.
Este é um teste das interfaces, não homologação da feature #32.

## Resultado

Sessão A: `854ed623-b53b-4b57-b01a-4ab0db95e339`.
Sessão B: `c502e0e0-087c-4f6f-bd81-ae28f52ef21e`.
Dados: [eventos e uso sanitizados](../evaluation/native-boundary-feasibility.json).

| UTC | Ação | Evidência |
| --- | --- | --- |
| 12:23:09 | Abrir TUI em Haiku | `SessionStart(startup)`, A, `claude-haiku-5-5` |
| 12:23:18 | Enviar sentinela de bloqueio | `UserPromptSubmit(block)`, aviso nativo, nenhuma resposta |
| 12:23:25 | Enviar pedido inicial | `UserPromptSubmit(initial)` → resposta Haiku → `Stop`, A |
| 12:23:33 | Enviar continuação | `UserPromptSubmit(continuation)` → resposta Haiku → `Stop`, A |
| 12:23:42 | Enviar “Novo assunto” | `UserPromptSubmit(topic_change)` → resposta Haiku → `Stop`, A; sem troca de sessão/modelo |
| 12:23:57–12:24:02 | Picker Sonnet, tecla `s`, confirmar | `PreModelSwitch` → confirmação nativa → `PostModelSwitch`, source `picker`, A |
| 12:24:08 | `/clear` | `SessionEnd(A)` → `SessionStart(clear, B)`; TUI exibe Sonnet |
| 12:24:17 | `/resume A` | `SessionEnd(B)` → `SessionStart(resume, A, Sonnet)`; histórico reaparece |
| 12:24:25 | `/exit` | `SessionEnd(A)`, código 0 |

Um rascunho foi descartado com Ctrl-C antes da saída e não gerou submissão.
O `SessionStart(clear)` omitiu `model`; não se atribui modelo confirmado a
uma resposta de B, que não existiu. Sonnet foi confirmado no evento do picker
e na retomada, sem consumir resposta nesse modelo.

Foram **três respostas curtas em Haiku**, nenhuma ferramenta, nenhuma chamada
para classificação e zero caracteres de instruções de roteamento adicionados
pelo hook. O JSON conserva contagens de tokens informadas pelo cliente;
não houve medição de fatura nem custo em dólares. O limite operacional foi
três submissões que permitem inferência e saída imediata após a inspeção.
`--max-budget-usd` não foi usado: a CLI o restringe ao modo print.

O hook de prova não utiliza `Store`, não grava prompts nem transcrições e
registra somente campos permitidos e nomes de casos sintéticos. Não foi criado
banco do roteador. O histórico nativo permanece sob responsabilidade do Claude.
Não se publicou saída bruta da TUI, credenciais ou conteúdo de transcrições.

## Reprodução

O bloco prepara um diretório temporário privado e imprime o comando. Não
inicia IA. Execute o comando impresso em terminal interativo com conta própria.
O script de hook é o mesmo usado na prova (SHA-256 no JSON de evidência).

```bash
python3 - <<'PY'
from pathlib import Path
import json, shlex, sys, tempfile, uuid
root = Path(tempfile.mkdtemp(prefix='ctr-boundary-'))
(root / 'project').mkdir()
(root / 'probe_hook.py').write_text('''import json, os, sys, time
from pathlib import Path
p=json.load(sys.stdin)
row={k:p[k] for k in ('hook_event_name','session_id','source','model','from_model','to_model','requested_model') if k in p}
row['time_ns']=time.time_ns()
if p.get('hook_event_name')=='UserPromptSubmit':
 text=p.get('prompt','')
 row['case']={'Responda somente OK.':'initial','Continue: responda somente OK.':'continuation','Novo assunto: quanto e 2 + 2? Responda somente 4.':'topic_change','BLOQUEAR_PROVA':'block'}.get(text,'other')
with open(Path(__file__).with_name('events.jsonl'),'a') as out:
 out.write(json.dumps(row)+'\\n')
if row.get('case')=='block':
 print(json.dumps({'decision':'block','reason':'Prova local: prompt bloqueado antes de inferencia.','hookSpecificOutput':{'hookEventName':'UserPromptSubmit','suppressOriginalPrompt':True}}))
''')
command = shlex.join([sys.executable, str(root / 'probe_hook.py')])
events = ('SessionStart', 'UserPromptSubmit', 'PreModelSwitch',
          'PostModelSwitch', 'Stop', 'SessionEnd')
settings = {'hooks': {e: [{'hooks': [{'type': 'command', 'command': command,
                                    'timeout': 5}]}] for e in events},
            'autoMemoryEnabled': False, 'promptSuggestionEnabled': False,
            'switchModelsOnFlag': False}
(root / 'settings.json').write_text(json.dumps(settings))
session = str(uuid.uuid4())
print('cd ' + shlex.quote(str(root / 'project')))
print(shlex.join(['claude', '--model', 'haiku', '--session-id', session,
      '--setting-sources', '', '--settings', str(root / 'settings.json'),
      '--tools', '', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
      '--no-chrome']))
print('# Sessão inicial: ' + session)
print('# Eventos privados: ' + str(root / 'events.jsonl'))
PY
```

No diretório temporário, confirme a confiança nativa e faça a sequência:

1. Envie `BLOQUEAR_PROVA`. Confira o aviso; descarte o texto devolvido à
   entrada com Ctrl-U para não reenviá-lo junto do próximo pedido.
2. Envie `Responda somente OK.` e espere a resposta/`Stop`.
3. Envie `Continue: responda somente OK.` e espere a resposta/`Stop`.
4. Envie `Novo assunto: quanto e 2 + 2? Responda somente 4.` e espere.
5. Abra `/model`, selecione Sonnet e use **`s`** para mudar apenas nesta sessão.
   Confirme o diálogo de troca se aparecer. Enter no picker ou `/model sonnet`
   pode salvar um padrão global, por isso não foi usado.
6. Execute `/clear`, confira o UUID de `SessionStart` e execute `/resume UUID`
   com o identificador inicial. Confira histórico e modelo.
7. Descarte um rascunho com Ctrl-C, depois use `/exit`.

Interrompa se o cliente pedir inferências ou ferramentas fora deste roteiro.
As três mensagens de resposta são a única parte que deve consumir IA.
Compare eventos com a tabela; UUIDs, timestamps e uso variarão.

## Limites

O ensaio não tentou interceptar texto para automatizar `/model` ou `/clear`,
nem enviou setters não documentados. Ele comprova observação/bloqueio e ações
manuais; a análise das saídas públicas fundamenta a lacuna de controle.
Não foram executados o E2E da futura implementação, métricas de detecção,
falhas de uma transição inexistente ou testes nativos macOS. A regressão offline
existente passou: 80 testes, incluindo locks, override, hooks atrasados,
recuperação e privacidade. Isso não satisfaz o aceite de #39/#40.
