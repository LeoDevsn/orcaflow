# OrçaFlow

**Do contato à conquista.** Um aplicativo desktop para autônomos e pequenos negócios acompanharem clientes, criarem orçamentos e lembrarem do próximo contato. Funciona localmente, sem cadastro, mensalidade ou chave de API.

**[Baixar para Windows](https://github.com/LeoDevsn/orcaflow/releases/latest)** · [Reportar um problema](https://github.com/LeoDevsn/orcaflow/issues)

## Começar em cinco minutos

1. Baixe e abra **OrcaFlow.exe**. Não precisa instalar Python nem executar como administrador.
2. Clique em **Experimentar demo** para explorar clientes e propostas fictícios. **Voltar aos meus dados** retorna à sua base, que continua separada.
3. Em **Meu negócio**, configure o nome e os contatos que devem aparecer nas propostas.
4. Cadastre um cliente e crie um orçamento. Adicione descrição, quantidade e preço de cada item; confira o desconto e salve o rascunho.
5. Exporte a proposta. Ela abre no navegador para imprimir ou salvar como PDF pelo diálogo de impressão.
6. Depois de enviar a proposta por sua conta, marque a etapa como **Enviado**. A agenda cria automaticamente um retorno para daqui a três dias.

Aplicativo portátil para Windows 10/11 x64. O executável não possui assinatura digital; a versão inclui `SHA256SUMS.txt` para verificar o download.

## Um fluxo completo

| Área | O que faz |
| --- | --- |
| Visão geral | Clientes cadastrados, valor em negociação, propostas aprovadas, etapas e tarefas atrasadas. |
| Clientes | Cadastro, edição, busca e importação CSV com deduplicação por e-mail. |
| Orçamentos | Itens, quantidades fracionadas, desconto, validade, condições e histórico de etapas. |
| Propostas | Documento HTML para impressão, com cabeçalho do negócio e dados do cliente preservados no orçamento. |
| Agenda | Tarefas manuais e retornos criados automaticamente ao mudar a etapa. |
| Meu negócio | Perfil, exportação CSV, backup e restauração com cópia de segurança da base anterior. |

### Automação de retorno

- **Enviado:** cria um lembrete para daqui a 3 dias corridos.
- **Negociação:** cria ou atualiza o lembrete aberto para daqui a 2 dias corridos.
- **Aprovado, Recusado ou Arquivado:** encerra os retornos automáticos abertos dessa proposta. Tarefas manuais são mantidas.
- **Copiar mensagem:** prepara um texto com nome, número da proposta e valor. Você revisa, cola e envia pelo canal que preferir.

A agenda é salva no banco; tarefas atrasadas aparecem ao reabrir. Não há notificações do sistema nem envio automático de e-mails ou mensagens. A tela inicial atualiza os indicadores a cada minuto enquanto estiver aberta.

### Integridade das propostas

Valores são armazenados em **centavos inteiros**, com quantidades em milésimos e arredondamento decimal por item. Exemplos aceitos: `1.250,50` e `1250.50` para valores; `1,5` ou `1.5` para quantidades. Use vírgula ao informar separador brasileiro de milhar: `1.250` sozinho é rejeitado por ser ambíguo; informe `1250` ou `1.250,00` para mil duzentos e cinquenta reais.

Propostas fora de **Rascunho** não podem ser editadas nem voltar a rascunho. Use **Duplicar** para criar uma nova versão. Os dados do cliente são copiados para o orçamento: editar o cadastro não altera propostas anteriores. Ao editar um rascunho, o cliente e os dados atuais são usados na nova gravação. O cabeçalho do negócio reflete o perfil atual na exportação.

O valor de **Aprovados** é o total de orçamentos nessa etapa; **não é receita recebida**. Não existe controle de pagamentos, emissão de nota fiscal ou assinatura digital de contratos. Propostas exportadas são documentos comerciais sem valor fiscal.

### Importação de clientes

CSV UTF-8 (com ou sem BOM), com vírgula ou ponto e vírgula. Use os cabeçalhos abaixo; somente `nome` é obrigatório. Um e-mail já cadastrado é ignorado. Linhas sem e-mail são sempre adicionadas, por isso não são deduplicadas.

```csv
nome;empresa;email;telefone;observacoes
Cliente Exemplo;Empresa Exemplo;cliente@example.com;(00) 00000-0000;Contato fictício
```

Até 10.000 linhas por importação. Se houver uma linha inválida, a importação inteira é cancelada sem cadastros parciais. Há um arquivo de exemplo em `examples/clientes.csv`.

### Backup e privacidade

O banco fica em `%LOCALAPPDATA%\OrcaFlow\orcaflow.sqlite3`. O aplicativo não envia seus dados à internet. Propostas, CSVs e backups contêm os dados que você cadastrou: escolha onde guardar e com quem compartilhar.

Em **Meu negócio**, use **Criar backup** para gerar uma cópia consistente do banco SQLite. Para recuperar, use **Restaurar backup**. A restauração valida a versão, a integridade e a estrutura do arquivo e preserva a base anterior em `antes-restauracao-<id>.sqlite3` dentro da pasta de dados. Arquivos exportados e backups não sobrescrevem arquivos existentes; escolha um nome novo.

Não há nuvem, contas, colaboração entre computadores ou criptografia do banco. Use em uma estação de trabalho por vez. Mantenha backups em outro local; perder o computador e a única cópia do banco implica perder os dados.

## Desenvolver e executar pelo código

Python 3.12+ com Tkinter, sem dependências externas para executar o aplicativo.

```powershell
python -m orca_flow
python -m orca_flow --demo
python -m orca_flow --data-dir ".dados-teste" --stats
python -X utf8 -m unittest discover -s tests -v
```

`iniciar.pyw` abre a interface no Windows com dois cliques quando associado ao Python.

Instalação opcional de terminal:

```powershell
python -m pip install .
orcaflow --help
```

Build portátil para Windows:

```powershell
python -m pip install pyinstaller==6.22.3
python scripts/build_windows.py
python scripts/package_release.py
```

O executável e seu hash ficam em `dist/`. O ZIP de código-fonte exclui bases locais, caches, builds e arquivos de testes gerados. Testes e build também estão configurados no GitHub Actions.

## Arquitetura e validação

```text
orca_flow/
  core.py        Regras de negócio, cálculo decimal, SQLite, CSV, propostas e backups
  gui.py         Interface Tkinter, formulários, painel e agenda
  __main__.py    Inicialização e consulta de indicadores em terminal
tests/           Testes reais em bases e arquivos temporários
scripts/         Build de executável e pacote de código-fonte
examples/        CSV fictício para experimentar importação
```

SQLite usa chaves estrangeiras, restrição de e-mails únicos e índice parcial para impedir retornos automáticos abertos duplicados. Importação e gravação de propostas usam transações. A restauração usa a API de backup do SQLite, preservando uma cópia anterior.

Os testes verificam cálculo decimal, arredondamento por item, snapshots de clientes, propostas imutáveis, duplicação, lembretes, importação atômica, backup/restauração, CSV e escape de texto no HTML. A aplicação não usa IA nesta versão e não há alegação de adoção por clientes externos.

Licença MIT · Leonardo Santos
