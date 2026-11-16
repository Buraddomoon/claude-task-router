# Avaliação prospectiva de eficiência — #31

Estado em 16/11/2026: **economia geral e redução de tokens não comprovadas**.
O usuário autorizou apenas testes simples com baixo gasto. A coorte de
tarefas reais não foi executada; não há revisão humana dessa coorte.

| Etapa | Entrega | Aceite restante |
| --- | --- | --- |
| #35 | Desenho e rubrica congelados em `c255d61`; smoke de baixo custo em `a8442bc`; ferramenta para congelar manifesto | Selecionar/autorizar oito tarefas reais em dois projetos e congelar seus hashes antes dos ensaios |
| #36 | Instrumentação, regressões offline e smoke nativo new/resume | Entregue; não implica validação da economia em projetos reais |
| #37 | Ferramenta de execução/relatório e reanálise dos dados históricos | Coorte real, testes dos projetos e revisão humana; permanecem pendentes |

A #31 permanece aberta. Não substituir os aceites por microtarefas nem
marcar economia como comprovada por um teste de instrumentação aprovado.

## Evidência nativa de instrumentação

Código do ensaio: commit `a63a92b`. Relatório sanitizado:
[`accounting-smoke-v1.json`](../evaluation/accounting-smoke-v1.json).
Linux, Python 3.14.3, Claude Code 2.1.325, modelo claude-sonnet-5-5.
Versão e SHA-256 do executável iguais antes/depois das duas chamadas.
Nenhuma chamada adicional foi feita após esse ensaio.

| Turno | Classificações | Tokens marginais | Estimativa CLI marginal (US$) | Estimativa acumulada (US$) | Parede (s) |
| --- | --- | --- | --- | --- | --- |
| new | 1 | 1.993 | 0,0054609 | 0,0054609 | 2,8151 |
| resume | 0 | 2.042 | 0,0017764 | 0,0072373 | 2,0994 |
| Total | 1 | 4.035 | **0,0072373** | 0,0072373 | 4,9145 |

Somar os dois custos acumulados produziria US$ 0,0126982: duplicaria o
gasto do primeiro turno. Somar os tokens cumulativos produziria 6.028 em
vez de 4.035. A instrumentação subtrai os contadores anteriores da mesma
sessão, por modelo, e usa somente os deltas para o total. Modelos presentes
apenas no histórico não são tratados como modelos ativos na continuação.

O UUID foi confirmado no estado persistido em ambos os turnos. A resposta
curta passou na igualdade funcional nas duas chamadas. O classificador levou
0,0335 ms no new; o overhead local observado foi 6,35 ms no new e 5,01 ms
no resume. Essas durações locais excluem o subprocesso nativo e a inicialização
do interpretador do observador. O tempo de parede inclui o processo completo;
verificações de proveniência e testes de aceitação ficam fora dele.
Não se trata de comparação de modelos ou de economia de continuação: cache
e quantidade de trabalho diferem entre os turnos.

Os campos `total_cost_usd` e `modelUsage` são cumulativos na retomada. O campo
`usage` tem escopo diferente e pode excluir subagentes. Por isso os totais
novos usam deltas de `modelUsage`, preservando cache escrito/lido e saída.
A estimativa é calculada pelo cliente e não representa fatura ou quota.
Fonte primária: [documentação de custo do Claude Code](https://code.claude.com/docs/en/agent-sdk/cost-tracking).
Fatura API e quota permanecem `null`/não verificadas; não foram consultados
endpoints privados.

## Usar sem consumir inferência

```bash
python3 evaluation/real.py --prospective
python3 evaluation/real.py --smoke
python3 -m unittest discover -s tests -v
```

Ambos os planos são offline. A CI executa somente planos e testes com
fixtures, nunca o ensaio nativo real. O relatório histórico continua
preservado; `python3 evaluation/real.py` ainda planeja as microtarefas antigas.
Os relatórios novos não sobrescrevem os antigos. O novo formato histórico
é identificado como `real-v2`, com proveniência por chamada e uso de
`modelUsage`; os arquivos anteriores `real-v1` permanecem intactos.

O smoke real exige opt-in e teto explícito; a execução autorizada nesta
entrega já terminou e não precisa ser repetida:

```bash
python3 evaluation/real.py --smoke --real --max-cost-usd 0.05 \
  --output /diretorio/novo-smoke.json
```

O teto nativo pode ser excedido pelo turno corrente. O harness registra o
excesso e para. Falhas de spawn/timeout/interrupção são tentativas com
consumo desconhecido até existir medição, nunca chamadas gratuitas.

## Preparar uma coorte futura

O [protocolo congelado](../evaluation/prospective-protocol.md) define todos
os limites. **Os US$ 8,00 dessa coorte não foram autorizados nesta sessão.**
Manifesto e prompts ficam fora deste repositório, com permissões 0600.
Exemplo estrutural de uma entrada no manifesto privado:

```json
{
  "authorized": true,
  "not_used_for_calibration": true,
  "tasks": [{
    "id": "T01",
    "category": "fix",
    "project": "/projeto/autorizado",
    "commit": "SHA_COMPLETO_DO_HEAD_LIMPO",
    "prompts": ["/privado/inicial.txt", "/privado/continuacao.txt"],
    "acceptance": [["python3", "check_initial.py"], ["python3", "check_final.py"]]
  }]
}
```

O manifesto completo exige oito tarefas, duas por categoria, em pelo menos
dois projetos. O exemplo não é uma amostra válida. Os comandos são executados
sem shell e só em snapshots isolados; projetos originais ficam preservados.
Os snapshots são mantidos no diretório privado para revisão humana. O cliente
continua responsável pela autenticação, permissões e transcrição nativa.
O harness não copia prompts, respostas ou transcrições para o relatório.

```bash
# Valida e congela, sem chamadas de IA:
python3 evaluation/real.py --prospective --manifest /privado/manifest.json \
  --freeze --lock /privado/coorte-lock.json
```

O lock exporta somente IDs/hashes/metadados e vincula protocolo, manifesto,
prompts, comandos de aceitação, commits e fontes do harness/roteador.
Alterar qualquer item invalida o lock. A checagem de sobreposição por hash
cobre os corpora públicos; similaridade semântica e casos privados exigem a
declaração do responsável. Antes de executar futuramente, obter autorização
para os projetos, comandos e teto congelado; usar `--real`, `--max-cost-usd 8`,
`--output` novo e `--work-dir` novo fora deste repositório. Não há retry
automático. Todos os braços e falhas ficam no mesmo relatório de tentativas.

## Revisão humana e decisão

O resultado sem revisão humana é inconclusivo. O avaliador humano inspeciona
os snapshots e a conversa nativa local, seguindo a rubrica, sem conhecer o
braço se possível. Salva um arquivo privado ligado ao SHA-256 exato do relatório:

```json
{
  "report_sha256": "SHA256_DOS_BYTES_DO_RELATORIO",
  "reviewed_by_human": true,
  "records": {
    "T01:1:baseline:1": {"verdict": "pass", "critical_regression": false}
  }
}
```

São necessárias as 32 entradas; `pending`, ausência de revisão ou regressão
crítica impedem uma conclusão favorável. Não preencher essa declaração
automaticamente com a avaliação do agente. Recalcular sem inferência:

```bash
python3 evaluation/real.py --prospective --report /privado/resultado.json \
  --reviews /privado/revisao-humana.json --output /privado/conclusao-nova.json
```

O relatório mostra totais conhecidos (inclusive falhas), completude,
subtotais new/resume, métricas separadas e conclusão da amostra. Valores
ausentes não viram zero. Uma redução observada na amostra nunca altera
`general_savings_proven=false` nem comprova economia na fatura/quota.
