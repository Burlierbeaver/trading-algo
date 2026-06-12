"""Robinhood Agentic Trading broker via MCP.

Robinhood exposes its Agentic Trading beta as an MCP (Model Context
Protocol) server speaking Streamable HTTP at
``https://agent.robinhood.com/mcp/trading``. This module wraps that server
behind the same ``execute_order`` contract the pipeline already uses for
the Alpaca adapter, plus the read-only quote/cash/positions surface the
risk manager's ``BrokerBridge`` needs — so Robinhood drops into either
seam without touching the rest of the system.

Robinhood has not published a frozen tool schema for the beta, so nothing
here hardcodes tool names: the broker calls ``tools/list`` at connect
time, resolves each capability (place order, quote, positions, account)
by keyword against the discovered tools, and adapts argument names to
each tool's declared ``inputSchema``. Pass ``tool_map`` to pin exact tool
names if discovery guesses wrong; ``trading-algo robinhood-tools`` prints
what the server offers and how it resolved.

Safety: order placement is OFF by default. ``execute_order`` raises
``OrdersDisabled`` unless the broker was built with ``allow_orders=True``
or ``ROBINHOOD_MCP_ALLOW_ORDERS=1`` is set. Read-only calls always work.
Auth is a bearer token from ``token=`` or ``ROBINHOOD_MCP_TOKEN``.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional, Protocol

from alpaca_broker_adapter import OrderRequest, OrderResult, OrderStatus

from risk_manager import Position

from trading_algo.bridges.broker import BrokerBridge

log = logging.getLogger(__name__)

DEFAULT_URL = "https://agent.robinhood.com/mcp/trading"
TOKEN_ENV = "ROBINHOOD_MCP_TOKEN"
ALLOW_ORDERS_ENV = "ROBINHOOD_MCP_ALLOW_ORDERS"
PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "trading-algo", "version": "0.1.0"}


class MCPError(RuntimeError):
    """JSON-RPC, transport, or tool-level failure from the MCP server."""


class OrdersDisabled(MCPError):
    """Order placement attempted without allow_orders / the env opt-in."""


class ToolNotFound(MCPError):
    """No discovered tool matched a required capability."""


# ── transport ─────────────────────────────────────────────────────────


class Transport(Protocol):
    def request(self, payload: dict) -> Optional[dict]:
        """Send one JSON-RPC message; return the response message, or None
        for notifications (no response expected)."""
        ...


def parse_http_response(
    content_type: str, body: str, request_id: Optional[int]
) -> Optional[dict]:
    """Decode a Streamable HTTP response body into the JSON-RPC response
    message matching ``request_id`` (or None for accepted notifications)."""
    if request_id is None or not body:
        return None
    if "text/event-stream" in content_type:
        match: Optional[dict] = None
        for line in body.splitlines():
            if not line.startswith("data:"):
                continue
            try:
                message = json.loads(line[len("data:") :].strip())
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict) and message.get("id") == request_id:
                match = message
        if match is None:
            raise MCPError(f"no response for request id={request_id} in event stream")
        return match
    try:
        message = json.loads(body)
    except json.JSONDecodeError as exc:
        raise MCPError(f"invalid JSON-RPC response: {body[:200]!r}") from exc
    if not isinstance(message, dict):
        raise MCPError(f"unexpected JSON-RPC response shape: {body[:200]!r}")
    return message


class StreamableHTTPTransport:
    """Minimal MCP Streamable HTTP client on stdlib urllib — POSTs JSON-RPC,
    accepts JSON or SSE responses, and carries the Mcp-Session-Id header."""

    def __init__(self, url: str = DEFAULT_URL, *, token: Optional[str] = None, timeout: float = 30.0) -> None:
        self._url = url
        self._token = token
        self._timeout = timeout
        self._session_id: Optional[str] = None

    def request(self, payload: dict) -> Optional[dict]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        req = urllib.request.Request(
            self._url, data=json.dumps(payload).encode(), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                session_id = resp.headers.get("Mcp-Session-Id")
                if session_id:
                    self._session_id = session_id
                body = resp.read().decode("utf-8", errors="replace")
                content_type = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise MCPError(f"HTTP {exc.code} from {self._url}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise MCPError(f"cannot reach {self._url}: {exc.reason}") from exc
        return parse_http_response(content_type, body, payload.get("id"))


# ── JSON-RPC / MCP client ─────────────────────────────────────────────


class MCPClient:
    """Initialize handshake + tools/list + tools/call over a Transport."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport
        self._ids = itertools.count(1)
        self.server_info: dict = {}

    def connect(self) -> None:
        result = self.rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
        )
        self.server_info = result.get("serverInfo", {})
        self._transport.request({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def rpc(self, method: str, params: Optional[dict] = None) -> dict:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": next(self._ids), "method": method}
        if params is not None:
            payload["params"] = params
        message = self._transport.request(payload)
        if message is None:
            raise MCPError(f"no response to {method}")
        if "error" in message:
            err = message["error"]
            raise MCPError(f"{method} failed: [{err.get('code')}] {err.get('message')}")
        return message.get("result", {})

    def list_tools(self) -> list[dict]:
        tools: list[dict] = []
        cursor: Optional[str] = None
        while True:
            params = {"cursor": cursor} if cursor else {}
            result = self.rpc("tools/list", params)
            tools.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def call_tool(self, name: str, arguments: dict) -> dict:
        result = self.rpc("tools/call", {"name": name, "arguments": arguments})
        payload = _payload_from_result(result)
        if result.get("isError"):
            raise MCPError(f"tool {name} returned an error: {payload}")
        return payload


def _payload_from_result(result: dict) -> dict:
    """Pull the useful payload out of a tools/call result — prefer
    structuredContent, fall back to JSON embedded in text content."""
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    texts: list[str] = []
    for item in result.get("content", []):
        if item.get("type") != "text":
            continue
        text = item.get("text", "")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            texts.append(text)
            continue
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"results": parsed}
    return {"text": "\n".join(texts)}


# ── tool discovery ────────────────────────────────────────────────────

# capability → keyword groups; a tool matches when every group has at
# least one keyword appearing in its tokenized name (+ description as a
# tiebreaker). Highest total hits wins.
_CAPABILITY_RULES: dict[str, tuple[tuple[str, ...], ...]] = {
    "place_order": (("order", "trade"), ("place", "submit", "create", "execute", "buy", "sell")),
    "get_quote": (("quote", "quotes", "price", "prices"),),
    "get_positions": (("position", "positions", "holding", "holdings", "portfolio"),),
    "get_account": (("account", "balance", "balances", "buying", "cash"),),
    "cancel_order": (("order", "orders", "trade"), ("cancel",)),
}


def _tokens(text: str) -> set[str]:
    out, word = set(), []
    for ch in text.lower():
        if ch.isalnum():
            word.append(ch)
        elif word:
            out.add("".join(word))
            word = []
    if word:
        out.add("".join(word))
    return out


def resolve_tools(tools: Iterable[dict]) -> dict[str, str]:
    """Map each known capability to the best-matching discovered tool."""
    resolved: dict[str, str] = {}
    for capability, groups in _CAPABILITY_RULES.items():
        best_name, best_score = None, 0
        for tool in tools:
            name = tool.get("name", "")
            name_tokens = _tokens(name)
            desc_tokens = _tokens(tool.get("description", ""))
            score = 0
            for group in groups:
                name_hits = sum(2 for kw in group if kw in name_tokens)
                desc_hits = sum(1 for kw in group if kw in desc_tokens)
                if name_hits + desc_hits == 0:
                    score = 0
                    break
                score += name_hits + min(desc_hits, 1)
            if score > best_score or (score == best_score and best_name and score and len(name) < len(best_name)):
                best_name, best_score = name, score
        if best_name and best_score:
            resolved[capability] = best_name
    return resolved


# arg-name synonyms tried (in order) when a tool's inputSchema doesn't
# declare our canonical name.
_ARG_SYNONYMS: dict[str, tuple[str, ...]] = {
    "symbol": ("ticker", "instrument", "stock_symbol"),
    "qty": ("quantity", "shares", "units"),
    "notional": ("amount", "dollar_amount", "notional_value", "amount_in_dollars"),
    "side": ("action", "direction", "transaction_type"),
    "order_type": ("type", "orderType"),
    "limit_price": ("price", "limitPrice"),
    "time_in_force": ("timeInForce", "tif", "duration"),
    "client_order_id": ("clientOrderId", "idempotency_key", "ref_id"),
}


def adapt_args(args: dict, schema: Optional[dict]) -> dict:
    """Rename/coerce arguments to fit a tool's declared inputSchema. With
    no usable schema the canonical names pass through unchanged."""
    properties = (schema or {}).get("properties")
    if not isinstance(properties, dict) or not properties:
        return {k: v for k, v in args.items() if v is not None}
    adapted: dict[str, Any] = {}
    for key, value in args.items():
        if value is None:
            continue
        target = key if key in properties else next(
            (alt for alt in _ARG_SYNONYMS.get(key, ()) if alt in properties), None
        )
        if target is None:
            continue  # tool doesn't take this parameter
        declared = properties[target].get("type")
        if declared == "number" and isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                pass
        elif declared == "integer" and isinstance(value, str):
            try:
                value = int(Decimal(value))
            except (ValueError, InvalidOperation):
                pass
        adapted[target] = value
    return adapted


# ── response parsing helpers ──────────────────────────────────────────


def _dig(payload: Any, keys: tuple[str, ...]) -> Any:
    """Breadth-first search nested dicts/lists for the first present key."""
    queue = [payload]
    while queue:
        node = queue.pop(0)
        if isinstance(node, dict):
            for key in keys:
                if node.get(key) is not None:
                    return node[key]
            queue.extend(node.values())
        elif isinstance(node, list):
            queue.extend(node)
    return None


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace("$", "").replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


_STATUS_MAP = {
    "filled": OrderStatus.FILLED,
    "executed": OrderStatus.FILLED,
    "partially_filled": OrderStatus.PARTIALLY_FILLED,
    "partial": OrderStatus.PARTIALLY_FILLED,
    "canceled": OrderStatus.CANCELED,
    "cancelled": OrderStatus.CANCELED,
    "rejected": OrderStatus.REJECTED,
    "failed": OrderStatus.REJECTED,
    "expired": OrderStatus.EXPIRED,
    "pending": OrderStatus.PENDING,
    "queued": OrderStatus.SUBMITTED,
    "confirmed": OrderStatus.SUBMITTED,
    "accepted": OrderStatus.SUBMITTED,
    "submitted": OrderStatus.SUBMITTED,
    "placed": OrderStatus.SUBMITTED,
    "new": OrderStatus.SUBMITTED,
    "open": OrderStatus.SUBMITTED,
}


def parse_status(value: Any) -> OrderStatus:
    if isinstance(value, str):
        return _STATUS_MAP.get(value.strip().lower().replace(" ", "_"), OrderStatus.SUBMITTED)
    return OrderStatus.SUBMITTED


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


# ── the broker ────────────────────────────────────────────────────────


class RobinhoodMCPBroker:
    """Robinhood Agentic Trading MCP server as a pipeline OrderExecutor +
    the risk manager's read-only quote/cash/positions surface.

    Construction is cheap; the MCP handshake and tool discovery happen on
    first use. ``allow_orders`` must be opted into (arg or
    ``ROBINHOOD_MCP_ALLOW_ORDERS=1``) before execute_order will transmit
    anything — the risk engine and killswitch still gate upstream."""

    def __init__(
        self,
        url: str = DEFAULT_URL,
        *,
        token: Optional[str] = None,
        allow_orders: Optional[bool] = None,
        tool_map: Optional[dict[str, str]] = None,
        transport: Optional[Transport] = None,
        timeout: float = 30.0,
    ) -> None:
        token = token if token is not None else os.environ.get(TOKEN_ENV)
        if allow_orders is None:
            allow_orders = os.environ.get(ALLOW_ORDERS_ENV, "").strip().lower() in {"1", "true", "yes", "on"}
        self._allow_orders = allow_orders
        self._tool_map_override = dict(tool_map or {})
        self._transport = transport or StreamableHTTPTransport(url, token=token, timeout=timeout)
        self._client: Optional[MCPClient] = None
        self._tools: list[dict] = []
        self._resolved: dict[str, str] = {}

    # -- connection / discovery

    def _ensure_connected(self) -> MCPClient:
        if self._client is None:
            client = MCPClient(self._transport)
            client.connect()
            self._tools = client.list_tools()
            self._resolved = resolve_tools(self._tools)
            self._resolved.update(self._tool_map_override)
            self._client = client
            log.info(
                "robinhood mcp connected server=%s tools=%d resolved=%s",
                self._client.server_info.get("name", "?"),
                len(self._tools),
                self._resolved,
            )
        return self._client

    def tools(self) -> list[dict]:
        """The server's discovered tool list (name/description/inputSchema)."""
        self._ensure_connected()
        return list(self._tools)

    def resolved_tools(self) -> dict[str, str]:
        """capability → tool-name map actually in use."""
        self._ensure_connected()
        return dict(self._resolved)

    def _call(self, capability: str, args: dict) -> dict:
        client = self._ensure_connected()
        name = self._resolved.get(capability)
        if name is None:
            raise ToolNotFound(
                f"no Robinhood MCP tool resolved for {capability!r}; "
                f"available: {[t.get('name') for t in self._tools]} — pass tool_map to pin one"
            )
        schema = next((t.get("inputSchema") for t in self._tools if t.get("name") == name), None)
        return client.call_tool(name, adapt_args(args, schema))

    # -- pipeline OrderExecutor

    def execute_order(
        self, order: OrderRequest, *, reference_price: Optional[Decimal] = None
    ) -> OrderResult:
        if not self._allow_orders:
            raise OrdersDisabled(
                "Robinhood MCP order placement is disabled; construct with "
                f"allow_orders=True or set {ALLOW_ORDERS_ENV}=1"
            )
        args = {
            "symbol": order.symbol,
            "side": order.side.value,
            "qty": str(order.qty) if order.qty is not None else None,
            "notional": str(order.notional) if order.notional is not None else None,
            "order_type": order.order_type.value,
            "limit_price": str(order.limit_price) if order.limit_price is not None else None,
            "time_in_force": order.time_in_force.value,
            "client_order_id": str(order.client_order_id),
        }
        payload = self._call("place_order", args)
        broker_order_id = _dig(payload, ("order_id", "orderId", "id"))
        return OrderResult(
            client_order_id=order.client_order_id,
            broker_order_id=str(broker_order_id) if broker_order_id is not None else None,
            status=parse_status(_dig(payload, ("status", "state"))),
            submitted_at=_parse_ts(_dig(payload, ("submitted_at", "created_at", "updated_at"))),
            filled_qty=_decimal(
                _dig(payload, ("filled_qty", "filled_quantity", "cumulative_quantity"))
            )
            or Decimal("0"),
            filled_avg_price=_decimal(
                _dig(payload, ("filled_avg_price", "average_price", "avg_price", "executed_price"))
            ),
        )

    # -- risk manager read-only surface

    def get_quote(self, symbol: str) -> Decimal:
        payload = self._call("get_quote", {"symbol": symbol})
        price = _decimal(
            _dig(payload, ("price", "last_trade_price", "last_price", "mark_price", "ask_price"))
        )
        if price is None:
            raise MCPError(f"no price for {symbol} in quote payload: {payload}")
        return price

    def get_cash(self) -> Decimal:
        payload = self._call("get_account", {})
        cash = _decimal(
            _dig(payload, ("buying_power", "cash", "cash_balance", "available_cash"))
        )
        if cash is None:
            raise MCPError(f"no cash/buying power in account payload: {payload}")
        return cash

    def get_positions(self) -> dict[str, Position]:
        payload = self._call("get_positions", {})
        rows = _find_position_rows(payload)
        positions: dict[str, Position] = {}
        for row in rows:
            symbol = _dig(row, ("symbol", "ticker"))
            qty = _decimal(_dig(row, ("qty", "quantity", "shares")))
            if not symbol or qty is None:
                continue
            avg = _decimal(
                _dig(row, ("avg_cost", "average_buy_price", "average_price", "avg_price"))
            )
            positions[str(symbol)] = Position(
                symbol=str(symbol), qty=qty, avg_cost=avg or Decimal("0")
            )
        return positions

    def as_risk_bridge(self) -> BrokerBridge:
        """This broker wired into the risk manager's BrokerAdapter protocol."""
        return BrokerBridge(
            self,  # duck-typed: BrokerBridge only forwards the callables below
            cash_fn=self.get_cash,
            positions_fn=self.get_positions,
            quote_fn=self.get_quote,
        )


def _find_position_rows(payload: Any) -> list[dict]:
    """Locate the list of position dicts wherever the tool nested it."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("positions", "holdings", "results", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
        for value in payload.values():
            rows = _find_position_rows(value)
            if rows:
                return rows
        if _dig(payload, ("symbol", "ticker")) is not None:
            return [payload]
    return []
