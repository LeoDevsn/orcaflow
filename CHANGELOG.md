# Alterações

## 2.1.0

- Portal reservado por link para aprovar, recusar e pedir ajustes em uma versão fixa.
- Conversa com o cliente, pedidos convertidos em tarefas e aviso de mensagens novas.
- Pix/cartão via checkout Mercado Pago, com configuração inicial vazia, credenciais cifradas e confirmação canônica por API/Webhook.
- Cadastro de prestador PF/PJ com CPF/CNPJ numérico ou alfanumérico, identificação e contato nas propostas.
- Solicitação de dados fiscais e entrega de PDF/XML emitidos externamente, incluídos no backup.
- Link revogável, expiração de acesso e invalidação de links após restaurar backups.
- Homologação de pagamentos e revisão visual real permanecem dependentes da configuração e do ambiente descritos em QA.md.

## 2.0.0

- Nova interface web, com navegação superior, linguagem de tarefas e estados vazios orientados.
- Front HTML/CSS/JavaScript e API Flask servida por Waitress.
- Primeiro acesso com senha, sessões protegidas e demonstração isolada por navegador.
- Editor em página completa, resumo visível e proteção contra edição concorrente.
- Download da cópia anterior após restauração de backup.
- Executável inicia o servidor local; modo servidor separado e modelos Docker.
- Mantém a base comercial da versão 1. Testes de API e integração do front adicionados.
- Revisão visual em navegador real pendente devido à indisponibilidade do controle do navegador. Consulte QA.md.

## 1.0.0

- Cadastro, edição e importação atômica de clientes por CSV.
- Orçamentos com cálculo decimal, desconto, validade e dados do cliente preservados.
- Histórico de etapas, duplicação e propostas para impressão.
- Agenda com retornos automáticos e mensagens para copiar.
- Dashboard, perfil do negócio e demonstração isolada.
- Backup/restauração com cópia anterior e exportação CSV.
- Executável Windows, testes automáticos e build reproduzível.
