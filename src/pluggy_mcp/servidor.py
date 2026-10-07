"""Servidor MCP, so de leitura, com os dados do Meu Pluggy do proprio usuario.

Configuracao por variavel de ambiente:
    PLUGGY_CLIENT_ID, PLUGGY_CLIENT_SECRET  credenciais da aplicacao no Dashboard
    PLUGGY_ITEM_IDS                         itemIds separados por virgula (a API
                                            nao lista itens, entao eles vem daqui)
"""
from __future__ import annotations

import os
from collections import defaultdict
from functools import cache
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from pluggy_mcp.cliente import ClientePluggy, ErroPluggy

mcp = MCPServer(
    name="pluggy",
    instructions=(
        "Dados financeiros pessoais (Open Finance Brasil via Meu Pluggy), so leitura. "
        "Valores em DEBIT sao saidas de dinheiro. Pagamento de fatura na conta corrente "
        "e as compras no cartao representam o mesmo gasto: nao some os dois."
    ),
)
SO_LEITURA = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                             idempotent_hint=True, open_world_hint=True)


@cache
def cliente() -> ClientePluggy:
    return ClientePluggy(os.environ.get("PLUGGY_CLIENT_ID", ""),
                         os.environ.get("PLUGGY_CLIENT_SECRET", ""))


def item_ids() -> list[str]:
    ids = [i.strip() for i in os.environ.get("PLUGGY_ITEM_IDS", "").split(",") if i.strip()]
    if not ids:
        raise ErroPluggy("PLUGGY_ITEM_IDS vazio: informe os itemIds das conexoes "
                         "MeuPluggy, separados por virgula")
    return ids


def valor(tx: dict) -> float:
    # Compra em moeda estrangeira: o valor convertido e o que pesa na conta.
    convertido = tx.get("amountInAccountCurrency")
    return convertido if convertido is not None else tx["amount"]


def todas_as_contas() -> list[dict]:
    return [c for item_id in item_ids() for c in cliente().contas(item_id)]


def resumo_transacao(tx: dict, conta_id: str) -> dict:
    return {
        "data": tx.get("date", "")[:10], "descricao": tx.get("description"),
        "valor": valor(tx), "moeda": tx.get("currencyCode"), "tipo": tx.get("type"),
        "categoria": tx.get("category"), "status": tx.get("status"), "conta_id": conta_id,
    }


# Codigo COMPE (inicio do transferNumber da conta corrente) -> nome do banco.
BANCOS_COMPE = {
    "001": "Banco do Brasil", "033": "Santander", "077": "Inter", "102": "XP",
    "104": "Caixa", "208": "BTG Pactual", "212": "Banco Original", "237": "Bradesco",
    "260": "Nubank", "290": "PagBank", "323": "Mercado Pago", "336": "C6 Bank",
    "341": "Itau", "380": "PicPay", "422": "Safra", "655": "Votorantim",
    "748": "Sicredi", "756": "Sicoob",
}


def deduzir_banco(contas: list[dict]) -> str | None:
    """Pelo MeuPluggy o conector e sempre 'MeuPluggy': o banco sai das contas.
    Ordem: codigo COMPE da conta corrente, nome da conta corrente, nome da 1a conta."""
    correntes = [c for c in contas if c.get("type") == "BANK"]
    for c in correntes:
        compe = str((c.get("bankData") or {}).get("transferNumber") or "").split("/")[0]
        if compe in BANCOS_COMPE:
            return BANCOS_COMPE[compe]
    for c in correntes + contas:
        if c.get("name"):
            return c["name"]
    return None


@mcp.tool(annotations=SO_LEITURA)
def listar_conexoes() -> list[dict]:
    """Conexoes (itens) configuradas: banco, status e data da ultima atualizacao."""
    saida = []
    for item_id in item_ids():
        item = cliente().item(item_id)
        saida.append({"item_id": item_id,
                      "banco": (deduzir_banco(cliente().contas(item_id))
                                or (item.get("connector") or {}).get("name")),
                      "status": item.get("status"),
                      "atualizado_em": item.get("lastUpdatedAt"),
                      "consentimento_expira_em": item.get("consentExpiresAt")})
    return saida


@mcp.tool(annotations=SO_LEITURA)
def listar_contas() -> list[dict]:
    """Contas correntes, poupancas e cartoes de credito, com o saldo informado pelo banco."""
    return [{"conta_id": c["id"], "item_id": c.get("itemId"), "tipo": c.get("type"),
             "subtipo": c.get("subtype"), "nome": c.get("name"),
             "saldo": c.get("balance"), "moeda": c.get("currencyCode")}
            for c in todas_as_contas()]


@mcp.tool(annotations=SO_LEITURA)
def saldo(conta_id: str) -> dict:
    """Saldo atual de uma conta, como o banco informou na ultima sincronizacao."""
    c = cliente().conta(conta_id)
    return {"conta_id": c["id"], "saldo": c.get("balance"), "moeda": c.get("currencyCode"),
            "atualizado_em": c.get("updatedAt")}


@mcp.tool(annotations=SO_LEITURA)
def transacoes(desde: str, ate: str | None = None,
               conta_id: str | None = None) -> list[dict]:
    """Transacoes no periodo (datas AAAA-MM-DD). Sem conta_id, traz de todas as contas.
    tipo DEBIT = dinheiro saiu; CREDIT = entrou."""
    contas = [conta_id] if conta_id else [c["id"] for c in todas_as_contas()]
    return [resumo_transacao(tx, cid)
            for cid in contas for tx in cliente().transacoes(cid, desde, ate)]


@mcp.tool(annotations=SO_LEITURA)
def faturas(conta_id: str | None = None) -> list[dict]:
    """Faturas de cartao de credito. Sem conta_id, traz de todos os cartoes."""
    cartoes = ([conta_id] if conta_id else
               [c["id"] for c in todas_as_contas() if c.get("type") == "CREDIT"])
    return [{"conta_id": cid, "vencimento": (f.get("dueDate") or "")[:10],
             "fechamento": (f.get("billClosingDate") or "")[:10],
             "total": f.get("totalAmount"), "moeda": f.get("totalAmountCurrencyCode"),
             "pagamento_minimo": f.get("minimumPaymentAmount")}
            for cid in cartoes for f in cliente().faturas(cid)]


@mcp.tool(annotations=SO_LEITURA)
def investimentos() -> list[dict]:
    """Posicoes de investimento de todas as conexoes."""
    return [{"item_id": item_id, "nome": i.get("name"), "tipo": i.get("type"),
             "subtipo": i.get("subtype"), "saldo": i.get("balance"),
             "moeda": i.get("currencyCode"), "vencimento": i.get("dueDate"),
             "instituicao": (i.get("institution") or {}).get("name")}
            for item_id in item_ids() for i in cliente().investimentos(item_id)]


@mcp.tool(annotations=SO_LEITURA)
def gastos_por_categoria(desde: str, ate: str | None = None,
                         ignorar_categorias: list[str] | None = None) -> list[dict]:
    """Soma das saidas (DEBIT) por categoria e moeda no periodo, da maior para a menor.
    Use ignorar_categorias para tirar transferencias entre contas proprias e
    pagamento de fatura, que senao contam o mesmo gasto duas vezes."""
    ignorar = {c.lower() for c in (ignorar_categorias or [])}
    soma: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0])
    for conta in todas_as_contas():
        for tx in cliente().transacoes(conta["id"], desde, ate):
            categoria = tx.get("category") or "Sem categoria"
            if tx.get("type") != "DEBIT" or categoria.lower() in ignorar:
                continue
            acumulado = soma[(categoria, conta.get("currencyCode") or "BRL")]
            acumulado[0] += abs(valor(tx))  # o sinal varia entre conta e cartao
            acumulado[1] += 1
    linhas: list[dict[str, Any]] = [
        {"categoria": cat, "moeda": moeda, "total": round(total, 2), "transacoes": n}
        for (cat, moeda), (total, n) in soma.items()]
    return sorted(linhas, key=lambda l: l["total"], reverse=True)


def main() -> None:
    mcp.run()
