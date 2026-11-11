# OrçaFlow

Clientes, orçamentos e próximos contatos em um espaço de trabalho no navegador, conectado a um servidor próprio. Interface em português para autônomos e pequenos negócios cuidarem da parte comercial sem terminal ou planilhas paralelas.

**[Baixar para Windows](https://github.com/LeoDevsn/orcaflow/releases/latest)** · [Instalar no servidor](SERVER.md) · [Verificação e limites](QA.md) · [Reportar problema](https://github.com/LeoDevsn/orcaflow/issues)

## Comece pelo aplicativo

1. Abra **OrcaFlow.exe**. Ele inicia o servidor neste computador e abre uma aba no navegador. Não precisa instalar Python ou Node.
2. Na primeira visita, informe seu nome e crie uma senha para proteger o espaço de trabalho.
3. Configure o nome do negócio, cadastre um cliente e clique em **Novo orçamento**.
4. Descreva os serviços, confira o resumo e salve o rascunho.
5. Use **Compartilhar proposta** para gerar o link do portal do cliente, ou baixe o orçamento para enviar por sua conta. Gerar o link preserva o rascunho como **Enviado**.
6. Acompanhe o próximo contato em **Agenda**. Para terminar, use **Encerrar aplicativo** na janela de controle.

Na tela de entrada, **Experimentar com dados de exemplo** abre uma demonstração separada dos dados reais e diferente em cada sessão do navegador.

Executável portátil para Windows 10/11 x64, sem assinatura digital. A versão inclui `SHA256SUMS.txt` para conferir a integridade. Requer navegador moderno.

## Uma interface nova

A versão 2 substitui a barra lateral escura e os blocos de métricas por navegação no topo, listas de trabalho e um editor de orçamento com resumo ao lado. Estados vazios explicam o próximo passo. Datas usam os controles do navegador e erros de gravação preservam os campos preenchidos.

A direção foi trabalhada com Impeccable e registrada em [DESIGN.md](DESIGN.md). O fluxo foi testado com DOM simulado e API HTTP real. **A revisão visual em navegadores reais e celulares permanece pendente**, porque o controle do navegador não estava disponível. Não se afirma conformidade WCAG ou aprovação visual sem essa checagem. Veja [QA.md](QA.md).

## O trabalho que ele organiza

| Área | Uso |
| --- | --- |
| Hoje | Próximos contatos, propostas recentes e resumo comercial. |
| Clientes | Cadastro, busca, edição e importação CSV. |
| Orçamentos | Itens, quantidade, preço, desconto, validade, condições e histórico. |
| Agenda | Tarefas manuais e retornos agendados pelas etapas. |
| Meu negócio | Cabeçalho, senha, exportação e backup/restauração. |

**Enviado** agenda um retorno para daqui a 3 dias corridos. **Negociação** cria ou atualiza o retorno para daqui a 2 dias. **Aprovado, Recusado e Arquivado** encerram os retornos automáticos abertos; tarefas manuais são mantidas.

**Copiar texto de retorno** prepara uma mensagem com cliente, número e valor para você revisar e enviar. O aplicativo não envia mensagens automaticamente.

## Propostas e valores

O servidor calcula em centavos inteiros e quantidades em milésimos, com arredondamento decimal por item. Valores aceitos: `1250`, `1.250,50` e `1250.50`. O valor `1.250` é recusado por ser ambíguo; informe `1250` ou `1.250,00` para mil duzentos e cinquenta reais.

Somente rascunhos podem ser editados. Use **Duplicar proposta** para criar uma nova versão de uma proposta enviada. Os dados do cliente são copiados para o orçamento: editar o cadastro não muda propostas anteriores. O cabeçalho usa o perfil atual ao exportar.

A proposta é HTML para impressão. Abra o arquivo baixado e use **Imprimir → Salvar como PDF** no navegador. Não há geração direta de PDF, emissão fiscal ou controle de pagamentos. Orçamentos aprovados **não representam dinheiro recebido**.

Importações aceitam CSV UTF-8 com `nome;empresa;email;telefone;observacoes`; somente `nome` é obrigatório. E-mails já existentes são ignorados, e uma linha inválida cancela toda a importação. Há um exemplo em `examples/clientes.csv`.

## Dados e backups

Os dados comerciais continuam em `%LOCALAPPDATA%\OrcaFlow\orcaflow.sqlite3`. A versão 2 mantém a base da versão 1 e cria somente o acesso por senha, sem apagar clientes ou propostas.

Em **Meu negócio**, baixe backups e guarde uma cópia em outro local. Restaurar substitui os dados comerciais e preserva uma cópia anterior. Depois, **Baixar cópia anterior** permite recuperar essa cópia pela interface. A senha não muda ao restaurar.

Não há conta em nuvem do OrçaFlow. Uma conta de gestão compartilha o mesmo espaço; não há papéis de funcionário ou multiempresa. O banco comercial não tem criptografia em repouso. Quando o proprietário habilita recebimentos, o checkout e a verificação do pagamento usam a API do Mercado Pago.

## Portal, conversa e pagamentos

Em cada proposta, **Compartilhar proposta** gera um link reservado. Copie no momento da criação; o token completo não fica guardado no banco. Gerar outro link encerra o anterior. É possível encerrar o acesso pela gestão. O acesso dura 90 dias; o prazo para aceitar continua sendo a validade comercial indicada na proposta.

Quem tem o link consulta uma versão fixa, informa o nome e aprova, recusa ou pede ajustes. Uma resposta não pode ser substituída pela mesma versão. Aprovar muda a negociação para Aprovado, sem afirmar que houve pagamento. Pedir ajustes muda para Negociação e cria uma tarefa. Para alterar preço ou escopo, duplique e prepare uma nova versão.

A conversa permite mensagens e pedidos de alteração, com histórico e tarefas concluídas pelo proprietário. Mensagens novas aparecem na gestão. Não há envio automático de e-mail, WhatsApp ou notificações externas. O link identifica a proposta; o nome informado não equivale a identidade verificada ou assinatura digital.

**Recebimentos começam sem conta cadastrada.** Em **Meu negócio**, o proprietário pode cadastrar o endereço público HTTPS, Access Token e assinatura dos Webhooks do Mercado Pago. Os campos de credenciais não são devolvidos ao navegador e ficam cifrados em arquivos separados da base comercial. Comece pelo ambiente de teste e homologue a integração com sua conta antes de habilitar produção.

Ao habilitar, o cliente pode pagar o **valor integral** da proposta aprovada por Pix ou cartão no checkout hospedado. Os meios disponíveis dependem da conta e das condições do provedor. O OrçaFlow não coleta dados de cartão. Uma tela de retorno ou confirmação do cliente nunca marca o pagamento como recebido: a confirmação consulta o provedor, confere assinatura, conta, moeda, valor e ambiente. Estornos e contestações atualizam o status; múltiplos pagamentos são sinalizados para conferência, sem estorno automático pelo aplicativo.

Credenciais de recebimentos e configuração de HTTPS não são fornecidas nesta distribuição. Os testes do provedor usam respostas simuladas, sem cobranças reais; a homologação com a conta do proprietário permanece necessária. Instruções em [SERVER.md](SERVER.md).

## Prestador, CPF/CNPJ e nota fiscal

O perfil aceita pessoa física (nome e CPF) ou empresa (razão social e CNPJ), além de nome comercial, telefone e e-mail. CPF e CNPJ têm validação de formato e dígitos; CNPJ alfanumérico também é aceito. Isso não consulta a situação cadastral nem habilita emissão fiscal. O proprietário escolhe como mostrar o documento nas propostas: CNPJ completo e CPF mascarado, ou documento completo.

O cliente pode informar nome/razão social, CPF/CNPJ, e-mail e endereço para emissão. Esses dados completos aparecem somente na gestão; o documento é mascarado na página do cliente. O proprietário emite a nota no emissor fiscal autorizado e anexa o PDF/XML já emitido. O cliente baixa pela proposta. Os documentos entram no backup comercial.

**Não existe emissão automática de NFS-e nesta versão.** Ela exige integração e cadastro fiscal compatíveis com a situação do prestador. O OrçaFlow não transforma um comprovante de Pix/cartão em nota fiscal e não valida a autenticidade fiscal dos arquivos anexados. Cadastro no aplicativo não substitui habilitação no emissor. Referências: [NFS-e oficial](https://www.gov.br/pt-br/servicos/emitir-nota-fiscal-de-servico-eletronica), [CNPJ alfanumérico](https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/acoes-e-programas/programas-e-atividades/cnpj-alfanumerico).

## Cliente e servidor

O cliente é HTML/CSS/JavaScript. O backend é Flask servido por Waitress; SQLite guarda os dados. O executável reúne tudo para uso local. Para outros computadores, há modo sem interface gráfica, configuração de hosts e HTTPS e modelos Docker/Compose em [SERVER.md](SERVER.md).

Não foi criada hospedagem pública. Rede exige servidor, domínio e proxy HTTPS configurados pelo responsável técnico. Os modelos Docker são fornecidos, mas a imagem não foi construída nem testada nesta estação.

## Desenvolver

Python 3.12+:

```text
python -m pip install .
python -m orca_flow
python -m orca_flow --demo
python -m orca_flow --server --port 7460
python -X utf8 -m unittest discover -s tests -v
```

O front não precisa de build ou dependências Node para executar. Node serve somente ao teste de integração:

```text
npm ci
npm test
```

Executável em Windows:

```text
python -m pip install pyinstaller==6.22.3
python scripts/build_windows.py
python scripts/package_release.py
```

`dist/` recebe executável, hash e código-fonte sem bases locais, credenciais, caches ou node_modules. A interface antiga existe para compatibilidade via `python -m orca_flow --legacy`; o padrão é o novo front web.

## Estrutura

```text
orca_flow/
  core.py       Negócio e banco comercial existente
  web.py        API, autenticação, sessões e downloads
  server.py     Servidor WSGI e janela de controle
  portal.py     Links reservados, respostas e versões compartilhadas
  payments.py   Configuração cifrada, checkout e confirmação do provedor
  documents.py  Conversa, pedidos, identificação e documentos fiscais
  frontend/     HTML, CSS, JavaScript e fontes locais
tests/          Negócio, API e front com HTTP real
SERVER.md       Instalação e operação do servidor
DESIGN.md       Direção e decisões visuais
QA.md           Verificações executadas e pendentes
```

Não usa IA nem alega adoção por clientes externos. Licença MIT · Leonardo Santos. Public Sans usa SIL Open Font License, incluída em `orca_flow/frontend/fonts/OFL.txt`.
