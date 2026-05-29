#!/usr/bin/env python3
"""Mercado Livre Analytics — MCP Server"""

import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Any

import httpx
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from auth import get_seller_id, get_valid_access_token

ML_API_BASE = "https://api.mercadolibre.com"
server = Server("mercado-livre-analytics")


def _client_creds() -> tuple[str, str]:
    cid = os.environ.get("ML_CLIENT_ID", "")
    sec = os.environ.get("ML_CLIENT_SECRET", "")
    if not cid or not sec:
        raise RuntimeError("ML_CLIENT_ID e ML_CLIENT_SECRET devem estar configurados.")
    return cid, sec


async def _headers() -> dict:
    cid, sec = _client_creds()
    token = await get_valid_access_token(cid, sec)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_orders",
            description="Lista pedidos do vendedor autenticado no Mercado Livre.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Status: paid | cancelled | payment_required | payment_in_process",
                        "default": "paid",
                    },
                    "date_from": {"type": "string", "description": "Data inicial YYYY-MM-DD"},
                    "date_to":   {"type": "string", "description": "Data final YYYY-MM-DD"},
                    "limit":  {"type": "integer", "description": "Máx de resultados (≤50)", "default": 50},
                    "offset": {"type": "integer", "description": "Offset para paginação", "default": 0},
                },
            },
        ),
        types.Tool(
            name="get_sales",
            description="Resumo de vendas (total de pedidos, valor total, média) em um período.",
            inputSchema={
                "type": "object",
                "properties": {
                    "date_from": {"type": "string", "description": "Data inicial YYYY-MM-DD"},
                    "date_to":   {"type": "string", "description": "Data final YYYY-MM-DD"},
                },
            },
        ),
        types.Tool(
            name="get_products",
            description="Lista anúncios/produtos do vendedor com preço, estoque e quantidade vendida.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Status do anúncio: active | paused | closed | under_review",
                        "default": "active",
                    },
                    "limit":  {"type": "integer", "description": "Máx de resultados (≤50)", "default": 50},
                    "offset": {"type": "integer", "description": "Offset para paginação", "default": 0},
                },
            },
        ),
        types.Tool(
            name="get_visits",
            description="Estatísticas de visitas aos anúncios do vendedor em um período.",
            inputSchema={
                "type": "object",
                "properties": {
                    "date_from": {"type": "string", "description": "Data inicial YYYY-MM-DD"},
                    "date_to":   {"type": "string", "description": "Data final YYYY-MM-DD"},
                    "item_id":   {"type": "string", "description": "ID de anúncio específico (ex: MLB123456). Se omitido, retorna total do vendedor."},
                },
            },
        ),
        types.Tool(
            name="get_reputation",
            description="Reputação e métricas de qualidade do vendedor (nível, reclamações, cancelamentos, atrasos).",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="get_financial_summary",
            description="Resumo financeiro: receita bruta, comissões do ML e receita líquida em um período.",
            inputSchema={
                "type": "object",
                "properties": {
                    "date_from": {"type": "string", "description": "Data inicial YYYY-MM-DD"},
                    "date_to":   {"type": "string", "description": "Data final YYYY-MM-DD"},
                },
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            hdrs = await _headers()
            seller_id = get_seller_id()

            dispatch = {
                "get_orders":           _get_orders,
                "get_sales":            _get_sales,
                "get_products":         _get_products,
                "get_visits":           _get_visits,
                "get_reputation":       _get_reputation,
                "get_financial_summary": _get_financial_summary,
            }

            if name not in dispatch:
                result = {"error": f"Ferramenta desconhecida: {name}"}
            else:
                result = await dispatch[name](client, hdrs, seller_id, arguments)

    except httpx.HTTPStatusError as e:
        result = {
            "error": f"Erro HTTP {e.response.status_code} na API do Mercado Livre",
            "detail": e.response.text[:500],
        }
    except RuntimeError as e:
        result = {"error": str(e)}
    except Exception as e:
        result = {"error": f"Erro inesperado: {e}"}

    return [types.TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def _get_orders(client, hdrs, seller_id, args):
    params: dict = {
        "seller": seller_id,
        "order.status": args.get("status", "paid"),
        "limit": min(int(args.get("limit", 50)), 50),
        "offset": int(args.get("offset", 0)),
        "sort": "date_desc",
    }
    if "date_from" in args:
        params["order.date_created.from"] = f"{args['date_from']}T00:00:00.000-00:00"
    if "date_to" in args:
        params["order.date_created.to"] = f"{args['date_to']}T23:59:59.000-00:00"

    resp = await client.get(f"{ML_API_BASE}/orders/search", headers=hdrs, params=params)
    resp.raise_for_status()
    return resp.json()


async def _get_sales(client, hdrs, seller_id, args):
    today = datetime.now()
    date_from = args.get("date_from", (today - timedelta(days=30)).strftime("%Y-%m-%d"))
    date_to   = args.get("date_to",   today.strftime("%Y-%m-%d"))

    params = {
        "seller": seller_id,
        "order.status": "paid",
        "order.date_created.from": f"{date_from}T00:00:00.000-00:00",
        "order.date_created.to":   f"{date_to}T23:59:59.000-00:00",
        "limit": 50,
        "sort": "date_desc",
    }
    resp = await client.get(f"{ML_API_BASE}/orders/search", headers=hdrs, params=params)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [])

    total_revenue = sum(o.get("total_amount", 0) for o in results)
    total_orders  = data.get("paging", {}).get("total", 0)
    currency      = results[0].get("currency_id", "BRL") if results else "BRL"
    avg_ticket    = round(total_revenue / len(results), 2) if results else 0

    return {
        "period":       {"from": date_from, "to": date_to},
        "currency":     currency,
        "total_orders": total_orders,
        "sampled":      len(results),
        "total_revenue_sampled": round(total_revenue, 2),
        "avg_ticket_sampled":    avg_ticket,
        "note": "Valores baseados nos primeiros 50 pedidos. Use get_orders com paginação para o total completo.",
        "recent_orders": [
            {
                "id":           o.get("id"),
                "date_created": o.get("date_created"),
                "total_amount": o.get("total_amount"),
                "status":       o.get("status"),
                "items":        len(o.get("order_items", [])),
            }
            for o in results[:10]
        ],
    }


async def _get_products(client, hdrs, seller_id, args):
    status = args.get("status", "active")
    limit  = min(int(args.get("limit", 50)), 50)
    offset = int(args.get("offset", 0))

    resp = await client.get(
        f"{ML_API_BASE}/users/{seller_id}/items/search",
        headers=hdrs,
        params={"status": status, "limit": limit, "offset": offset},
    )
    resp.raise_for_status()
    search_data = resp.json()
    item_ids = search_data.get("results", [])

    if not item_ids:
        return {"total": 0, "offset": offset, "limit": limit, "items": []}

    ids_str = ",".join(item_ids[:20])
    detail_resp = await client.get(
        f"{ML_API_BASE}/items", headers=hdrs, params={"ids": ids_str}
    )
    detail_resp.raise_for_status()

    items = []
    for entry in detail_resp.json():
        if entry.get("code") == 200:
            b = entry.get("body", {})
            items.append({
                "id":                 b.get("id"),
                "title":              b.get("title"),
                "price":              b.get("price"),
                "currency_id":        b.get("currency_id"),
                "available_quantity": b.get("available_quantity"),
                "sold_quantity":      b.get("sold_quantity"),
                "status":             b.get("status"),
                "listing_type_id":    b.get("listing_type_id"),
                "category_id":        b.get("category_id"),
                "permalink":          b.get("permalink"),
            })

    return {
        "total":  search_data.get("paging", {}).get("total", 0),
        "offset": offset,
        "limit":  limit,
        "items":  items,
    }


async def _get_visits(client, hdrs, seller_id, args):
    today = datetime.now()
    date_from = args.get("date_from", (today - timedelta(days=30)).strftime("%Y-%m-%d"))
    date_to   = args.get("date_to",   today.strftime("%Y-%m-%d"))

    if "item_id" in args:
        item_id = args["item_id"]
        resp = await client.get(
            f"{ML_API_BASE}/items/visits",
            headers=hdrs,
            params={"ids": item_id, "date_from": date_from, "date_to": date_to},
        )
    else:
        resp = await client.get(
            f"{ML_API_BASE}/users/{seller_id}/items_visits",
            headers=hdrs,
            params={"date_from": date_from, "date_to": date_to},
        )

    resp.raise_for_status()
    return resp.json()


async def _get_reputation(client, hdrs, seller_id, args):
    resp = await client.get(f"{ML_API_BASE}/users/{seller_id}", headers=hdrs)
    resp.raise_for_status()
    data = resp.json()
    rep  = data.get("seller_reputation", {})

    return {
        "user_id":  data.get("id"),
        "nickname": data.get("nickname"),
        "site_id":  data.get("site_id"),
        "status":   data.get("status"),
        "reputation": {
            "level_id":           rep.get("level_id"),
            "power_seller_status": rep.get("power_seller_status"),
            "real_level":          rep.get("real_level"),
            "transactions":        rep.get("transactions", {}),
            "metrics":             rep.get("metrics", {}),
        },
    }


async def _get_financial_summary(client, hdrs, seller_id, args):
    today = datetime.now()
    date_from = args.get("date_from", (today - timedelta(days=30)).strftime("%Y-%m-%d"))
    date_to   = args.get("date_to",   today.strftime("%Y-%m-%d"))

    params = {
        "seller": seller_id,
        "order.status": "paid",
        "order.date_created.from": f"{date_from}T00:00:00.000-00:00",
        "order.date_created.to":   f"{date_to}T23:59:59.000-00:00",
        "limit": 50,
    }
    resp = await client.get(f"{ML_API_BASE}/orders/search", headers=hdrs, params=params)
    resp.raise_for_status()
    data    = resp.json()
    results = data.get("results", [])

    total_revenue  = 0.0
    total_fees     = 0.0
    total_shipping = 0.0

    for order in results:
        total_revenue += order.get("total_amount", 0)
        for payment in order.get("payments", []):
            total_shipping += payment.get("shipping_cost", 0)
        for item in order.get("order_items", []):
            total_fees += item.get("sale_fee", 0)

    currency = results[0].get("currency_id", "BRL") if results else "BRL"

    return {
        "period":              {"from": date_from, "to": date_to},
        "currency":            currency,
        "total_orders":        data.get("paging", {}).get("total", 0),
        "sampled":             len(results),
        "total_revenue":       round(total_revenue, 2),
        "total_fees":          round(total_fees, 2),
        "total_shipping_cost": round(total_shipping, 2),
        "net_revenue":         round(total_revenue - total_fees, 2),
        "note": "Valores baseados nos primeiros 50 pedidos. Use get_orders com paginação para o total completo.",
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
