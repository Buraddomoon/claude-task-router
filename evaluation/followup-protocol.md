# Seguimento de engenharia — política v4

O primeiro ensaio real-v1/política v3 está preservado integralmente em
`real-results-v3.json`. Houve 12/12 acertos em cada braço, mas o roteamento
custou mais, levou mais tempo e usou mais tokens no agregado. Não houve
economia observada nesse ensaio.

As tarefas simples com instruções de saída (“retorne somente JSON”, “sem
Markdown”, “sem outras alterações”) foram tratadas como trabalho adicional e
receberam Sonnet. Essa é uma lacuna de classificação para uso diário, além do
efeito de contexto/cache e da tarefa advanced com Opus.

Antes de alterar regras, define-se este seguimento: reconhecer restrições
comuns de apresentação, sem remover ações adicionais nem desativar sinais
de risco. Adicionar regressões adversariais para esses limites. Não alterar
os casos, critérios de qualidade, esforço ou modelo baseline do real-v1.

Executar o mesmo harness uma vez com a política seguinte e guardar outro
relatório, incluindo o original nas comparações. Isso é calibração e regressão
de engenharia no mesmo conjunto conhecido, não avaliação independente nem
evidência de economia geral. Cache/ordem do segundo ensaio podem favorecer
resultados; uma melhora aqui exige validação futura em tarefas reais diferentes
antes de qualquer promessa mais ampla. Se custo/tokens/tempo não melhorarem,
registrar isso sem declarar o objetivo comprovado.

A primeira tentativa v4 foi interrompida após 18 execuções bem-sucedidas:
o sistema devolveu ENOENT ao iniciar o executável nativo para a próxima
chamada. A causa transitória não foi determinada; `claude --version` voltou
a funcionar com a mesma versão 2.1.323. O relatório parcial está preservado
em `real-results-v4-interrupted.json` e não é tratado como ensaio completo.
O harness passou a registrar falhas de spawn como linhas de erro e a parar
sem retry automático. Uma nova execução completa será identificada em outro
arquivo; os custos da tentativa parcial não desaparecem do registro histórico.
