# Verificação da versão 2

## Executado

Na versão 2.1: 45 testes Python e um fluxo DOM/HTTP incluindo portal do cliente, aprovação, conversa, pedido de alteração e solicitação de dados fiscais. Os testes de pagamento simulam a API do provedor: assinatura inválida, moeda/valor/conta/ambiente incorretos, notificação repetida, estorno e pagamento duplicado. Não foram feitos pagamentos reais nem homologação com conta Mercado Pago. Documentos fiscais de teste são arquivos fictícios, sem validade fiscal.

- Testes de negócio: centavos, arredondamento, snapshots de cliente, etapas, agenda e backups.
- Testes da API: primeiro acesso local, login/logout, CSRF, hosts permitidos, sessão privada, isolamento da demo, mudança de senha, download/restauração e fluxo comercial.
- Teste do front com jsdom e API HTTP real: primeiro acesso, cliente, orçamento, resumo, erro de desconto com preservação dos campos, salvamento, etapa, agenda, conclusão e busca. Nenhum erro de execução no fluxo testado.
- Checagem de sintaxe JavaScript e leitura HTTP do servidor local.
- Impeccable: contexto, direção, craft floor e detector mecânico dos três arquivos do front. O detector retornou `[]`; ele avisou que as URLs absolutas `/static/style.css` e `/static/portal.css` não pôde ser seguida pelo resolvedor de arquivos. O CSS também foi passado diretamente como alvo. Resultado mecânico não equivale a aprovação visual.

## Pendente

O host de acesso ao navegador não estava disponível. A tentativa de revisão pelo controle do computador foi interrompida pela própria ferramenta por não conseguir determinar a URL atual com segurança. Não foram usados outros controles de navegador para contornar essa restrição.

Assim, ficam pendentes: revisão visual em desktop e celular, zoom a 200%, interação de toque, foco real dos diálogos e renderização das fontes. Existem regras responsivas e estados acessíveis no código; não se afirma conformidade WCAG ou aprovação visual sem essa validação.

O Dockerfile e o Compose são fornecidos para operação em servidor, mas a construção da imagem e a configuração real de DNS/TLS dependem do ambiente de destino e não foram verificadas aqui.
