# Radar de Editais — Engenharia Civil / Reforma Predial (PNCP)

Automação que varre o [PNCP](https://pncp.gov.br) (Portal Nacional de Contratações Públicas) em busca de
contratações com proposta em aberto relacionadas a manutenção predial, reforma, ampliação e demais
serviços de engenharia civil, em todo o Brasil (esferas federal, estadual e municipal).

- Dashboard: https://g3healthservice.github.io/radar-editais-engenharia/
- Roda a cada 4h via GitHub Actions (`.github/workflows/radar-editais.yml`)
- Envia e-mail com os editais novos desde a última execução (só quando há novidade)

## Secrets necessários (Settings → Secrets and variables → Actions)
- `MAIL_SERVER` (ex.: smtp.gmail.com)
- `MAIL_PORT` (ex.: 465)
- `MAIL_USERNAME` (conta Gmail remetente)
- `MAIL_PASSWORD` (senha de app do Gmail, sem espaços)
