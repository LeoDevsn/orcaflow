# Instalar como servidor

O OrçaFlow 2 usa uma interface web em HTML/CSS/JavaScript, uma API Flask, Waitress como servidor WSGI e SQLite para os dados. O mesmo aplicativo atende o navegador local e clientes de um servidor próprio. A publicação no GitHub distribui código e executáveis; não contrata nem configura hospedagem pública.

## No computador de uma pessoa

Abra `OrcaFlow.exe`. A janela de controle inicia o servidor somente em `127.0.0.1:7460` e abre o navegador. Configure seu nome e sua senha na primeira visita. Mantenha a janela aberta durante o uso; **Encerrar aplicativo** para o servidor. Uma segunda abertura leva ao servidor que já está rodando.

Os dados de negócio continuam em `%LOCALAPPDATA%\OrcaFlow\orcaflow.sqlite3`, preservando a base da versão 1. A autenticação usa `acesso.sqlite3` e `.server-key` na mesma pasta. Não apague esses arquivos. Backups feitos pela interface contêm os dados comerciais, sem a senha ou a chave de sessão.

## Servidor Windows ou Linux com Python

Requer Python 3.12+. Instale o projeto e configure o acesso **no terminal local do servidor**:

```text
python -m pip install .
python -m orca_flow --data-dir /caminho/seguro/dados --init-owner
```

O comando pergunta nome e senha sem gravar a senha em arquivos de configuração ou histórico do terminal. Depois configure as variáveis de ambiente para seu domínio:

```text
ORCAFLOW_HTTPS=1
ORCAFLOW_PROXY=1
ORCAFLOW_TRUSTED_HOSTS=localhost,127.0.0.1,orcaflow.seudominio.com
```

Execute o backend em loopback, atrás do proxy HTTPS:

```text
python -m orca_flow --data-dir /caminho/seguro/dados --server --host 127.0.0.1 --port 7460
```

Os exemplos usam caminhos Linux. No Windows, use uma pasta absoluta como `C:\OrcaFlow\dados` e configure as variáveis com `$env:NOME="valor"` no PowerShell. O modo `--server` não depende de interface gráfica.

## Proxy HTTPS

Exemplo de configuração Caddy para um domínio que já aponta para o servidor:

```text
orcaflow.seudominio.com {
    reverse_proxy 127.0.0.1:7460
}
```

A instalação do proxy, configuração DNS e gerenciamento de TLS são responsabilidade do administrador. `ORCAFLOW_PROXY=1` aceita o protocolo encaminhado somente do proxy em `127.0.0.1`. Não exponha a porta do backend à internet. Requisições remotas à API por HTTP sem TLS são recusadas. Cookies usam Secure quando `ORCAFLOW_HTTPS=1`.

## Portal e recebimentos

O proprietário cadastra o endereço público em **Meu negócio → Links para clientes**, depois que DNS/TLS e proxy já estiverem funcionando. Alternativamente, o administrador pode definir `ORCAFLOW_PUBLIC_URL=https://orcaflow.seudominio.com`. Sem endereço público, links são locais e não funcionam no dispositivo de um cliente externo.

Em **Receber por Pix ou cartão**, cadastre as credenciais da aplicação Mercado Pago. Elas vêm vazias. Configure Webhooks de **Pagamentos** em `https://seu-dominio/api/payments/webhook` e copie a assinatura secreta. Use conta/credenciais de teste e homologue primeiro. O formulário verifica a conta pela API antes de guardar a configuração; marcar produção não substitui a homologação do provedor.

As credenciais são cifradas com Fernet em `.payments.enc`, com chave `.payments-key`, ambas na pasta de dados. Proteja essa pasta e os backups administrativos. O backup comercial não inclui essas credenciais. O arquivo `.portal-generation` invalida links ao restaurar uma base; depois da restauração, gere links novos para os clientes. Não copie arquivos secretos para repositórios públicos ou imagens Docker.

As notificações têm assinatura HMAC verificada antes da consulta à API. A confirmação canônica confere referência, recebedor, BRL, valor e modo de teste/produção. Nenhum endpoint de retorno aceita um status de pagamento vindo do navegador como prova. Não há cancelamento de pagamento, reembolso automático ou divisão de pagamentos nesta versão; trate essas operações na conta do provedor. Desabilitar recebimentos ou encerrar um link não desfaz um checkout já iniciado.

A integração com Mercado Pago foi testada com respostas simuladas. Recebimentos reais dependem da conta, domínio HTTPS, credenciais e homologação pelo proprietário. Recursos e instruções oficiais: [Checkout Pro](https://www.mercadopago.com.br/developers/pt/docs/checkout-pro-preferences/overview), [Webhooks](https://www.mercadopago.com.br/developers/pt/docs/checkout-pro-preferences/payment-notifications).

Documentos fiscais anexados são armazenados no banco comercial e entram no backup. A emissão continua externa; cadastrar CPF/CNPJ não cria autorização para emitir NFS-e.

## Docker Compose

O `compose.yaml` é um modelo para uso atrás do proxy HTTPS no mesmo host. Antes de subir, troque `orcaflow.example.com` pelo seu domínio. Crie a conta no volume e depois inicie:

```text
docker compose build
docker compose run --rm -it orcaflow python -m orca_flow --data-dir /data --init-owner
docker compose up -d
```

O volume `orcaflow-data` precisa ser preservado. O processo roda como usuário sem privilégios. A porta publicada fica restrita ao loopback do host. O modelo e a construção da imagem precisam ser validados no ambiente Docker de destino; o build Docker não foi executado na estação Windows desta entrega.

Dentro do container, `ORCAFLOW_PROXY_IP=*` aceita o protocolo encaminhado porque o proxy no host chega pela ponte Docker, sem endereço fixo. Essa opção pressupõe a porta publicada **somente em 127.0.0.1** e rede de containers confiável. Não altere a publicação para `0.0.0.0`. Fora de Docker, o padrão é confiar somente em `127.0.0.1`; `ORCAFLOW_PROXY_IP` permite indicar outro endereço exato de proxy quando necessário.

## Acesso e operação

- Uma conta de trabalho com senha; múltiplos navegadores podem se conectar ao mesmo espaço. Não existe separação por empresa, conta individual de funcionário ou permissões por papel.
- Senhas têm hash scrypt, sessões duram até 12 horas e mudar a senha invalida os outros acessos.
- Escritas exigem token contra CSRF; hosts aceitos são explícitos. Login tem limite de tentativas por endereço.
- Dados de demonstração são isolados por sessão e não entram na base real.
- Rascunhos web detectam atualização concorrente e recusam gravar sobre uma versão mais recente.
- O banco SQLite atende instalações pequenas em uma única instância. Não execute réplicas independentes contra o mesmo volume. Não é uma arquitetura distribuída.
- Faça backups regulares, monitore espaço em disco e proteja o acesso à pasta do servidor. Logs de erro ficam em `servidor.log`. Não há criptografia do banco em repouso.

Se a senha for perdida, o administrador com acesso local à pasta de dados pode executar:

```text
python -m orca_flow --data-dir /caminho/seguro/dados --reset-password
```

Isso altera a senha e encerra as sessões anteriores. Não existe recuperação remota sem acesso administrativo ao servidor.

## Verificação

`GET /health` retorna somente o estado e a versão. Use `python -X utf8 -m unittest discover -s tests -v` para testar regras e API. `npm ci` e `npm test` executam o fluxo do front em DOM simulado contra um servidor HTTP real, sem acessar perfis do navegador. A revisão visual em navegadores reais está pendente conforme `QA.md`.
