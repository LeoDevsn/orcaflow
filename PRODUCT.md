# OrçaFlow

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Autônomos e pequenos negócios que cadastram clientes, preparam orçamentos e acompanham retornos. O pedido atual prioriza explicitamente usuários sem conhecimento técnico.

## Product Purpose

Reunir o trabalho comercial de um profissional em um lugar: cliente, escopo, valor, proposta e próxima conversa. Sucesso significa concluir esse fluxo sem terminal, planilhas paralelas ou dúvidas sobre o que foi salvo.

## Operating Context

Aplicativo Windows existente com dados em SQLite. A nova interface abre no navegador e conversa com um servidor Python. A base de negócio anterior deve continuar utilizável. O computador do servidor precisa permanecer ligado durante o uso.

## Capabilities and Constraints

Preservar cadastro/importação de clientes, propostas com itens e descontos, snapshots de cliente, etapas, lembretes, exportação e backup/restauração. Valores calculados pelo servidor em centavos. Não há envio de mensagens, cobrança, emissão fiscal ou sincronização em nuvem. Dados de demonstração devem ficar separados dos dados reais.

O usuário confirmou o portal externo: destinatários consultam uma proposta por link, aprovam, recusam, pedem ajustes, trocam mensagens e informam dados para nota fiscal. O proprietário configura recebimentos Pix/cartão; nenhum provedor vem preenchido. NFS-e automática depende de integração fiscal específica; a versão atual solicita dados e entrega documentos já emitidos, sem fabricar notas fiscais.

## Brand Commitments

Nome OrçaFlow. O usuário rejeitou o visual semelhante ao PastaPronta e solicitou uma identidade menos genérica, usando Impeccable. Não foram fixados cores, fontes ou referências externas. Português brasileiro, linguagem clara e direta.

## Evidence on Hand

Screenshot do aplicativo anterior enviado pelo usuário. `orca_flow/core.py` e testes documentam as funções reais. A demonstração usa nomes identificados como exemplos e domínios example.com. Não existem depoimentos, métricas de adoção ou clientes reais autorizados para divulgação.

## Product Principles

- Priorizar a tarefa em andamento e oferecer um próximo passo claro.
- Mostrar o resultado da ação e preservar dados já gravados.
- Evitar termos de infraestrutura nos fluxos de clientes e orçamentos.
- Proteger a base real e separar demonstração, autenticação e backups.
