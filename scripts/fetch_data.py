#!/usr/bin/env python3
"""
scripts/fetch_data.py — Busca dados da API do Mercado Livre → gera snapshot JSON.

Uso:
    python scripts/fetch_data.py [--client ziyou] [--days 30]

Fluxo:
    1. Lê clients/{client}/config.json
    2. Autentica com ML_CLIENT_ID + ML_CLIENT_SECRET
    3. Faz chamadas paralelas à API do ML
    4. Salva clients/{client}/snapshots/YYYY-MM-DD.json
    5. Chama build.py --client {client} para atualizar public/
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from auth import get_valid_access_token, get_seller_id

ML_API = "https://api.mercadolibre.com"


# ─────────────────────────────────────────────
# Config loader
# ─────────────────────────────────────────────

def load_client_config(client_id: str) -> dict:
    path = ROOT / "clients" / client_id / "config.json"
    if not path.exists():
        raise SystemExit(f"[fetch] Config não encontrado: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# ─────────────────────────────────────────────
# ML API helpers
# ─────────────────────────────────────────────

async def _get_products(c, h, seller_id, config):
    category_map = config.get("category_map", {})
    r = await c.get(
        f"{ML_API}/users/{seller_id}/items/search",
        headers=h,
        params={"status": "active", "limit": 50},
    )
    r.raise_for_status()
    data   = r.json()
    ids    = data.get("results", [])
    paging = data.get("paging", {})

    if not ids:
        return {"total": 0, "items": []}

    dr = await c.get(f"{ML_API}/items", headers=h, params={"ids": ",".join(ids[:20])})
    dr.raise_for_status()

    items = []
    for entry in dr.json():
        if entry.get("code") == 200:
            b = entry["body"]
            items.append({
                "id":           b.get("id"),
                "title":        b.get("title"),
                "price":        b.get("price", 0),
                "stock":        b.get("available_quantity", 0),
                "sold":         b.get("sold_quantity", 0),
                "visits":       0,
                "status":       b.get("status", "active"),
                "listing_type": b.get("listing_type_id", ""),
                "category":     category_map.get(b.get("category_id", ""), "Outros"),
                "permalink":    b.get("permalink", ""),
            })

    return {"total": paging.get("total", len(items)), "items": items}


async def _get_visits_total(c, h, seller_id, date_from, date_to):
    r = await c.get(
        f"{ML_API}/users/{seller_id}/items_visits",
        headers=h,
        params={"date_from": date_from, "date_to": date_to},
    )
    r.raise_for_status()
    return r.json()


async def _get_visits_item(c, h, item_id, date_from, date_to):
    r = await c.get(
        f"{ML_API}/items/visits",
        headers=h,
        params={"ids": item_id, "date_from": date_from, "date_to": date_to},
    )
    r.raise_for_status()
    result = r.json()
    if isinstance(result, list) and result:
        return result[0].get("total_visits", 0)
    return 0


async def _get_orders(c, h, seller_id, date_from, date_to):
    params = {
        "seller": seller_id,
        "order.status": "paid",
        "order.date_created.from": f"{date_from}T00:00:00.000-00:00",
        "order.date_created.to":   f"{date_to}T23:59:59.000-00:00",
        "limit": 50,
        "sort":  "date_desc",
    }
    r = await c.get(f"{ML_API}/orders/search", headers=h, params=params)
    r.raise_for_status()
    data    = r.json()
    results = data.get("results", [])

    total_rev = sum(o.get("total_amount", 0) for o in results)
    total_ord = data.get("paging", {}).get("total", 0)
    avg       = round(total_rev / len(results), 2) if results else 0

    return {
        "total_orders":  total_ord,
        "sampled":       len(results),
        "total_revenue": round(total_rev, 2),
        "avg_ticket":    avg,
        "daily":         _daily_series(results, date_from, date_to),
        "recent": [
            {
                "id":     o.get("id"),
                "date":   o.get("date_created"),
                "total":  o.get("total_amount"),
                "status": o.get("status"),
                "items":  len(o.get("order_items", [])),
            }
            for o in results[:10]
        ],
    }


async def _get_financial(c, h, seller_id, date_from, date_to):
    params = {
        "seller": seller_id,
        "order.status": "paid",
        "order.date_created.from": f"{date_from}T00:00:00.000-00:00",
        "order.date_created.to":   f"{date_to}T23:59:59.000-00:00",
        "limit": 50,
    }
    r = await c.get(f"{ML_API}/orders/search", headers=h, params=params)
    r.raise_for_status()
    data    = r.json()
    results = data.get("results", [])

    revenue  = sum(o.get("total_amount", 0) for o in results)
    fees     = sum(i.get("sale_fee", 0) for o in results for i in o.get("order_items", []))
    shipping = sum(p.get("shipping_cost", 0) for o in results for p in o.get("payments", []))

    return {
        "total_orders":        data.get("paging", {}).get("total", 0),
        "total_revenue":       round(revenue, 2),
        "total_fees":          round(fees, 2),
        "total_shipping_cost": round(shipping, 2),
        "net_revenue":         round(revenue - fees, 2),
    }


async def _get_reputation(c, h, seller_id):
    r = await c.get(f"{ML_API}/users/{seller_id}", headers=h)
    r.raise_for_status()
    d   = r.json()
    rep = d.get("seller_reputation", {})
    st  = d.get("status", {})

    return {
        "user_id":         d.get("id"),
        "nickname":        d.get("nickname"),
        "site_id":         d.get("site_id"),
        "mercadoenvios":   st.get("mercadoenvios", "not_accepted") == "accepted",
        "account_type":    st.get("mercadopago_account_type", "personal"),
        "confirmed_email": st.get("confirmed_email", True),
        "reputation": {
            "level_id":            rep.get("level_id"),
            "power_seller_status": rep.get("power_seller_status"),
            "transactions":        rep.get("transactions", {}),
            "metrics":             rep.get("metrics", {}),
        },
    }


# ─────────────────────────────────────────────
# Health Score engine  (0-100)
# ─────────────────────────────────────────────

def compute_health_score(products: list, kpis: dict, account: dict, config: dict) -> dict:
    """
    Calcula o Marketplace Health Score de 0 a 100.

    Critérios e pesos:
        Visitas          20 pts
        Conversão        25 pts  (suavizado para lojas novas < 30 visitas)
        Sem visitas      15 pts
        Estoque parado   15 pts
        Cobertura        10 pts
        Vendas           15 pts
    """
    tv   = kpis.get("total_visits", 0)
    ts   = kpis.get("total_sales",  0)
    n    = max(1, len(products))
    vpl  = tv / n                              # visitas por listing
    cvr  = ts / max(1, tv) if tv > 0 else 0   # taxa de conversão

    no_visit   = [p for p in products if not p.get("visits", 0)]
    idle       = [p for p in products if p.get("stock", 0) >= 15 and not p.get("visits", 0)]
    with_visit = [p for p in products if p.get("visits", 0) > 0]

    nv_pct  = len(no_visit)   / n
    id_pct  = len(idle)       / n
    cov_pct = len(with_visit) / n

    bd: dict[str, int] = {}

    # ── Visitas (20)
    if   vpl >= 20: bd["visits"] = 20
    elif vpl >= 10: bd["visits"] = 17
    elif vpl >= 5:  bd["visits"] = 13
    elif vpl >= 2:  bd["visits"] = 9
    elif vpl >= 1:  bd["visits"] = 5
    else:           bd["visits"] = max(1, round(vpl * 4))

    # ── Conversão (25) — loja nova (<30 visitas) recebe nota neutra
    if tv < 30:
        bd["conversion"] = 13          # cedo demais para julgar
    elif cvr >= 0.05: bd["conversion"] = 25
    elif cvr >= 0.03: bd["conversion"] = 20
    elif cvr >= 0.01: bd["conversion"] = 14
    elif cvr > 0:     bd["conversion"] = 7
    else:             bd["conversion"] = 0

    # ── Produtos sem visitas (15)
    if   nv_pct == 0:    bd["no_visits"] = 15
    elif nv_pct <= 0.15: bd["no_visits"] = 12
    elif nv_pct <= 0.35: bd["no_visits"] = 9
    elif nv_pct <= 0.55: bd["no_visits"] = 5
    elif nv_pct <= 0.75: bd["no_visits"] = 2
    else:                bd["no_visits"] = 0

    # ── Estoque parado (15): stock >= 15 e 0 visitas
    if   id_pct == 0:    bd["idle_stock"] = 15
    elif id_pct <= 0.15: bd["idle_stock"] = 12
    elif id_pct <= 0.35: bd["idle_stock"] = 8
    elif id_pct <= 0.55: bd["idle_stock"] = 4
    else:                bd["idle_stock"] = 1

    # ── Cobertura do catálogo (10)
    if   cov_pct >= 0.9:  bd["coverage"] = 10
    elif cov_pct >= 0.7:  bd["coverage"] = 8
    elif cov_pct >= 0.5:  bd["coverage"] = 6
    elif cov_pct >= 0.3:  bd["coverage"] = 3
    else:                 bd["coverage"] = 1

    # ── Vendas (15)
    if   ts >= 20: bd["sales"] = 15
    elif ts >= 10: bd["sales"] = 12
    elif ts >= 5:  bd["sales"] = 9
    elif ts >= 2:  bd["sales"] = 6
    elif ts >= 1:  bd["sales"] = 3
    else:          bd["sales"] = 0

    # Bônus Mercado Envios (até +3)
    bonus = 3 if account.get("mercadoenvios", False) else 0
    total = min(100, sum(bd.values()) + bonus)

    # Level e cor
    if   total >= 80: level, color, emoji = "Excelente", "#22d3a0", "🏆"
    elif total >= 60: level, color, emoji = "Bom",       "#4f8ef7", "✅"
    elif total >= 40: level, color, emoji = "Regular",   "#ffe600", "⚠️"
    else:             level, color, emoji = "Crítico",   "#ef4444", "🚨"

    # ── Ações prioritárias (ordenadas por impacto estimado)
    actions: list[dict] = []

    if bd.get("visits", 0) <= 5:
        actions.append({
            "priority": 1,
            "label":    "Ativar ML Ads",
            "body":     "Produto Patrocinado aumenta visitas imediatamente sem alterar o catálogo.",
            "impact":   "alto",
        })
    if not account.get("mercadoenvios", False):
        actions.append({
            "priority": 2,
            "label":    "Habilitar Mercado Envios",
            "body":     "Ativa o filtro 'Frete grátis' e o selo Full — aumenta CTR organicamente.",
            "impact":   "alto",
        })
    if nv_pct > 0.4:
        actions.append({
            "priority": 3,
            "label":    f"Revisar {len(no_visit)} anúncio{'s' if len(no_visit)>1 else ''} sem visitas",
            "body":     "Inclua palavras-chave populares no título e substitua fotos por imagens de lifestyle.",
            "impact":   "médio",
        })
    if id_pct > 0.3:
        actions.append({
            "priority": 4,
            "label":    "Reduzir estoque parado",
            "body":     "Crie promoção temporária (5-10% de desconto) nos produtos com estoque alto e zero visitas.",
            "impact":   "médio",
        })
    if bd.get("conversion", 0) == 0 and tv >= 30:
        actions.append({
            "priority": 5,
            "label":    "Melhorar taxa de conversão",
            "body":     "Reduza o preço dos produtos mais visitados em 5-10% e teste o impacto em 7 dias.",
            "impact":   "alto",
        })
    if cov_pct < 0.5:
        actions.append({
            "priority": 6,
            "label":    "Aumentar cobertura do catálogo",
            "body":     "Adicione termos de busca ao título dos anúncios invisíveis para aparecer em mais pesquisas.",
            "impact":   "médio",
        })

    # Por categoria
    cat_scores: dict[str, dict] = {}
    cats = {}
    for p in products:
        cat = p.get("category", "Outros")
        if cat not in cats:
            cats[cat] = {"products": [], "visits": 0, "sales": 0}
        cats[cat]["products"].append(p)
        cats[cat]["visits"] += p.get("visits", 0)
        cats[cat]["sales"]  += p.get("sold",   0)

    for cat, c_data in cats.items():
        ps    = c_data["products"]
        c_tv  = c_data["visits"]
        c_ts  = c_data["sales"]
        c_n   = max(1, len(ps))
        c_nv  = len([p for p in ps if not p.get("visits", 0)]) / c_n
        c_cov = len([p for p in ps if p.get("visits", 0) > 0]) / c_n
        c_cvr = c_ts / max(1, c_tv)

        s = 0
        s += min(20, round((c_tv / c_n) * 4))
        s += 13 if c_tv < 10 else (25 if c_cvr >= 0.05 else 15 if c_cvr > 0 else 0)
        s += round((1 - c_nv) * 15)
        s += round(c_cov * 10)
        cat_scores[cat] = {
            "score":    min(100, s),
            "visits":   c_tv,
            "products": c_n,
            "coverage": round(c_cov * 100, 1),
        }

    return {
        "total":   total,
        "level":   level,
        "color":   color,
        "emoji":   emoji,
        "bonus":   bonus,
        "breakdown": {
            "visits":     {"score": bd.get("visits", 0),     "max": 20, "label": "Visitas"},
            "conversion": {"score": bd.get("conversion", 0), "max": 25, "label": "Conversão"},
            "no_visits":  {"score": bd.get("no_visits", 0),  "max": 15, "label": "Sem Visitas"},
            "idle_stock": {"score": bd.get("idle_stock", 0), "max": 15, "label": "Estoque Parado"},
            "coverage":   {"score": bd.get("coverage", 0),   "max": 10, "label": "Cobertura"},
            "sales":      {"score": bd.get("sales", 0),      "max": 15, "label": "Vendas"},
        },
        "details": {
            "visits_per_listing": round(vpl, 2),
            "conversion_rate":    round(cvr * 100, 2),
            "no_visit_pct":       round(nv_pct  * 100, 1),
            "idle_stock_pct":     round(id_pct  * 100, 1),
            "coverage_pct":       round(cov_pct * 100, 1),
        },
        "actions":        actions[:3],
        "category_scores": cat_scores,
    }


# ─────────────────────────────────────────────
# Insights engine (server-side, embeds no JSON)
# ─────────────────────────────────────────────

def _compute_insights(products: list, kpis: dict, account: dict, config: dict) -> list:
    cfg        = config.get("insights", {})
    low_visits = cfg.get("low_visit_threshold", 2)
    hslv_ratio = cfg.get("high_stock_low_visit_ratio", 10)

    insights = []

    sorted_by_visits = sorted(products, key=lambda p: p.get("visits", 0), reverse=True)
    no_visit         = [p for p in products if p.get("visits", 0) == 0]
    total_visits     = kpis.get("total_visits", 0)
    total_sales      = kpis.get("total_sales", 0)

    # ── Top 3 mais visitados
    top3 = sorted_by_visits[:3]
    if top3 and top3[0].get("visits", 0) > 0:
        insights.append({
            "type":  "ranking",
            "title": "Produtos mais visitados",
            "items": [
                {
                    "rank":    i + 1,
                    "id":      p["id"],
                    "title":   p["title"],
                    "visits":  p.get("visits", 0),
                    "share":   round(p.get("visits", 0) / max(1, total_visits) * 100, 1),
                    "stock":   p.get("stock", 0),
                    "permalink": p.get("permalink", ""),
                }
                for i, p in enumerate(top3)
            ],
        })

    # ── Sem visitas
    if no_visit:
        insights.append({
            "type":  "no_visits",
            "title": "Produtos sem nenhuma visita",
            "count": len(no_visit),
            "items": [
                {"id": p["id"], "title": p["title"], "stock": p.get("stock", 0), "permalink": p.get("permalink", "")}
                for p in no_visit[:5]
            ],
        })

    # ── Estoque alto, procura baixa
    hslv = [
        p for p in products
        if p.get("stock", 0) >= low_visits * hslv_ratio
        and p.get("visits", 0) < low_visits
    ]
    if hslv:
        insights.append({
            "type":  "high_stock_low_demand",
            "title": "Estoque alto com baixa procura",
            "items": [
                {
                    "id":      p["id"],
                    "title":   p["title"],
                    "stock":   p.get("stock", 0),
                    "visits":  p.get("visits", 0),
                    "price":   p.get("price", 0),
                    "permalink": p.get("permalink", ""),
                }
                for p in sorted(hslv, key=lambda p: p.get("stock", 0), reverse=True)[:5]
            ],
        })

    # ── Sem vendas
    if total_sales == 0 and total_visits > 0:
        insights.append({
            "type":  "zero_sales",
            "title": "Sem conversão no período",
            "total_visits": total_visits,
            "total_listings": len(products),
            "suggestion": "Revisar preço, fotos e título dos anúncios mais visitados.",
        })

    # ── Mercado Envios
    if not account.get("mercadoenvios", False):
        insights.append({
            "type":       "mercadoenvios_off",
            "title":      "Mercado Envios não habilitado",
            "suggestion": "Habilitar frete ML aumenta visibilidade no filtro 'Frete grátis'.",
        })

    # ── Concentração de tráfego
    if sorted_by_visits and total_visits > 0 and len(products) > 1:
        top_share = round(sorted_by_visits[0].get("visits", 0) / total_visits * 100, 1)
        if top_share >= 50:
            insights.append({
                "type":      "traffic_concentration",
                "title":     f"{top_share}% do tráfego em 1 produto",
                "product":   sorted_by_visits[0]["title"],
                "share":     top_share,
                "suggestion": "Otimize os demais anúncios para distribuir o tráfego.",
            })

    return insights


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _daily_series(orders: list, date_from: str, date_to: str) -> list:
    start  = datetime.strptime(date_from, "%Y-%m-%d").date()
    end    = datetime.strptime(date_to,   "%Y-%m-%d").date()
    days   = (end - start).days + 1
    series = [0] * days
    for o in orders:
        ds = o.get("date_created", "")[:10]
        try:
            d   = datetime.strptime(ds, "%Y-%m-%d").date()
            idx = (d - start).days
            if 0 <= idx < days:
                series[idx] += 1
        except Exception:
            pass
    return series


def _distribute_visits(total: int, days: int) -> list:
    series = [0] * days
    if total <= 0:
        return series
    step = max(1, days // max(1, total))
    rem  = total
    i    = days - 1
    while rem > 0 and i >= 0:
        series[i] = 1
        rem -= 1
        i   -= step
        if i < 0 and rem > 0:
            i = days - 1
    return series


def _categories_from_products(products: list) -> dict:
    sku_cats  = {}
    visit_cats = {}
    for p in products:
        cat = p.get("category", "Outros")
        sku_cats[cat]   = sku_cats.get(cat, 0) + 1
        visit_cats[cat] = visit_cats.get(cat, 0) + p.get("visits", 0)
    return {cat: visit_cats.get(cat, 0) for cat in sku_cats}


def _save_snapshot(data: dict, client_id: str, date_str: str) -> Path:
    snap_dir = ROOT / "clients" / client_id / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    path = snap_dir / f"{date_str}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

async def fetch(client_id: str, days: int = 30) -> dict:
    config    = load_client_config(client_id)
    today     = datetime.now(timezone.utc)
    date_to   = today.strftime("%Y-%m-%d")
    date_from = (today - timedelta(days=days)).strftime("%Y-%m-%d")

    cid = os.environ.get("ML_CLIENT_ID", "")
    sec = os.environ.get("ML_CLIENT_SECRET", "")
    if not cid or not sec:
        raise SystemExit("[fetch] ML_CLIENT_ID e ML_CLIENT_SECRET são obrigatórios.")

    print(f"[fetch] Cliente: {client_id} | Período: {date_from} → {date_to}")

    token     = await get_valid_access_token(cid, sec)
    seller_id = get_seller_id()
    hdrs      = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=30) as c:
        print("[fetch] Chamadas principais em paralelo...")
        prod_r, ord_r, vis_r, fin_r, rep_r = await asyncio.gather(
            _get_products(c, hdrs, seller_id, config),
            _get_orders(c, hdrs, seller_id, date_from, date_to),
            _get_visits_total(c, hdrs, seller_id, date_from, date_to),
            _get_financial(c, hdrs, seller_id, date_from, date_to),
            _get_reputation(c, hdrs, seller_id),
            return_exceptions=True,
        )

        for name, r in zip(
            ["products", "orders", "visits_total", "financial", "reputation"],
            [prod_r, ord_r, vis_r, fin_r, rep_r],
        ):
            if isinstance(r, Exception):
                print(f"[AVISO] {name}: {r}", file=sys.stderr)

        products = prod_r.get("items", []) if not isinstance(prod_r, Exception) else []

        print(f"[fetch] Buscando visitas por produto ({len(products)} itens)...")
        visit_results = await asyncio.gather(
            *[_get_visits_item(c, hdrs, p["id"], date_from, date_to) for p in products],
            return_exceptions=True,
        )
        for i, vr in enumerate(visit_results):
            if not isinstance(vr, Exception):
                products[i]["visits"] = vr

    orders_data  = ord_r if not isinstance(ord_r, Exception) else {}
    visits_data  = vis_r if not isinstance(vis_r, Exception) else {}
    fin_data     = fin_r if not isinstance(fin_r, Exception) else {}
    rep_data     = rep_r if not isinstance(rep_r, Exception) else {}

    account = {
        "nickname":      rep_data.get("nickname", ""),
        "user_id":       rep_data.get("user_id", 0),
        "site_id":       rep_data.get("site_id", "MLB"),
        "mercadoenvios": rep_data.get("mercadoenvios", False),
        "account_type":  rep_data.get("account_type", "personal"),
    }

    total_visits = visits_data.get("total_visits", 0)
    total_stock  = sum(p.get("stock", 0) for p in products)
    total_sales  = orders_data.get("total_orders", 0)
    revenue      = orders_data.get("total_revenue", 0.0)
    avg_ticket   = orders_data.get("avg_ticket", 0.0)
    daily_sales  = orders_data.get("daily", [0] * days)
    if len(daily_sales) < days:
        daily_sales = daily_sales + [0] * (days - len(daily_sales))
    daily_sales = daily_sales[:days]

    kpis = {
        "active_listings": len(products),
        "total_visits":    total_visits,
        "total_sales":     total_sales,
        "revenue":         revenue,
        "avg_ticket":      avg_ticket,
        "total_stock":     total_stock,
    }

    output = {
        "meta": {
            "fetched_at":  today.astimezone().isoformat(),
            "period_from": date_from,
            "period_to":   date_to,
            "client_id":   client_id,
            "seller_id":   seller_id,
            "version":     "2.0",
        },
        "account":        account,
        "reputation":     rep_data.get("reputation", {}),
        "kpis":           kpis,
        "visits_series":  _distribute_visits(total_visits, days),
        "sales_series":   daily_sales,
        "products":       products,
        "categories":     _categories_from_products(products),
        "financial":      fin_data,
        "orders":         orders_data.get("recent", []),
        "insights":       _compute_insights(products, kpis, account, config),
        "health_score":   compute_health_score(products, kpis, account, config),
    }

    return output


async def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch ML data for a client.")
    parser.add_argument("--client", default="ziyou",  help="ID do cliente")
    parser.add_argument("--days",   type=int, default=30, help="Janela de dados em dias")
    args = parser.parse_args()

    data = await fetch(args.client, args.days)

    # Salvar snapshot
    date_str   = data["meta"]["period_to"]
    snap_path  = _save_snapshot(data, args.client, date_str)
    print(f"[fetch] ✓ Snapshot salvo → {snap_path}")
    print(f"[fetch]   {data['kpis']['active_listings']} produtos | "
          f"{data['kpis']['total_visits']} visitas | "
          f"{data['kpis']['total_sales']} vendas | "
          f"estoque: {data['kpis']['total_stock']}")

    # Disparar build
    print(f"[fetch] Executando build para '{args.client}'...")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build.py"), "--client", args.client],
        check=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
