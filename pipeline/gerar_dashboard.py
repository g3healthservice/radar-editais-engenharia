#!/usr/bin/env python3
"""Gera app.html (dashboard self-contained) e build.txt a partir de dataset.json."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATASET_PATH = HERE / "dataset.json"
OUT_APP = HERE.parent / "app.html"
OUT_BUILD = HERE.parent / "build.txt"

TEMPLATE = """<!DOCTYPE html><html lang="pt-BR"><head>
<meta charset="UTF-8">
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Radar de Editais de Engenharia Civil — PNCP | G3 Health Service</title>
<style>
:root{--navy:#1F3A5F;--navy2:#27466E;--teal:#0E7C7B;--bg:#f0f2f5;--card:#ffffff;--ok:#2D6A4F;--warn:#9B2226;--muted:#5b6b7a}
*{box-sizing:border-box}
body{margin:0;font-family:Arial,Helvetica,sans-serif;background:var(--bg);color:#222}
header{background:linear-gradient(135deg,var(--navy),var(--navy2));color:#fff;padding:20px 24px}
header h1{margin:0 0 4px;font-size:22px}
header .sub{font-size:13px;opacity:.85}
.wrap{max-width:1300px;margin:0 auto;padding:18px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin-bottom:18px}
.card{background:var(--card);border-radius:10px;padding:14px 16px;box-shadow:0 1px 3px rgba(0,0,0,.1)}
.card .n{font-size:24px;font-weight:bold;color:var(--navy)}
.card .l{font-size:12px;color:var(--muted);margin-top:2px}
.filters{background:var(--card);border-radius:10px;padding:14px 16px;margin-bottom:14px;display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end}
.filters label{font-size:11px;color:var(--muted);display:block;margin-bottom:3px}
.filters select,.filters input{padding:6px 8px;border:1px solid #cfd8e3;border-radius:6px;font-size:13px;min-width:140px}
.filters input[type=text]{min-width:220px}
table{width:100%;border-collapse:collapse;background:var(--card);border-radius:10px;overflow:hidden}
thead th{background:var(--navy);color:#fff;text-align:left;padding:9px 10px;font-size:12px;cursor:pointer;white-space:nowrap}
thead th:hover{background:var(--teal)}
tbody td{padding:8px 10px;font-size:12.5px;border-bottom:1px solid #eef1f4;vertical-align:top}
tbody tr:hover{background:#f7fafc}
.tablewrap{overflow-x:auto;border-radius:10px}
.badge{display:inline-block;padding:2px 7px;border-radius:20px;font-size:10.5px;margin:1px 2px 1px 0;white-space:nowrap}
.b-fed{background:#dbe7f3;color:var(--navy)}
.b-est{background:#e2f0ee;color:var(--teal)}
.b-mun{background:#eef2e6;color:var(--ok)}
.b-na{background:#eee;color:#777}
.b-ata-s{background:#e2f5ea;color:var(--ok)}
.b-ata-n{background:#f7e8e8;color:var(--warn)}
.b-fonte{background:#f1eef7;color:#6a4c93}
.objeto{max-width:340px}
.small{color:var(--muted);font-size:11px}
a.btn{color:var(--teal);text-decoration:none;font-weight:bold}
footer{text-align:center;color:var(--muted);font-size:11px;padding:18px}
.count-info{font-size:12px;color:var(--muted);margin:6px 0 10px}
</style>
</head><body>
<header>
<h1>🏗️ Radar de Editais — Engenharia Civil / Reforma Predial</h1>
<div class="sub">Fonte: PNCP (dados abertos) · Brasil inteiro · gerado em __GERADO_EM__ · build __BUILD__</div>
</header>
<div class="wrap">
  <div class="cards">
    <div class="card"><div class="n" id="cTotal">0</div><div class="l">Editais de engenharia civil em aberto</div></div>
    <div class="card"><div class="n" id="cValor">R$ 0</div><div class="l">Valor total estimado</div></div>
    <div class="card"><div class="n" id="cAta">0</div><div class="l">Aceitam Ata de Registro de Preços</div></div>
    <div class="card"><div class="n" id="cUrgente">0</div><div class="l">Com prazo ≤ 5 dias</div></div>
  </div>

  <div class="filters">
    <div><label>Esfera</label><select id="fEsfera"><option value="">Todas</option><option>Federal</option><option>Estadual</option><option>Municipal</option><option>Não informado</option></select></div>
    <div><label>UF</label><select id="fUf"><option value="">Todas</option></select></div>
    <div><label>Aceita ATA</label><select id="fAta"><option value="">Todas</option><option value="1">Sim</option><option value="0">Não</option></select></div>
    <div><label>Fonte de recurso</label><select id="fFonte"><option value="">Todas</option></select></div>
    <div><label>Buscar (órgão, município, objeto)</label><input type="text" id="fBusca" placeholder="ex.: hospital, prefeitura, UBS..."></div>
  </div>

  <div class="count-info" id="countInfo"></div>
  <div class="tablewrap">
  <table id="tbl">
    <thead><tr>
      <th data-k="dataEncerramentoProposta">Prazo proposta ↕</th>
      <th data-k="orgao">Órgão ↕</th>
      <th data-k="esfera">Esfera ↕</th>
      <th data-k="municipio">Município/UF ↕</th>
      <th>Objeto</th>
      <th data-k="modalidade">Modalidade ↕</th>
      <th data-k="valorEstimado">Valor estimado ↕</th>
      <th>ATA</th>
      <th>Fonte de recurso</th>
      <th>Edital</th>
    </tr></thead>
    <tbody id="tbody"></tbody>
  </table>
  </div>
</div>
<footer>Classificação de fonte de recurso é heurística (baseada no texto do objeto/edital) — sempre confirmar no edital antes de decidir. Dados: Portal Nacional de Contratações Públicas (PNCP).</footer>
<script>
const D = __DATASET_JSON__;
let itens = D.itens;

function fmtMoeda(v){ if(v==null) return '—'; return 'R$ '+v.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2}); }
function fmtData(iso){ if(!iso) return '—'; const d=new Date(iso); return d.toLocaleDateString('pt-BR')+' '+d.toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'}); }
function diasRestantes(iso){ if(!iso) return 999; return (new Date(iso) - new Date())/86400000; }
function esferaBadge(e){ const m={'Federal':'b-fed','Estadual':'b-est','Municipal':'b-mun'}; return `<span class="badge ${m[e]||'b-na'}">${e}</span>`; }

const ufs = [...new Set(itens.map(i=>i.uf).filter(Boolean))].sort();
const selUf = document.getElementById('fUf');
ufs.forEach(u=>{ const o=document.createElement('option'); o.value=u; o.textContent=u; selUf.appendChild(o); });

const fontes = [...new Set(itens.flatMap(i=>i.fonteRecurso))].sort();
const selFonte = document.getElementById('fFonte');
fontes.forEach(f=>{ const o=document.createElement('option'); o.value=f; o.textContent=f; selFonte.appendChild(o); });

let sortKey = 'dataEncerramentoProposta', sortAsc = true;

function render(){
  const eEsfera = document.getElementById('fEsfera').value;
  const eUf = document.getElementById('fUf').value;
  const eAta = document.getElementById('fAta').value;
  const eFonte = document.getElementById('fFonte').value;
  const eBusca = document.getElementById('fBusca').value.trim().toLowerCase();

  let filtrados = itens.filter(i=>{
    if(eEsfera && i.esfera!==eEsfera) return false;
    if(eUf && i.uf!==eUf) return false;
    if(eAta==='1' && !i.srp) return false;
    if(eAta==='0' && i.srp) return false;
    if(eFonte && !i.fonteRecurso.includes(eFonte)) return false;
    if(eBusca){
      const alvo = (i.orgao+' '+i.municipio+' '+i.objeto).toLowerCase();
      if(!alvo.includes(eBusca)) return false;
    }
    return true;
  });

  filtrados.sort((a,b)=>{
    let va=a[sortKey], vb=b[sortKey];
    if(va==null) va = sortKey==='valorEstimado'?-1:'';
    if(vb==null) vb = sortKey==='valorEstimado'?-1:'';
    if(va<vb) return sortAsc?-1:1;
    if(va>vb) return sortAsc?1:-1;
    return 0;
  });

  document.getElementById('countInfo').textContent = `Mostrando ${filtrados.length} de ${itens.length} editais filtrados (de ${D.totalAbertoBrasil.toLocaleString('pt-BR')} contratações abertas no Brasil hoje).`;

  document.getElementById('cTotal').textContent = filtrados.length;
  document.getElementById('cValor').textContent = fmtMoeda(filtrados.reduce((s,i)=>s+(i.valorEstimado||0),0));
  document.getElementById('cAta').textContent = filtrados.filter(i=>i.srp).length;
  document.getElementById('cUrgente').textContent = filtrados.filter(i=>diasRestantes(i.dataEncerramentoProposta)<=5 && diasRestantes(i.dataEncerramentoProposta)>=0).length;

  const tbody = document.getElementById('tbody');
  tbody.innerHTML = filtrados.slice(0,500).map(i=>{
    const dias = diasRestantes(i.dataEncerramentoProposta);
    const urgente = dias<=5 && dias>=0;
    return `<tr>
      <td>${fmtData(i.dataEncerramentoProposta)}${urgente?' <span class="badge b-ata-n">urgente</span>':''}</td>
      <td>${i.orgao||'—'}<div class="small">${i.unidade||''}</div></td>
      <td>${esferaBadge(i.esfera)}<div class="small">${i.poder}</div></td>
      <td>${i.municipio||'—'}/${i.uf||'—'}</td>
      <td class="objeto" title="${(i.objeto||'').replace(/"/g,'&quot;')}">${(i.objeto||'').slice(0,140)}${(i.objeto||'').length>140?'…':''}</td>
      <td>${i.modalidade||'—'}</td>
      <td>${fmtMoeda(i.valorEstimado)}</td>
      <td><span class="badge ${i.srp?'b-ata-s':'b-ata-n'}">${i.srp?'Sim':'Não'}</span></td>
      <td>${i.fonteRecurso.map(f=>`<span class="badge b-fonte">${f}</span>`).join('')}</td>
      <td>${i.linkEdital?`<a class="btn" href="${i.linkEdital}" target="_blank" rel="noopener">Abrir ↗</a>`:'—'}</td>
    </tr>`;
  }).join('');
  if(filtrados.length>500){
    tbody.innerHTML += `<tr><td colspan="10" class="small" style="text-align:center;padding:12px">Mostrando os 500 primeiros (use os filtros para refinar).</td></tr>`;
  }
}

document.querySelectorAll('thead th[data-k]').forEach(th=>{
  th.addEventListener('click',()=>{
    const k = th.dataset.k;
    if(sortKey===k) sortAsc=!sortAsc; else { sortKey=k; sortAsc=true; }
    render();
  });
});
['fEsfera','fUf','fAta','fFonte'].forEach(id=>document.getElementById(id).addEventListener('change',render));
document.getElementById('fBusca').addEventListener('input',render);

render();
</script>
</body></html>
"""


def main():
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    html = TEMPLATE.replace("__DATASET_JSON__", json.dumps(dataset, ensure_ascii=False))
    html = html.replace("__GERADO_EM__", dataset["geradoEm"]).replace("__BUILD__", str(dataset["build"]))
    OUT_APP.write_text(html, encoding="utf-8")
    OUT_BUILD.write_text(str(dataset["build"]), encoding="utf-8")
    print(f"app.html gerado ({len(html)/1024:.0f} KB), build {dataset['build']}")


if __name__ == "__main__":
    main()
