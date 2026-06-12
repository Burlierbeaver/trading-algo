from __future__ import annotations

import json
from decimal import Decimal
from uuid import uuid4

import pytest

from alpaca_broker_adapter import OrderRequest, OrderSide, OrderStatus
from trading_algo.bridges.robinhood_mcp import (
    MCPError,
    OrdersDisabled,
    RobinhoodMCPBroker,
    ToolNotFound,
    adapt_args,
    parse_http_response,
    parse_status,
    resolve_tools,
)
from trading_algo.fakes import FakeNLP
from trading_algo.pipeline import Pipeline

# A plausible Robinhood Agentic Trading tool surface. The adapter must not
# depend on these exact names — discovery + schema adaptation handle it.
RH_TOOLS = [
    {
        "name": "place_equity_order",
        "description": "Place a buy or sell order for an equity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "side": {"type": "string"},
                "quantity": {"type": "number"},
                "amount_in_dollars": {"type": "number"},
                "type": {"type": "string"},
                "limit_price": {"type": "number"},
                "time_in_force": {"type": "string"},
                "client_order_id": {"type": "string"},
            },
        },
    },
    {
        "name": "get_stock_quote",
        "description": "Latest market quote for a symbol.",
        "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string"}}},
    },
    {
        "name": "get_portfolio_positions",
        "description": "Current portfolio holdings.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_account_details",
        "description": "Account info including buying power.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "cancel_equity_order",
        "description": "Cancel an open order.",
        "inputSchema": {"type": "object", "properties": {"order_id": {"type": "string"}}},
    },
]


class FakeTransport:
    """Scripted MCP server: answers the handshake, tools/list, and routes
    tools/call to canned per-tool results."""

    def __init__(self, tools=None, results=None):
        self.tools = RH_TOOLS if tools is None else tools
        self.results = results or {}
        self.tool_calls: list[tuple[str, dict]] = []
        self.notifications: list[dict] = []

    def request(self, payload):
        if "id" not in payload:
            self.notifications.append(payload)
            return None
        method = payload["method"]
        if method == "initialize":
            result = {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "robinhood-trading", "version": "beta"},
                "capabilities": {"tools": {}},
            }
        elif method == "tools/list":
            result = {"tools": self.tools}
        elif method == "tools/call":
            name = payload["params"]["name"]
            self.tool_calls.append((name, payload["params"]["arguments"]))
            data = self.results[name]
            # wrap raw payloads in the MCP tools/call result envelope
            if {"content", "structuredContent", "isError"} & set(data):
                result = data
            else:
                result = {
                    "structuredContent": data,
                    "content": [{"type": "text", "text": json.dumps(data)}],
                }
        else:
            raise AssertionError(f"unexpected method {method}")
        return {"jsonrpc": "2.0", "id": payload["id"], "result": result}


def make_broker(*, allow_orders=False, results=None, tools=None, tool_map=None):
    transport = FakeTransport(tools=tools, results=results)
    broker = RobinhoodMCPBroker(
        transport=transport, allow_orders=allow_orders, tool_map=tool_map
    )
    return broker, transport


def market_buy(qty="4.2000"):
    return OrderRequest(
        symbol="AAPL",
        side=OrderSide.BUY,
        qty=Decimal(qty),
        client_order_id=uuid4(),
    )


# ── discovery ─────────────────────────────────────────────────────────


def test_resolves_capabilities_from_discovered_tools():
    resolved = resolve_tools(RH_TOOLS)
    assert resolved == {
        "place_order": "place_equity_order",
        "get_quote": "get_stock_quote",
        "get_positions": "get_portfolio_positions",
        "get_account": "get_account_details",
        "cancel_order": "cancel_equity_order",
    }


def test_unresolvable_capability_raises_with_hint():
    broker, _ = make_broker(tools=[RH_TOOLS[0]])  # order tool only
    with pytest.raises(ToolNotFound, match="get_quote"):
        broker.get_quote("AAPL")


def test_tool_map_override_pins_a_tool():
    results = {"weird_quote_thing": {"price": "188.10"}}
    tools = [
        {"name": "weird_quote_thing", "description": "", "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string"}}}}
    ]
    broker, _ = make_broker(tools=tools, results=results, tool_map={"get_quote": "weird_quote_thing"})
    assert broker.get_quote("AAPL") == Decimal("188.10")


# ── safety ────────────────────────────────────────────────────────────


def test_orders_disabled_by_default_and_nothing_transmitted(monkeypatch):
    monkeypatch.delenv("ROBINHOOD_MCP_ALLOW_ORDERS", raising=False)
    transport = FakeTransport()
    broker = RobinhoodMCPBroker(transport=transport)
    with pytest.raises(OrdersDisabled):
        broker.execute_order(market_buy())
    assert transport.tool_calls == []


def test_env_var_enables_orders(monkeypatch):
    monkeypatch.setenv("ROBINHOOD_MCP_ALLOW_ORDERS", "true")
    transport = FakeTransport(
        results={"place_equity_order": {"order": {"id": "RH-1", "state": "queued"}}}
    )
    broker = RobinhoodMCPBroker(transport=transport)
    result = broker.execute_order(market_buy())
    assert result.broker_order_id == "RH-1"
    assert result.status is OrderStatus.SUBMITTED


# ── order placement ───────────────────────────────────────────────────


def test_execute_order_adapts_args_to_tool_schema():
    broker, transport = make_broker(
        allow_orders=True,
        results={"place_equity_order": {"order": {"id": "RH-2", "state": "confirmed"}}},
    )
    broker.execute_order(market_buy())

    (name, args), = transport.tool_calls
    assert name == "place_equity_order"
    # qty renamed to the schema's "quantity" and coerced to number
    assert args["quantity"] == pytest.approx(4.2)
    assert args["side"] == "buy"
    assert args["type"] == "market"
    assert args["time_in_force"] == "day"
    assert "notional" not in args and "amount_in_dollars" not in args


def test_execute_order_notional_maps_to_dollar_amount():
    broker, transport = make_broker(
        allow_orders=True,
        results={"place_equity_order": {"order": {"id": "RH-3", "state": "queued"}}},
    )
    order = OrderRequest(symbol="MSFT", side=OrderSide.BUY, notional=Decimal("250.00"))
    broker.execute_order(order)

    (_, args), = transport.tool_calls
    assert args["amount_in_dollars"] == pytest.approx(250.0)
    assert "quantity" not in args


def test_execute_order_parses_fill_result():
    broker, _ = make_broker(
        allow_orders=True,
        results={
            "place_equity_order": {
                "order": {
                    "id": "RH-4",
                    "state": "filled",
                    "filled_quantity": "4.2",
                    "average_price": "150.00",
                    "created_at": "2026-06-12T10:00:00Z",
                }
            }
        },
    )
    order = market_buy()
    result = broker.execute_order(order)

    assert result.client_order_id == order.client_order_id
    assert result.broker_order_id == "RH-4"
    assert result.status is OrderStatus.FILLED
    assert result.filled_qty == Decimal("4.2")
    assert result.filled_avg_price == Decimal("150.00")
    assert result.submitted_at.isoformat() == "2026-06-12T10:00:00+00:00"


def test_tool_error_raises_mcp_error():
    class ErroringTransport(FakeTransport):
        def request(self, payload):
            message = super().request(payload)
            if message and payload.get("method") == "tools/call":
                message["result"] = {
                    "isError": True,
                    "content": [{"type": "text", "text": "insufficient buying power"}],
                }
            return message

    transport = ErroringTransport(results={"place_equity_order": {}})
    broker = RobinhoodMCPBroker(transport=transport, allow_orders=True)
    with pytest.raises(MCPError, match="insufficient buying power"):
        broker.execute_order(market_buy())


# ── read-only surface ─────────────────────────────────────────────────


def test_get_quote_from_text_content():
    class TextQuoteTransport(FakeTransport):
        def request(self, payload):
            message = super().request(payload)
            if message and payload.get("method") == "tools/call":
                message["result"] = {
                    "content": [
                        {"type": "text", "text": json.dumps({"symbol": "AAPL", "last_trade_price": "187.66"})}
                    ]
                }
            return message

    broker = RobinhoodMCPBroker(transport=TextQuoteTransport(results={"get_stock_quote": {}}))
    assert broker.get_quote("AAPL") == Decimal("187.66")


def test_get_cash_reads_buying_power():
    broker, _ = make_broker(
        results={"get_account_details": {"account": {"buying_power": "10000.50", "currency": "USD"}}}
    )
    assert broker.get_cash() == Decimal("10000.50")


def test_get_positions_parses_holdings():
    broker, _ = make_broker(
        results={
            "get_portfolio_positions": {
                "positions": [
                    {"symbol": "AAPL", "quantity": "10", "average_buy_price": "150.00"},
                    {"symbol": "MSFT", "quantity": "2.5", "average_buy_price": "400.00"},
                    {"note": "not a position"},
                ]
            }
        }
    )
    positions = broker.get_positions()
    assert set(positions) == {"AAPL", "MSFT"}
    assert positions["AAPL"].qty == Decimal("10")
    assert positions["AAPL"].avg_cost == Decimal("150.00")


def test_as_risk_bridge_forwards_reads():
    broker, _ = make_broker(
        results={
            "get_account_details": {"buying_power": "5000"},
            "get_portfolio_positions": {"positions": []},
            "get_stock_quote": {"price": "187.66"},
        }
    )
    bridge = broker.as_risk_bridge()
    assert bridge.get_cash() == Decimal("5000")
    assert bridge.get_positions() == {}
    assert bridge.get_quote("AAPL") == Decimal("187.66")


# ── unit helpers ──────────────────────────────────────────────────────


def test_parse_status_mapping():
    assert parse_status("Filled") is OrderStatus.FILLED
    assert parse_status("partially filled") is OrderStatus.PARTIALLY_FILLED
    assert parse_status("cancelled") is OrderStatus.CANCELED
    assert parse_status("failed") is OrderStatus.REJECTED
    assert parse_status("queued") is OrderStatus.SUBMITTED
    assert parse_status(None) is OrderStatus.SUBMITTED
    assert parse_status("something_new") is OrderStatus.SUBMITTED


def test_adapt_args_passthrough_without_schema():
    args = {"symbol": "AAPL", "qty": "1", "limit_price": None}
    assert adapt_args(args, None) == {"symbol": "AAPL", "qty": "1"}


def test_parse_http_response_json_and_sse():
    json_msg = parse_http_response("application/json", '{"jsonrpc":"2.0","id":7,"result":{}}', 7)
    assert json_msg["id"] == 7

    sse_body = (
        'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress"}\n\n'
        'data: {"jsonrpc":"2.0","id":8,"result":{"ok":true}}\n\n'
    )
    sse_msg = parse_http_response("text/event-stream", sse_body, 8)
    assert sse_msg["result"] == {"ok": True}

    assert parse_http_response("application/json", "", None) is None
    with pytest.raises(MCPError):
        parse_http_response("text/event-stream", sse_body, 99)


def test_initialized_notification_sent_after_handshake():
    broker, transport = make_broker(results={"get_stock_quote": {"price": "1"}})
    broker.get_quote("AAPL")
    assert any(
        n.get("method") == "notifications/initialized" for n in transport.notifications
    )


# ── pipeline integration ──────────────────────────────────────────────


async def test_pipeline_executes_through_robinhood_broker(raw_event, risk_engine):
    broker, transport = make_broker(
        allow_orders=True,
        results={
            "place_equity_order": {
                "order": {"id": "RH-9", "state": "filled", "filled_quantity": "4.2", "average_price": "150.00"}
            }
        },
    )
    pipeline = Pipeline(nlp=FakeNLP(), risk=risk_engine, broker=broker)

    result = await pipeline.ingest(raw_event)

    assert len(result.executed) == 1
    assert result.executed[0].broker_order_id == "RH-9"
    assert result.executed[0].status is OrderStatus.FILLED
    assert transport.tool_calls[0][0] == "place_equity_order"


async def test_pipeline_orders_disabled_yields_no_fills(raw_event, risk_engine, monkeypatch):
    monkeypatch.delenv("ROBINHOOD_MCP_ALLOW_ORDERS", raising=False)
    broker, transport = make_broker()  # read-only default
    pipeline = Pipeline(nlp=FakeNLP(), risk=risk_engine, broker=broker)

    result = await pipeline.ingest(raw_event)

    # risk approved it, but the broker refused to transmit
    assert len(result.approved) == 1
    assert result.executed == []
    assert transport.tool_calls == []
