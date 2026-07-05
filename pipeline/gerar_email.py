#!/usr/bin/env python3
"""Gera o corpo HTML do e-mail com os editais NOVOS desde a última execução."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DASHBOARD_URL = "https://g3healthservice.github.io/radar-editais-engenharia/"

ESFERA_COR = {"Federal": "#1F3A5F", "Estadual": "#0E7C7B", "Municipal": "#2D6A4F", "Não informado": "#777"}


def fmt_moeda(v):
    if v is None:
        return "—"
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_data(iso):
    if not iso:
        return "—"
    return iso.replace("T", " ")[:16]


def linha(item):
    cor = ESFERA_COR.get(item["esfera"], "#777")
    ata = "✅ Aceita ATA" if item["srp"] else "— Sem ATA"
    fontes = ", ".join(item["fonteRecurso"])
    return f"""
    <tr>
      <td style="padding:8px;border-bottom:1px solid #eee">
        <b>{item['orgao'] or '—'}</b>
        <span style="background:{cor};color:#fff;border-radius:10px;padding:1px 8px;font-size:11px;margin-left:6px">{item['esfera']}</span>
        <br><span style="color:#555;font-size:12.5px">{item['municipio'] or '—'}/{item['uf'] or '—'} · {item['modalidade'] or ''}</span>
        <br><span style="font-size:12.5px">{(item['objeto'] or '')[:220]}</span>
        <br><span style="font-size:12px;color:#555">Valor estimado: <b>{fmt_moeda(item['valorEstimado'])}</b> · Prazo proposta: <b>{fmt_data(item['dataEncerramentoProposta'])}</b> · {ata}</span>
        <br><span style="font-size:12px;color:#6a4c93">Fonte de recurso (indício no texto): {fontes}</span>
        <br><a href="{item['linkEdital'] or '#'}" style="font-size:12px">Abrir edital ↗</a>
      </td>
    </tr>"""


def main():
    dataset = json.loads((HERE / "dataset.json").read_text(encoding="utf-8"))
    novos = json.loads((HERE / "novos.json").read_text(encoding="utf-8"))

    resumo_esfera = {}
    for i in dataset["itens"]:
        resumo_esfera[i["esfera"]] = resumo_esfera.get(i["esfera"], 0) + 1

    linhas_html = "".join(linha(i) for i in novos[:80])
    aviso_corte = "" if len(novos) <= 80 else f"<p style='color:#9B2226'>Mostrando os 80 primeiros de {len(novos)} novos editais — veja o restante no dashboard.</p>"

    html = f"""<html><body style="font-family:Arial,Helvetica,sans-serif;color:#222;max-width:760px">
    <h2 style="color:#1F3A5F">🏗️ Radar de Editais — Engenharia Civil / Reforma Predial (PNCP)</h2>
    <p><b>{len(novos)} editais novos</b> desde a última verificação, de um total de <b>{dataset['totalEngenhariaCivil']}</b> abertos agora no Brasil
    (dentre {dataset['totalAbertoBrasil']:,} contratações com proposta em aberto no PNCP hoje).</p>
    <p style="font-size:13px;color:#555">Por esfera (total atual em aberto): {' · '.join(f"{k}: {v}" for k,v in resumo_esfera.items())}</p>
    <p><a href="{DASHBOARD_URL}" style="background:#1F3A5F;color:#fff;padding:8px 14px;border-radius:6px;text-decoration:none">Abrir dashboard completo (filtros, ordenação, todos os itens)</a></p>
    {aviso_corte}
    <table style="width:100%;border-collapse:collapse">{linhas_html}</table>
    <p style="font-size:11px;color:#888;margin-top:16px">Classificação de fonte de recurso é heurística (texto do objeto/edital) — confirmar sempre no edital antes de decidir. Fonte: PNCP (dados abertos).</p>
    </body></html>"""

    (HERE.parent / "email_novos.html").write_text(html, encoding="utf-8")
    print(f"E-mail gerado com {len(novos)} itens novos.")


if __name__ == "__main__":
    main()
