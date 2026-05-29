#!/usr/bin/env python3
"""
scripts/generate_pdf.py — Gera relatório PDF executivo via Playwright (headless Chromium).

Uso:
    python scripts/generate_pdf.py [--client ziyou] [--port 18080]

Requer:
    pip install playwright
    playwright install --with-deps chromium

O script:
    1. Sobe um servidor HTTP local servindo public/
    2. Abre o dashboard em modo print (?print=1 — bypassa login, layout A4)
    3. Aguarda Chart.js renderizar (~3s)
    4. Exporta para public/reports/YYYY-MM-DD.pdf
    5. Atualiza public/reports/index.json
"""

import argparse
import asyncio
import http.server
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT   = Path(__file__).parent.parent
PUBLIC = ROOT / "public"


# ─────────────────────────────────────────────
# HTTP server silencioso
# ─────────────────────────────────────────────

class _SilentHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def _start_server(port: int) -> http.server.HTTPServer:
    original_cwd = Path.cwd()
    os.chdir(PUBLIC)
    server = http.server.HTTPServer(("localhost", port), _SilentHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    os.chdir(original_cwd)
    return server


# ─────────────────────────────────────────────
# Geração do PDF
# ─────────────────────────────────────────────

async def _generate(client_id: str, port: int) -> Path:
    from playwright.async_api import async_playwright

    today       = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    reports_dir = PUBLIC / "reports"
    reports_dir.mkdir(exist_ok=True)
    pdf_path    = reports_dir / f"{today}.pdf"

    print(f"[pdf] Abrindo dashboard em modo print (porta {port})...")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox"])
        page    = await browser.new_page(viewport={"width": 1280, "height": 900})

        # ?print=1 faz o app.js pular o login e usar layout de impressão
        await page.goto(
            f"http://localhost:{port}/?print=1",
            wait_until="networkidle",
            timeout=20_000,
        )

        # Aguardar Chart.js terminar de renderizar
        await page.wait_for_timeout(3000)

        await page.pdf(
            path=str(pdf_path),
            format="A4",
            print_background=True,
            margin={"top": "14mm", "right": "10mm", "bottom": "14mm", "left": "10mm"},
        )
        await browser.close()

    print(f"[pdf] ✓ PDF gerado → {pdf_path}")
    return pdf_path


def _update_reports_index(reports_dir: Path) -> None:
    pdfs = sorted([f.stem for f in reports_dir.glob("*.pdf")], reverse=True)[:12]
    index = []
    for d in pdfs:
        try:
            label = datetime.strptime(d, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            label = d
        index.append({"date": d, "label": label, "url": f"reports/{d}.pdf"})

    (reports_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[pdf] reports/index.json → {len(index)} relatório(s)")


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

async def main() -> None:
    parser = argparse.ArgumentParser(description="Gera PDF executivo do dashboard.")
    parser.add_argument("--client", default="ziyou")
    parser.add_argument("--port",   type=int, default=18080)
    args = parser.parse_args()

    server = _start_server(args.port)
    time.sleep(0.8)  # aguardar servidor iniciar

    try:
        pdf_path = await _generate(args.client, args.port)
        _update_reports_index(pdf_path.parent)
    finally:
        server.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
