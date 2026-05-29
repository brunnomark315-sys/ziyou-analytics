#!/usr/bin/env python3
"""
scripts/build.py — Prepara public/ para um cliente específico.

Uso:
    python scripts/build.py --client ziyou

O que faz:
    1. Copia clients/{client}/config.json → public/config.json
    2. Copia snapshots recentes → public/snapshots/
    3. Gera public/snapshots/index.json
    4. Atualiza public/data.json com o snapshot mais recente
"""

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent


def build(client_id: str) -> None:
    client_dir = ROOT / "clients" / client_id
    public_dir = ROOT / "public"
    snap_src   = client_dir / "snapshots"
    snap_dst   = public_dir / "snapshots"

    if not client_dir.exists():
        raise SystemExit(f"[build] Cliente '{client_id}' não encontrado em clients/")

    snap_dst.mkdir(parents=True, exist_ok=True)
    (public_dir / "reports").mkdir(exist_ok=True)

    # 1 ── config.json
    cfg_src = client_dir / "config.json"
    if cfg_src.exists():
        shutil.copy2(cfg_src, public_dir / "config.json")
        print(f"[build] config.json → public/  (cliente: {client_id})")

    # 2 ── copiar snapshots (últimos 30, pulando os já existentes)
    snaps = sorted(snap_src.glob("*.json"), reverse=True)[:30] if snap_src.exists() else []
    copied = 0
    for snap in snaps:
        dst = snap_dst / snap.name
        if not dst.exists():
            shutil.copy2(snap, dst)
            copied += 1

    # 3 ── gerar snapshots/index.json
    snap_files = sorted(
        [f.stem for f in snap_dst.glob("*.json") if f.stem != "index"],
        reverse=True,
    )[:30]

    index = []
    for d in snap_files:
        try:
            label = datetime.strptime(d, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            label = d
        index.append({"date": d, "label": label})

    (snap_dst / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[build] snapshots/index.json → {len(index)} snapshot(s)  (+{copied} novos)")

    # 4 ── data.json ← snapshot mais recente
    if snaps:
        latest = snaps[0]
        shutil.copy2(latest, public_dir / "data.json")
        print(f"[build] data.json ← {latest.name}")
    else:
        print("[build] Nenhum snapshot encontrado — data.json inalterado.")

    print(f"[build] ✓ Cliente '{client_id}' pronto para deploy.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build public/ para um cliente.")
    parser.add_argument("--client", required=True, help="ID do cliente (ex: ziyou)")
    args = parser.parse_args()
    build(args.client)


if __name__ == "__main__":
    main()
