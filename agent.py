import anthropic
import json
import os
import re
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6"
MAX_RETRIES = 3
PAUSE_SECONDS = 90

MESES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}

SEARCH_TOPICS = [
    {
        "id": "regulacion",
        "categoria": "Regulación Financiera",
        "emoji": "⚖️",
        "query": "CNBV Banxico Condusef regulación fintech pagos adquirencia México noticias recientes 2026",
    },
    {
        "id": "competencia",
        "categoria": "Competencia",
        "emoji": "🎯",
        "query": "Clip Getnet Conekta Kushki Stripe pagos México adquirencia noticias 2026",
    },
    {
        "id": "fintech-pagos",
        "categoria": "Fintech y Pagos",
        "emoji": "⚡",
        "query": "SPEI BNPL STP pagos digitales fintech México noticias recientes 2026",
    },
    {
        "id": "tendencias-latam",
        "categoria": "Tendencias LATAM",
        "emoji": "🌎",
        "query": "tendencias fintech pagos digitales América Latina LATAM noticias 2026",
    },
    {
        "id": "nuevas-tecnologias",
        "categoria": "Nuevas Tecnologías de Pago",
        "emoji": "🚀",
        "query": "nuevas tecnologías pagos NFC biometría tokenización open banking México LATAM 2026",
    },
]

RELEVANCIA_COLORS = {
    "alta":  ("#dc2626", "#fef2f2", "🔴"),
    "media": ("#d97706", "#fffbeb", "🟡"),
    "baja":  ("#16a34a", "#f0fdf4", "🟢"),
}


def extract_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {"noticias": [], "tendencia_general": text[:500]}


def search_news(client: anthropic.Anthropic, topic: dict) -> dict:
    system_prompt = (
        "Eres un analista de noticias especializado en pagos digitales y fintech en México y LATAM. "
        "Responde ÚNICAMENTE con un objeto JSON válido, sin texto adicional ni markdown. "
        "El JSON debe tener esta estructura exacta:\n"
        '{"noticias": [{"titulo": "...", "fuente": "...", "fecha": "...", "url": "https://...", '
        '"resumen": "2-3 oraciones", "relevancia": "Por qué es relevante para Ecart Pay", '
        '"nivel_relevancia": "alta|media|baja"}], "tendencia_general": "1-2 oraciones"}\n\n'
        "CRITERIOS DE CLASIFICACIÓN DE RELEVANCIA para Ecart Pay (empresa de adquirencia en México):\n"
        "- alta: directamente relacionada con adquirencia, competidores directos (Clip, Getnet, MIT, Conekta, Kushki, Stripe), "
        "o regulación que afecte operaciones de Ecart Pay\n"
        "- media: relacionada con el ecosistema fintech/pagos en México o LATAM pero sin impacto directo inmediato\n"
        "- baja: tendencias globales o noticias de contexto general\n"
        "INCLUIR SOLO noticias que genuinamente merezcan estar. Si solo hay 2 noticias relevantes, incluir solo 2. "
        "Si no hay noticias relevantes, devolver lista vacía. Incluir siempre la URL real de la fuente en el campo url."
    )

    user_prompt = (
        f"Busca las noticias más recientes (últimos 7 días) sobre: {topic['query']}\n\n"
        "Incluye ÚNICAMENTE noticias que sean genuinamente relevantes para Ecart Pay. "
        "No fuerces un número mínimo; si solo hay 2 noticias que valen la pena, incluye solo esas 2. "
        "Para cada noticia incluye la URL real del artículo. "
        "Clasifica la relevancia según los criterios del sistema. "
        "Responde SOLO con el JSON."
    )

    for attempt in range(MAX_RETRIES):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=2500,
                tools=[
                    {
                        "type": "web_search_20260209",
                        "name": "web_search",
                        "max_uses": 5,
                    }
                ],
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            text_content = ""
            for block in response.content:
                if hasattr(block, "type") and block.type == "text":
                    text_content += block.text

            if text_content.strip():
                return extract_json(text_content)
            return {"noticias": [], "tendencia_general": "No se encontraron noticias."}

        except anthropic.RateLimitError as e:
            wait = 30 * (2 ** attempt)
            print(f"  ⚠️  Rate limit alcanzado. Esperando {wait}s antes de reintentar... (intento {attempt + 1}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES - 1:
                time.sleep(wait)
            else:
                print(f"  ❌ Se agotaron los reintentos para '{topic['categoria']}'.")
                return {"noticias": [], "tendencia_general": f"Error de rate limit: {str(e)[:200]}"}

        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                wait = 15 * (attempt + 1)
                print(f"  ⚠️  Error del servidor ({e.status_code}). Esperando {wait}s... (intento {attempt + 1}/{MAX_RETRIES})")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(wait)
                else:
                    print(f"  ❌ Se agotaron los reintentos para '{topic['categoria']}'.")
                    return {"noticias": [], "tendencia_general": f"Error del servidor: {str(e)[:200]}"}
            else:
                print(f"  ❌ Error de API ({e.status_code}): {str(e)[:200]}")
                return {"noticias": [], "tendencia_general": f"Error de API: {str(e)[:200]}"}

        except Exception as e:
            print(f"  ❌ Error inesperado: {str(e)[:200]}")
            return {"noticias": [], "tendencia_general": f"Error: {str(e)[:200]}"}

    return {"noticias": [], "tendencia_general": "No se pudo obtener información."}


def build_news_card(noticia: dict, idx: int) -> str:
    nivel = noticia.get("nivel_relevancia", "baja").lower()
    if nivel not in RELEVANCIA_COLORS:
        nivel = "baja"
    color, bg, emoji = RELEVANCIA_COLORS[nivel]

    titulo = noticia.get("titulo", "Sin título")
    fuente = noticia.get("fuente", "Fuente desconocida")
    fecha = noticia.get("fecha", "")
    resumen = noticia.get("resumen", "")
    relevancia = noticia.get("relevancia", "")
    url = noticia.get("url", "").strip()

    fecha_html = f'<span class="card-date">{fecha}</span>' if fecha else ""

    url_html = ""
    if url and url.startswith("http"):
        url_html = f'<a class="read-link" href="{url}" target="_blank" rel="noopener noreferrer">Leer nota completa →</a>'

    return f"""
    <div class="news-card" data-nivel="{nivel}" style="animation-delay: {idx * 0.1}s">
      <div class="card-header">
        <div class="card-source-row">
          <span class="card-source">{fuente}</span>
          {fecha_html}
        </div>
        <span class="relevance-badge" style="background:{bg}; color:{color}; border:1px solid {color}40;">
          {emoji} {nivel.capitalize()}
        </span>
      </div>
      <h3 class="card-title">{titulo}</h3>
      <p class="card-summary">{resumen}</p>
      <div class="relevance-box" style="border-left:3px solid {color}; background:{bg};">
        <span class="relevance-label">Relevancia para Ecart Pay:</span>
        <p class="relevance-text">{relevancia}</p>
      </div>
      {url_html}
    </div>"""


def build_section(topic: dict, data: dict) -> str:
    noticias = data.get("noticias", [])
    tendencia = data.get("tendencia_general", "")
    count = len(noticias)

    cards_html = "\n".join(build_news_card(n, i) for i, n in enumerate(noticias))
    tendencia_html = ""
    if tendencia:
        tendencia_html = f"""
      <div class="trend-box">
        <span class="trend-label">📈 Tendencia general:</span>
        <p class="trend-text">{tendencia}</p>
      </div>"""

    return f"""
  <section id="{topic['id']}" class="section">
    <div class="section-header">
      <div class="section-title-row">
        <span class="section-emoji">{topic['emoji']}</span>
        <h2 class="section-title">{topic['categoria']}</h2>
        <span class="section-count">{count} noticias</span>
      </div>
      {tendencia_html}
    </div>
    <div class="cards-grid">
      {cards_html if cards_html else '<p class="no-news">No se encontraron noticias para esta categoría.</p>'}
    </div>
  </section>"""


def build_exec_summary(results: list) -> str:
    all_news = []
    for _, data in results:
        all_news.extend(data.get("noticias", []))

    total = len(all_news)
    alta = sum(1 for n in all_news if n.get("nivel_relevancia", "").lower() == "alta")
    media = sum(1 for n in all_news if n.get("nivel_relevancia", "").lower() == "media")
    baja = sum(1 for n in all_news if n.get("nivel_relevancia", "").lower() == "baja")

    return f"""
  <div class="exec-summary">
    <h2 class="exec-title">📊 Resumen Ejecutivo</h2>
    <div class="stats-row">
      <div class="stat-card">
        <span class="stat-number">{total}</span>
        <span class="stat-label">Noticias encontradas</span>
      </div>
      <div class="stat-card">
        <span class="stat-number" style="color:#dc2626">{alta}</span>
        <span class="stat-label">🔴 Relevancia alta</span>
      </div>
      <div class="stat-card">
        <span class="stat-number" style="color:#d97706">{media}</span>
        <span class="stat-label">🟡 Relevancia media</span>
      </div>
      <div class="stat-card">
        <span class="stat-number" style="color:#16a34a">{baja}</span>
        <span class="stat-label">🟢 Relevancia baja</span>
      </div>
    </div>
  </div>"""


def build_nav(topics: list) -> str:
    category_links = "\n".join(
        f'      <a href="#{t["id"]}" class="nav-link">{t["emoji"]} {t["categoria"]}</a>'
        for t in topics
    )
    return f"""
  <nav class="sticky-nav">
    <div class="nav-inner">
      <div class="nav-group nav-categories">
{category_links}
      </div>
      <div class="nav-divider"></div>
      <div class="nav-group nav-filters">
        <span class="nav-filter-label">Filtrar:</span>
        <button class="filter-btn active" data-filter="all" onclick="filterCards('all')">Todas</button>
        <button class="filter-btn filter-alta" data-filter="alta" onclick="filterCards('alta')">🔴 Alta</button>
        <button class="filter-btn filter-media" data-filter="media" onclick="filterCards('media')">🟡 Media</button>
        <button class="filter-btn filter-baja" data-filter="baja" onclick="filterCards('baja')">🟢 Baja</button>
      </div>
    </div>
  </nav>"""


def generate_html(results: list, fecha_str: str) -> str:
    nav_html = build_nav(SEARCH_TOPICS)
    exec_html = build_exec_summary(results)
    sections_html = "\n".join(build_section(topic, data) for topic, data in results)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Ecart Pay · Noticias del día — {fecha_str}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: "Montserrat", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f1f5f9;
      color: #1e293b;
      line-height: 1.6;
    }}

    /* Header */
    .main-header {{
      background: #000000;
      color: #fff;
      padding: 32px 24px 28px;
      text-align: center;
      box-shadow: 0 4px 20px rgba(0,0,0,0.4);
    }}
    .header-logo {{ font-size: 2.2rem; font-weight: 800; letter-spacing: -0.5px; }}
    .header-logo span {{ color: #68AE34; }}
    .header-subtitle {{ font-size: 1rem; color: #94a3b8; margin-top: 4px; font-weight: 500; }}
    .header-date {{
      display: inline-block;
      margin-top: 12px;
      background: rgba(104,174,52,0.15);
      border: 1px solid rgba(104,174,52,0.4);
      color: #68AE34;
      padding: 4px 16px;
      border-radius: 999px;
      font-size: 0.875rem;
      font-weight: 600;
    }}

    /* Nav */
    .sticky-nav {{
      position: sticky;
      top: 0;
      z-index: 100;
      background: #000000;
      border-bottom: 2px solid #68AE34;
      box-shadow: 0 2px 10px rgba(0,0,0,0.3);
    }}
    .nav-inner {{
      max-width: 1300px;
      margin: 0 auto;
      padding: 0 16px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 4px;
    }}
    .nav-group {{ display: flex; flex-wrap: wrap; align-items: center; gap: 2px; }}
    .nav-divider {{
      width: 1px;
      height: 24px;
      background: #333;
      margin: 0 8px;
      flex-shrink: 0;
    }}
    .nav-link {{
      display: inline-block;
      padding: 10px 12px;
      color: #94a3b8;
      text-decoration: none;
      font-size: 0.8rem;
      font-weight: 600;
      transition: color 0.2s, background 0.2s;
      border-radius: 4px;
    }}
    .nav-link:hover {{ color: #68AE34; background: rgba(104,174,52,0.1); }}

    /* Filters */
    .nav-filter-label {{
      font-size: 0.72rem;
      font-weight: 700;
      color: #64748b;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      padding: 0 6px;
    }}
    .filter-btn {{
      border: 1px solid #333;
      background: transparent;
      color: #94a3b8;
      padding: 5px 12px;
      border-radius: 999px;
      font-size: 0.75rem;
      font-weight: 700;
      font-family: "Montserrat", sans-serif;
      cursor: pointer;
      transition: all 0.2s;
    }}
    .filter-btn:hover {{ border-color: #68AE34; color: #68AE34; }}
    .filter-btn.active {{ background: #68AE34; border-color: #68AE34; color: #fff; }}
    .filter-btn.filter-alta.active {{ background: #dc2626; border-color: #dc2626; }}
    .filter-btn.filter-media.active {{ background: #d97706; border-color: #d97706; }}
    .filter-btn.filter-baja.active {{ background: #16a34a; border-color: #16a34a; }}

    /* Main */
    main {{
      max-width: 1300px;
      margin: 0 auto;
      padding: 32px 16px 64px;
    }}

    /* Exec Summary */
    .exec-summary {{
      background: #fff;
      border-radius: 16px;
      padding: 28px;
      margin-bottom: 32px;
      box-shadow: 0 1px 8px rgba(0,0,0,0.08);
      border-top: 4px solid #68AE34;
    }}
    .exec-title {{ font-size: 1.3rem; font-weight: 800; margin-bottom: 20px; color: #000; }}
    .stats-row {{ display: flex; gap: 16px; flex-wrap: wrap; }}
    .stat-card {{
      flex: 1;
      min-width: 140px;
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      padding: 20px 16px;
      text-align: center;
    }}
    .stat-number {{ display: block; font-size: 2.2rem; font-weight: 800; color: #000; line-height: 1; }}
    .stat-label {{ display: block; font-size: 0.78rem; color: #64748b; margin-top: 6px; font-weight: 600; }}

    /* Section */
    .section {{ margin-bottom: 48px; }}
    .section-header {{
      background: #fff;
      border-radius: 16px 16px 0 0;
      padding: 24px 28px 20px;
      border-bottom: 2px solid #E1EFD6;
      border-top: 4px solid #68AE34;
      box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }}
    .section-title-row {{
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 12px;
    }}
    .section-emoji {{ font-size: 1.8rem; }}
    .section-title {{ font-size: 1.4rem; font-weight: 800; color: #000; }}
    .section-count {{
      margin-left: auto;
      background: #E1EFD6;
      border: 1px solid #68AE34;
      color: #4E8327;
      padding: 3px 12px;
      border-radius: 999px;
      font-size: 0.8rem;
      font-weight: 700;
    }}
    .trend-box {{
      background: #E1EFD6;
      border-left: 3px solid #68AE34;
      border-radius: 0 8px 8px 0;
      padding: 10px 14px;
    }}
    .trend-label {{ font-size: 0.78rem; font-weight: 700; color: #4E8327; text-transform: uppercase; letter-spacing: 0.05em; }}
    .trend-text {{ font-size: 0.9rem; color: #1e293b; margin-top: 2px; }}

    /* Cards grid */
    .cards-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
      gap: 16px;
      background: #f1f5f9;
      border-radius: 0 0 16px 16px;
      padding: 20px;
    }}
    .no-news {{ color: #94a3b8; font-size: 0.9rem; padding: 16px; }}

    /* Card */
    .news-card {{
      background: #fff;
      border-radius: 12px;
      padding: 20px;
      box-shadow: 0 1px 6px rgba(0,0,0,0.07);
      border: 1px solid #e2e8f0;
      transition: transform 0.2s, box-shadow 0.2s, opacity 0.2s;
      animation: fadeUp 0.4s ease both;
      display: flex;
      flex-direction: column;
      gap: 0;
    }}
    .news-card.hidden {{ display: none; }}
    .news-card:hover {{
      transform: translateY(-3px);
      box-shadow: 0 6px 20px rgba(104,174,52,0.15);
      border-color: #68AE34;
    }}
    @keyframes fadeUp {{
      from {{ opacity: 0; transform: translateY(12px); }}
      to   {{ opacity: 1; transform: translateY(0); }}
    }}
    .card-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 8px;
      margin-bottom: 10px;
    }}
    .card-source-row {{ display: flex; flex-direction: column; gap: 2px; }}
    .card-source {{ font-size: 0.78rem; font-weight: 700; color: #475569; text-transform: uppercase; letter-spacing: 0.04em; }}
    .card-date {{ font-size: 0.72rem; color: #94a3b8; }}
    .relevance-badge {{
      flex-shrink: 0;
      font-size: 0.72rem;
      font-weight: 700;
      padding: 3px 10px;
      border-radius: 999px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .card-title {{ font-size: 0.95rem; font-weight: 700; color: #000; margin-bottom: 8px; line-height: 1.4; }}
    .card-summary {{ font-size: 0.875rem; color: #334155; margin-bottom: 14px; line-height: 1.6; }}
    .relevance-box {{ padding: 10px 12px; border-radius: 0 8px 8px 0; }}
    .relevance-label {{ font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }}
    .relevance-text {{ font-size: 0.82rem; color: #374151; margin-top: 3px; line-height: 1.5; }}
    .read-link {{
      display: inline-block;
      margin-top: 12px;
      color: #4E8327;
      font-size: 0.8rem;
      font-weight: 700;
      text-decoration: none;
      border: 1px solid #68AE34;
      padding: 5px 12px;
      border-radius: 6px;
      transition: background 0.2s, color 0.2s;
      align-self: flex-start;
    }}
    .read-link:hover {{ background: #68AE34; color: #fff; }}

    /* Footer */
    footer {{
      text-align: center;
      padding: 24px;
      font-size: 0.8rem;
      color: #94a3b8;
      border-top: 1px solid #e2e8f0;
      background: #fff;
      font-weight: 500;
    }}

    @media (max-width: 640px) {{
      .cards-grid {{ grid-template-columns: 1fr; }}
      .stats-row {{ flex-direction: column; }}
      .nav-divider {{ display: none; }}
    }}
  </style>
</head>
<body>
  <header class="main-header">
    <div class="header-logo">Ecart <span>Pay</span></div>
    <div class="header-subtitle">Monitor de Noticias · Pagos Digitales &amp; Fintech México</div>
    <div class="header-date">📅 {fecha_str}</div>
  </header>

{nav_html}

  <main>
{exec_html}
{sections_html}
  </main>

  <footer>
    Generado automáticamente por Ecart Pay News Agent · {MODEL} · {fecha_str}
  </footer>

  <script>
    function filterCards(nivel) {{
      // Update active button
      document.querySelectorAll('.filter-btn').forEach(btn => {{
        btn.classList.remove('active');
        if (btn.dataset.filter === nivel) btn.classList.add('active');
      }});

      // Show/hide cards
      document.querySelectorAll('.news-card').forEach(card => {{
        if (nivel === 'all' || card.dataset.nivel === nivel) {{
          card.classList.remove('hidden');
        }} else {{
          card.classList.add('hidden');
        }}
      }});

      // Update section counts to reflect visible cards
      document.querySelectorAll('.section').forEach(section => {{
        const visible = section.querySelectorAll('.news-card:not(.hidden)').length;
        const countEl = section.querySelector('.section-count');
        if (countEl) {{
          const total = section.querySelectorAll('.news-card').length;
          countEl.textContent = nivel === 'all' ? `${{total}} noticias` : `${{visible}} / ${{total}} noticias`;
        }}
      }});
    }}
  </script>
</body>
</html>"""


def main():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ Error: ANTHROPIC_API_KEY no encontrada.")
        print("   Crea un archivo .env con: ANTHROPIC_API_KEY=sk-ant-...")
        return

    client = anthropic.Anthropic(api_key=api_key)

    now = datetime.now()
    fecha_str = f"{now.day} de {MESES[now.month]} de {now.year}"
    file_date = now.strftime("%Y-%m-%d_%H%M")

    reportes_dir = Path(__file__).parent / "reportes"
    reportes_dir.mkdir(exist_ok=True)

    print("=" * 60)
    print(f"  Ecart Pay News Agent — {fecha_str}")
    print("=" * 60)

    results = []
    for i, topic in enumerate(SEARCH_TOPICS):
        print(f"\n[{i+1}/{len(SEARCH_TOPICS)}] 🔍 Buscando: {topic['emoji']} {topic['categoria']}...")
        data = search_news(client, topic)
        n_found = len(data.get("noticias", []))
        print(f"  ✅ {n_found} noticias encontradas.")
        results.append((topic, data))

        if i < len(SEARCH_TOPICS) - 1:
            print(f"  ⏳ Pausa de {PAUSE_SECONDS}s para evitar rate limits...")
            time.sleep(PAUSE_SECONDS)

    print("\n📝 Generando reporte HTML...")
    html = generate_html(results, fecha_str)

    report_path = reportes_dir / f"reporte_{file_date}.html"
    report_path.write_text(html, encoding="utf-8")

    print(f"✅ Reporte guardado: {report_path}")
    print("🌐 Abriendo en el navegador...")
    if not os.getenv("CI"):
        webbrowser.open(report_path.resolve().as_uri())
    print("\n¡Listo! Revisa tu navegador.")


if __name__ == "__main__":
    main()
