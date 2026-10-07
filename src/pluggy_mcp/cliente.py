"""Cliente minimo, so de leitura, da API Pluggy (https://api.pluggy.ai).

Nao existe aqui nenhuma chamada que mova dinheiro: o unico POST e o /auth.
O transporte HTTP e injetavel para que os testes simulem a API sem rede.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from mcp.server.mcpserver.exceptions import ToolError

API = "https://api.pluggy.ai"
VALIDADE_API_KEY_S = 2 * 60 * 60  # a Pluggy declara 2 h para a apiKey
MARGEM_RENOVACAO_S = 10 * 60

# (metodo, url, cabecalhos, corpo) -> JSON decodificado
Transporte = Callable[[str, str, dict[str, str], dict | None], Any]


class ErroPluggy(ToolError):
    """Falha prevista: o SDK repassa a mensagem ao modelo em vez de escondê-la."""


def transporte_urllib(metodo: str, url: str, cabecalhos: dict[str, str],
                      corpo: dict | None) -> Any:
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, headers=cabecalhos, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        # O corpo do erro e onde a Pluggy explica o que faltou; nao contem a chave.
        detalhe = e.read().decode(errors="replace")[:500]
        caminho = urllib.parse.urlsplit(url).path
        raise ErroPluggy(f"HTTP {e.code} em {metodo} {caminho}: {detalhe}") from None


class ClientePluggy:
    def __init__(self, client_id: str, client_secret: str,
                 transporte: Transporte = transporte_urllib,
                 relogio: Callable[[], float] = time.monotonic) -> None:
        if not client_id or not client_secret:
            raise ErroPluggy("PLUGGY_CLIENT_ID e PLUGGY_CLIENT_SECRET sao obrigatorios")
        self._credenciais = {"clientId": client_id, "clientSecret": client_secret}
        self._transporte = transporte
        self._relogio = relogio
        self._api_key: str | None = None
        self._expira_em = 0.0

    def _chave(self) -> str:
        if self._api_key is None or self._relogio() >= self._expira_em:
            resp = self._transporte("POST", f"{API}/auth",
                                    {"Content-Type": "application/json"},
                                    self._credenciais)
            self._api_key = resp["apiKey"]
            self._expira_em = self._relogio() + VALIDADE_API_KEY_S - MARGEM_RENOVACAO_S
        return self._api_key

    def get(self, caminho: str, params: dict[str, Any] | None = None) -> Any:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        url = f"{API}{caminho}"
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        return self._transporte("GET", url, {"X-API-KEY": self._chave(),
                                             "Accept": "application/json"}, None)

    def paginado(self, caminho: str, params: dict[str, Any]) -> list[dict]:
        """Endpoints com page/totalPages (contas, faturas, investimentos)."""
        resultados, pagina = [], 1
        while True:
            resp = self.get(caminho, {**params, "page": pagina, "pageSize": 500})
            resultados += resp.get("results", [])
            if pagina >= resp.get("totalPages", 1):
                return resultados
            pagina += 1

    # --- recursos -----------------------------------------------------------

    def item(self, item_id: str) -> dict:
        return self.get(f"/items/{item_id}")

    def contas(self, item_id: str) -> list[dict]:
        return self.paginado("/accounts", {"itemId": item_id})

    def saldo(self, conta_id: str) -> dict:
        return self.get(f"/accounts/{conta_id}/balance")

    def transacoes(self, conta_id: str, desde: str | None = None,
                   ate: str | None = None) -> list[dict]:
        """/v2/transactions pagina por cursor: 'next' ja vem pronto para concatenar."""
        resultados = []
        resp = self.get("/v2/transactions",
                        {"accountId": conta_id, "dateFrom": desde, "dateTo": ate})
        while True:
            resultados += resp["results"]
            if not resp.get("next"):
                return resultados
            resp = self.get(f"/v2/transactions{resp['next']}")

    def faturas(self, conta_id: str) -> list[dict]:
        return self.paginado("/bills", {"accountId": conta_id})

    def investimentos(self, item_id: str) -> list[dict]:
        return self.paginado("/investments", {"itemId": item_id})
