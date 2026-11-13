# Smoke real da instalação pessoal V1.1

13/11/2026, Linux, Python 3.14.3, pacote instalado 1.1.0 em venv gerenciado,
fora do checkout. Claude Code observado no terminal: **2.1.325**. Os smokes
anteriores e o início dos ensaios de eficiência usaram 2.1.323; não se afirma
que o executável nativo permaneceu fixo durante toda a sessão de trabalho.

## Diagnóstico e configuração

`ctr setup --check-models` criou/preservou configuração válida e validou os
nomes com `/model` nativo. `ctr doctor` confirmou interface e login, sem
exportar email ou credenciais. O check de Haiku e o check de um nome inválido
mostraram zero turnos e zero custo reportado. O nome inválido retornou 0 no
Claude, mas foi recusado pelo roteador. `models --probe haiku` respondeu OK,
observou `claude-haiku-5-5`, um turno, estimativa CLI US$ 0,00021113, sem
persistir conversa ou criar tarefa do roteador.

## Terminal e continuidade

Diretório temporário sem código privado, `--tools '' --no-chrome --restricted`.
O diretório foi confirmado no diálogo nativo; não houve bypass de permissões.

1. `ctr run 'Responda somente OK.' --model haiku` identificou tarefa nova,
   criou UUID e respondeu OK. SessionStart confirmou `claude-haiku-5-5`.
2. `/model` abriu o picker. Sonnet foi escolhido com a tecla **s** e confirmação
   nativa, que informou “for this session only”. PostModelSwitch/source=picker
   persistiu escolha sonnet e ID `claude-sonnet-5-5`. Nenhum pedido de inferência
   foi enviado para realizar a troca.
3. Após `/exit`, `ctr run 'Continue. Responda somente OK.'` identificou
   continuação, passou o ID fixado e reutilizou o mesmo UUID. Modo print,
   timeout 60 s e limite de custo explícito; resposta OK, código 0. Como
   SessionStart omitiu o modelo, a transcrição da execução confirmou Sonnet.
4. `ctr` sem prompt abriu esse mesmo UUID e mostrou o histórico. Um rascunho
   foi descartado por Ctrl-C, e Ctrl-C duplo encerrou o cliente com código 0.
   Sem resposta nova nessa execução, o efetivo ficou desconhecido com aviso,
   preservando escolha/ID fixado e sem reutilizar confirmação antiga.

Metadados finais: três lançamentos, mesmo UUID, escolha sonnet, ID fixado
`claude-sonnet-5-5`, código 0 e término preenchido. O lock exclusivo de
instalação foi recusado durante o cliente aberto e adquirido após a saída.
Isso confirma o lease da instalação real, além da regressão que recusa
uninstall mesmo quando o chamador não conhece o estado personalizado da tarefa.

O JSON nativo da retomada incluiu modelUsage de Haiku e Sonnet do histórico:
esse campo pode ser cumulativo e não prova uso novo de ambos os modelos.
A confirmação usa os eventos/transcrição atuais. Os ensaios de eficiência
compararam somente sessões novas para evitar essa confusão.

## Regressão e limites

80 testes locais passaram, incluindo o artefato instalado fora da fonte,
sinais, timeout, migrações, dados privados, setup/backup/restore e remoção.
A CI final deve aprovar Linux/Python 3.11 e 3.14 e macOS Intel/Python 3.14;
o link exato está na descrição da release 1.1.0 após a aprovação.

Não foi realizado login/PTY nativo em macOS neste host. Não foram induzidos
fallbacks de conteúdo reais, auditadas faturas ou garantida qualidade geral
do classificador. Os relatórios de eficiência preservam a piora inicial,
a tentativa interrompida e o seguimento completo com seus limites.
