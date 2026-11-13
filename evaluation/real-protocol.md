# Protocolo de ensaio real — #26

Congelado antes da execução. Objetivo: observar custo estimado, tokens, tempo
e qualidade objetiva em seis microtarefas públicas, comparando Sonnet fixo
com a seleção local do roteador. Não equivale a avaliação de manutenção de
um projeto real, qualidade geral de programação ou fatura da conta.

## Desenho

`real-cases.json`: quatro operações mecânicas, uma função curta e uma análise
de corrida. Rótulos esperados e verificadores são definidos antes do ensaio.
Baseline: Sonnet em todas. Roteado: classificador padrão, sem ajuste posterior
dos prompts, critérios, modelos ou esforço para melhorar os resultados.

Duas repetições por caso, 24 execuções no total. Ordem baseline/roteado alterna
por caso/repetição para reduzir viés de cache/aquecimento, sem afirmar que o
elimina. Cada execução é nova, sem retomada. Há um ensaio separado do ciclo
new/resume para verificar identidade e persistência com o cliente real.

Ambos usam Claude Code público, modo print, saída JSON, ferramentas vazias,
modo restrito e effort=low. O diretório temporário é o mesmo, sem código
privado. A autenticação continua nativa. O braço roteado executa o launcher
real e seus hooks; a saída nativa é capturada apenas pelo harness de teste.
As instruções de formato do teste são idênticas para os dois braços.

## Limites de execução

Opt-in `--real`, teto estimado total padrão US$ 1,00, teto por chamada
US$ 0,05, timeout de 90 s, um turno, sem ferramentas e sem retries automáticos.
Os tetos do CLI podem ser excedidos pelo turno corrente; não são garantia de
faturamento. Antes de cada chamada, o harness verifica orçamento restante;
se o esgotar, para e registra a interrupção. Falhas permanecem no relatório.

## Métricas e qualidade

Guardar somente ID público do caso, braço/repetição, escolha/ID efetivo,
tokens reportados (entrada, cache, saída), duração de parede, custo estimado
do CLI, código de saída, status e qualidade. Não exportar credenciais,
transcrição, diretório privado, resposta livre ou prompts do usuário.
O SHA-256 identifica os casos e a política; registrar versão do CLI/Python.

Qualidade é igualdade estrutural de JSON nos casos determinísticos, tradução
entre duas variantes aceitas, equivalência AST da renomeação e cinco entradas
de teste para a função pages. Código da função é aceito somente em uma linguagem
AST restrita de aritmética/return, sem imports, chamadas, atributos, loops,
decoradores ou acesso a builtins. Não executar código arbitrário produzido
pelo modelo. Testar o verificador contra entradas maliciosas antes do ensaio.

Comparar custo/tokens/tempo brutos e somente pares com qualidade válida nos
dois braços. Não excluir falhas do total gasto. Declarar melhoria observada
apenas se a métrica diminuir, ambas as repetições/casos terminarem e o braço
roteado não perder acertos frente ao baseline. Qualidade geral e economia de
faturamento permanecem não comprovadas; assinatura usa quota e o CLI fornece
estimativas, não a fatura. Redução de preço por modelo não implica redução de
tokens ou tempo. O resultado pode honestamente mostrar piora em uma métrica.
