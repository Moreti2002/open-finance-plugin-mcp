"""Testes com uma API Pluggy falsa. Todos os dados sao sinteticos."""
from __future__ import annotations

import ast
import asyncio
import urllib.parse
from pathlib import Path

import pytest

from pluggy_mcp import servidor
from pluggy_mcp.cliente import ClientePluggy, ErroPluggy

ITEM = "item-teste-1"
CORRENTE, CARTAO = "conta-corrente-1", "conta-cartao-1"


class ApiFalsa:
    """Responde como a Pluggy e registra cada chamada."""

    def __init__(self) -> None:
        self.chamadas: list[tuple[str, str, dict]] = []
        self.autenticacoes = 0

    def __call__(self, metodo, url, cabecalhos, corpo):
        partes = urllib.parse.urlsplit(url)
        caminho, q = partes.path, dict(urllib.parse.parse_qsl(partes.query))
        self.chamadas.append((metodo, caminho, q))
        if caminho == "/auth":
            assert metodo == "POST" and corpo == {"clientId": "id-falso",
                                                  "clientSecret": "segredo-falso"}
            self.autenticacoes += 1
            return {"apiKey": f"chave-{self.autenticacoes}"}
        assert metodo == "GET", "o servidor so pode ler"
        assert cabecalhos["X-API-KEY"].startswith("chave-")
        return self.rotas(caminho, q)

    def rotas(self, caminho, q):
        if caminho == f"/items/{ITEM}":
            return {"id": ITEM, "status": "UPDATED", "connector": {"name": "Banco Ficticio"},
                    "lastUpdatedAt": "2026-01-02T00:00:00Z",
                    "consentExpiresAt": "2027-01-01T00:00:00Z"}
        if caminho == "/accounts":
            assert q["itemId"] == ITEM
            return {"page": 1, "totalPages": 1, "results": [
                {"id": CORRENTE, "itemId": ITEM, "type": "BANK", "subtype": "CHECKING_ACCOUNT",
                 "name": "Conta", "balance": 100.0, "currencyCode": "BRL"},
                {"id": CARTAO, "itemId": ITEM, "type": "CREDIT", "subtype": "CREDIT_CARD",
                 "name": "Cartao", "balance": 50.0, "currencyCode": "BRL"}]}
        if caminho == "/v2/transactions":
            return self.transacoes(q)
        if caminho == "/bills":
            assert q["accountId"] == CARTAO
            return {"page": 1, "totalPages": 1, "results": [
                {"id": "f1", "dueDate": "2026-02-10T00:00:00Z",
                 "billClosingDate": "2026-02-01T00:00:00Z", "totalAmount": 30.0,
                 "totalAmountCurrencyCode": "BRL", "minimumPaymentAmount": 5.0}]}
        if caminho == "/investments":
            pagina = int(q["page"])
            return {"page": pagina, "totalPages": 2, "results": [
                {"name": f"CDB {pagina}", "type": "FIXED_INCOME", "balance": 10.0 * pagina,
                 "currencyCode": "BRL", "institution": {"name": "Emissor Ficticio"}}]}
        if caminho == f"/accounts/{CORRENTE}/balance":
            return {"balance": 100.0}
        raise AssertionError(f"rota inesperada {caminho}")

    @staticmethod
    def transacoes(q):
        if q["accountId"] == CORRENTE:
            if "after" not in q:  # primeira pagina: aponta para a segunda pelo cursor
                return {"results": [
                    {"date": "2026-01-05T00:00:00Z", "description": "Mercado", "amount": -20.0,
                     "type": "DEBIT", "category": "Groceries", "currencyCode": "BRL"},
                    {"date": "2026-01-06T00:00:00Z", "description": "Salario", "amount": 500.0,
                     "type": "CREDIT", "category": "Salary", "currencyCode": "BRL"}],
                    "next": "?accountId=conta-corrente-1&after=cursor-2"}
            return {"results": [
                {"date": "2026-01-07T00:00:00Z", "description": "Pagamento fatura",
                 "amount": -30.0, "type": "DEBIT", "category": "Credit card payment",
                 "currencyCode": "BRL"}], "next": None}
        # Cartao: compra positiva com DEBIT, e uma em dolar com valor convertido.
        return {"results": [
            {"date": "2026-01-08T00:00:00Z", "description": "Restaurante", "amount": 25.0,
             "type": "DEBIT", "category": "Restaurants", "currencyCode": "BRL"},
            {"date": "2026-01-09T00:00:00Z", "description": "Assinatura", "amount": 2.0,
             "amountInAccountCurrency": 11.0, "type": "DEBIT", "category": "Groceries",
             "currencyCode": "USD"}], "next": None}


@pytest.fixture
def api(monkeypatch):
    falsa = ApiFalsa()
    monkeypatch.setenv("PLUGGY_ITEM_IDS", f" {ITEM} ,")
    monkeypatch.setattr(servidor, "cliente",
                        lambda c=ClientePluggy("id-falso", "segredo-falso", falsa): c)
    return falsa


def test_listar_conexoes(api):
    [c] = servidor.listar_conexoes()
    assert c == {"item_id": ITEM, "banco": "Banco Ficticio", "status": "UPDATED",
                 "atualizado_em": "2026-01-02T00:00:00Z",
                 "consentimento_expira_em": "2027-01-01T00:00:00Z"}


def test_listar_contas_e_saldo(api):
    contas = servidor.listar_contas()
    assert [c["conta_id"] for c in contas] == [CORRENTE, CARTAO]
    assert servidor.saldo(CORRENTE) == {"balance": 100.0}


def test_transacoes_segue_cursor_e_repassa_filtro_de_data(api):
    txs = servidor.transacoes("2026-01-01", "2026-01-31", conta_id=CORRENTE)
    assert [t["descricao"] for t in txs] == ["Mercado", "Salario", "Pagamento fatura"]
    primeira = next(q for m, c, q in api.chamadas if c == "/v2/transactions")
    assert primeira["dateFrom"] == "2026-01-01" and primeira["dateTo"] == "2026-01-31"


def test_transacoes_sem_conta_traz_todas(api):
    assert len(servidor.transacoes("2026-01-01")) == 5


def test_faturas_so_dos_cartoes(api):
    [f] = servidor.faturas()
    assert f["conta_id"] == CARTAO and f["total"] == 30.0 and f["fechamento"] == "2026-02-01"


def test_investimentos_pagina(api):
    assert [i["nome"] for i in servidor.investimentos()] == ["CDB 1", "CDB 2"]


def test_gastos_por_categoria(api):
    linhas = servidor.gastos_por_categoria("2026-01-01",
                                           ignorar_categorias=["credit card payment"])
    assert linhas == [
        {"categoria": "Groceries", "moeda": "BRL", "total": 31.0, "transacoes": 2},
        {"categoria": "Restaurants", "moeda": "BRL", "total": 25.0, "transacoes": 1}]


def test_api_key_e_reaproveitada_e_renovada():
    falsa, agora = ApiFalsa(), [0.0]
    c = ClientePluggy("id-falso", "segredo-falso", falsa, relogio=lambda: agora[0])
    c.saldo(CORRENTE)
    c.saldo(CORRENTE)
    assert falsa.autenticacoes == 1
    agora[0] += 2 * 60 * 60
    c.saldo(CORRENTE)
    assert falsa.autenticacoes == 2


def test_falha_alto_sem_credenciais_ou_sem_itens(monkeypatch):
    with pytest.raises(ErroPluggy):
        ClientePluggy("", "")
    monkeypatch.delenv("PLUGGY_ITEM_IDS", raising=False)
    with pytest.raises(ErroPluggy, match="PLUGGY_ITEM_IDS"):
        servidor.item_ids()


def test_todas_as_ferramentas_sao_so_leitura():
    ferramentas = asyncio.run(servidor.mcp.list_tools())
    assert {f.name for f in ferramentas} == {
        "listar_conexoes", "listar_contas", "saldo", "transacoes", "faturas",
        "investimentos", "gastos_por_categoria"}
    assert all(f.annotations.read_only_hint for f in ferramentas)


def test_codigo_nao_tem_post_alem_do_auth():
    """Garantia estrutural: nenhuma escrita na API alem de obter a apiKey."""
    fonte = Path(servidor.__file__).with_name("cliente.py").read_text()
    posts = [n for n in ast.walk(ast.parse(fonte))
             if isinstance(n, ast.Constant) and n.value in ("POST", "PUT", "PATCH", "DELETE")]
    assert len(posts) == 1  # o POST /auth
