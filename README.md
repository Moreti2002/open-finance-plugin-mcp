# pluggy-mcp

Servidor MCP (Model Context Protocol) somente leitura que expõe os seus próprios
dados financeiros do Open Finance Brasil, via [Meu Pluggy](https://meu.pluggy.ai),
para clientes MCP como Claude Code, Claude Desktop e Cursor.

Existe porque o Meu Pluggy é gratuito para uma pessoa acessar as próprias contas
pela API (até 5 conexões do mesmo titular, conforme
[pluggy.ai/meu-pluggy](https://www.pluggy.ai/meu-pluggy)), mas o
[MCP oficial](https://github.com/pluggyai/pluggy-mcp) tem só duas ferramentas
(contas de um item e lista de conectores) e não é atualizado desde junho de 2025.

## O que ele não faz

Não move dinheiro. Não existe PIX, transferência, pagamento nem alteração de
dados. O único `POST` do código é o `/auth` que obtém a apiKey, e um teste
falha se aparecer outro método de escrita. Todas as ferramentas são marcadas
como `readOnlyHint`.

Não armazena nada: cada chamada consulta a API e devolve o resultado ao cliente
MCP. Os dados continuam armazenados na Pluggy, que é a intermediária regulada.

## Ferramentas

| Ferramenta | O que devolve |
|---|---|
| `listar_conexoes` | Banco, status, última atualização e validade do consentimento de cada item |
| `listar_contas` | Contas correntes, poupanças e cartões, com saldo |
| `saldo` | Saldo atual de uma conta |
| `transacoes` | Transações por período (`desde`, `ate`), de uma conta ou de todas |
| `faturas` | Faturas de cartão: vencimento, fechamento, total, pagamento mínimo |
| `investimentos` | Posições de investimento de todas as conexões |
| `gastos_por_categoria` | Soma das saídas por categoria e moeda no período |

Convenções:

- `tipo` `DEBIT` é dinheiro que saiu e `CREDIT` é dinheiro que entrou, tanto na
  conta quanto no cartão.
- Compra em moeda estrangeira usa o valor convertido para a moeda da conta.
- Em `gastos_por_categoria`, o pagamento da fatura na conta corrente e as
  compras no cartão representam o mesmo gasto. Use `ignorar_categorias` para
  tirar o pagamento de fatura e as transferências entre contas próprias.

## Pré-requisitos

1. Conta no [Meu Pluggy](https://meu.pluggy.ai) com os bancos conectados.
2. Conta no [Dashboard Pluggy](https://dashboard.pluggy.ai), com uma aplicação
   criada. Dela saem o Client ID e o Client Secret.
3. Na aplicação, uma conexão com o conector **MeuPluggy** para cada banco. Não
   use o conector do banco nem o Sandbox. Cada conexão tem um `itemId`.
4. Python 3.12 e [uv](https://docs.astral.sh/uv/).

O passo a passo oficial está em [pluggy.ai/meu-pluggy](https://www.pluggy.ai/meu-pluggy).

## Configuração

Tudo por variável de ambiente. Nada de segredo em arquivo do repositório.

| Variável | Conteúdo |
|---|---|
| `PLUGGY_CLIENT_ID` | Client ID da aplicação |
| `PLUGGY_CLIENT_SECRET` | Client Secret da aplicação |
| `PLUGGY_ITEM_IDS` | itemIds separados por vírgula (a API não lista itens) |

Exemplo para Claude Code (`.mcp.json`), lendo as variáveis do ambiente em que o
cliente foi aberto:

```json
{
  "mcpServers": {
    "pluggy": {
      "command": "uv",
      "args": ["run", "--directory", "/caminho/para/pluggy-mcp", "pluggy-mcp"],
      "env": {
        "PLUGGY_CLIENT_ID": "${PLUGGY_CLIENT_ID}",
        "PLUGGY_CLIENT_SECRET": "${PLUGGY_CLIENT_SECRET}",
        "PLUGGY_ITEM_IDS": "${PLUGGY_ITEM_IDS}"
      }
    }
  }
}
```

## Desenvolvimento

```bash
uv sync
uv run pytest
```

Os testes simulam a API da Pluggy com um transporte falso e dados sintéticos.
Nenhum teste faz chamada de rede nem precisa de credencial.

Estrutura:

- `src/pluggy_mcp/cliente.py`: cliente HTTP da API. Faz a autenticação com
  renovação da apiKey (validade de 2 h), a paginação por página e por cursor,
  e aceita um transporte injetável.
- `src/pluggy_mcp/servidor.py`: as ferramentas MCP e a normalização dos campos.

## Licença

MIT.
