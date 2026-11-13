# Eficiência observada em Claude Code real — #26

13/11/2026, Linux, Python 3.14.3, Claude Code 2.1.323, conta própria com
autenticação nativa. Os relatórios capturaram 2.1.323 no início; o smoke
interativo posterior encontrou 2.1.325. A versão não foi verificada em cada
chamada do ensaio, portanto uma atualização automática durante o trabalho
é mais um fator não controlado. [Protocolo congelado](../evaluation/real-protocol.md),
[casos públicos](../evaluation/real-cases.json) e
[protocolo de seguimento](../evaluation/followup-protocol.md).

Cada ensaio completo tem seis casos, duas repetições e dois braços: 12
execuções Sonnet fixo e 12 roteadas. O esforço foi low, um turno, sem
ferramentas e com modo restrito nos dois braços. Verificadores são estruturais
e o teste da função Python só aceita uma AST aritmética restrita. A avaliação
não executa código arbitrário do modelo nem usa prompts privados.

| Ensaio | Braço | Acertos | Estimativa CLI (US$) | Tempo total (s) | Tokens totais |
| --- | --- | --- | --- | --- | --- |
| Política v3 inicial | Sonnet fixo | 12/12 | 0,01790840 | 31,9449 | 24.968 |
| Política v3 inicial | Roteado | 12/12 | 0,02230266 | 34,1540 | 26.760 |
| Política v4, seguimento | Sonnet fixo | 12/12 | 0,01314380 | 35,0266 | 24.980 |
| Política v4, seguimento | Roteado | 12/12 | 0,00667630 | 30,6489 | 30.068 |

No ensaio inicial, o roteamento ficou **24,54% mais caro**, **6,92% mais lento**
e usou **7,18% mais tokens**. Instruções de apresentação forçavam algumas
tarefas mecânicas para Sonnet. Esse resultado negativo não foi excluído.

A v4 reconhece restrições comuns de formato sem esconder ações ou riscos
adicionais. No seguimento, observou-se **49,21% menos custo estimado** e
**12,50% menos tempo**, porém **20,37% mais tokens**. O classificador não usa
inferência e os hooks não inserem instruções de roteamento no contexto;
isso não implica que modelos diferentes usem a mesma quantidade de tokens.

Relatórios integrais sanitizados: [v3](../evaluation/real-results-v3.json),
[v4 completo](../evaluation/real-results-v4.json) e
[tentativa v4 interrompida](../evaluation/real-results-v4-interrupted.json).
Essa tentativa tem 18 chamadas bem-sucedidas, preservadas, e foi interrompida
por ENOENT ao iniciar o próximo processo nativo. Não foi incorporada como
ensaio completo nem houve retry automático de inferência. A versão do CLI
voltou a responder; a causa transitória não foi determinada. O harness foi
corrigido para registrar também falha de spawn em vez de lançar exceção.
As 66 chamadas concluídas dos três registros somaram US$ 0,07725063 na
estimativa do CLI; isso não é valor confirmado na fatura ou na assinatura.

## O que se pode concluir

Houve melhoria de custo estimado/tempo e preservação dos verificadores nesses
casos, depois de um resultado inicial negativo. **Não foi comprovada redução
de tokens.** Não há evidência suficiente de qualidade em tarefas arbitrárias
de programação, economia percentual garantida ou redução de faturamento.
Na assinatura, o uso afeta quota; os valores do CLI são estimativas API.

Os casos do seguimento já eram conhecidos. Cache, estado de aquecimento,
variabilidade de rede e carga local podem favorecer ou prejudicar tempos e
custos. Não é uma avaliação independente cega, estudo estatístico ou benchmark
isolado de CPU. A ordem alternada reduz alguns vieses sem eliminá-los.
Novas regras futuras exigem outro conjunto reservado para alegar generalização.

## Reproduzir sem surpresa de consumo

```bash
python3 evaluation/real.py
# Somente com intenção explícita de consumir IA:
python3 evaluation/real.py --real --output /caminho/novo-relatorio.json
```

O padrão só imprime o plano. A execução real exige arquivo novo, limita
orçamento estimado e tempo, mantém falhas e para se não puder medir custo.
Não é executada automaticamente pela CI. Para trabalho onde qualidade tenha
prioridade sobre economia, configure `ctr setup --force --min-tier balanced`
ou faça override. Não é necessário classificar novamente cada continuação.
