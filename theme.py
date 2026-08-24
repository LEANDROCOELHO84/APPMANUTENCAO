import streamlit as st
import html as _html


# Ícones SVG animados (stroke style, 24x24 viewBox)
_ICONS_SVG = {
    "factory": """
<svg class="ico-svg ico-pulse" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <path class="ico-stroke" d="M3 21h18" stroke-width="1.75" stroke-linecap="round"/>
  <path class="ico-stroke" d="M5 21V10l4 3V8l4 3V5l6 4v12" stroke-width="1.75" stroke-linejoin="round"/>
  <path class="ico-accent ico-smoke" d="M8 4c0-1 .5-2 1.2-2M12 3c0-1.2.6-2.2 1.4-2.2M16 5c0-.9.4-1.8 1-1.8" stroke-width="1.5" stroke-linecap="round"/>
</svg>
""",
    "tools": """
<svg class="ico-svg ico-spin-slow" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <path class="ico-stroke" d="M14.7 6.3a4.5 4.5 0 0 0-6.1 6.1L3 18l3 3 5.6-5.6a4.5 4.5 0 0 0 6.1-6.1l-2.5 2.5-2.5-2.5 2.5-2.5z" stroke-width="1.75" stroke-linejoin="round"/>
  <circle class="ico-accent" cx="16.5" cy="7.5" r="1.2" fill="currentColor" stroke="none"/>
</svg>
""",
    "admin": """
<svg class="ico-svg ico-float" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <circle class="ico-stroke" cx="12" cy="8" r="3.5" stroke-width="1.75"/>
  <path class="ico-stroke" d="M5 20c1.5-3.5 4-5 7-5s5.5 1.5 7 5" stroke-width="1.75" stroke-linecap="round"/>
  <path class="ico-accent ico-shield" d="M18.5 4.5l1.2 1.2-3.2 3.2-1.2-1.2 3.2-3.2z" stroke-width="1.4" stroke-linejoin="round"/>
</svg>
""",
    "wrench": """
<svg class="ico-svg ico-tilt" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <path class="ico-stroke" d="M14.7 6.3a4 4 0 0 0-5.4 5.4L4 17l3 3 5.3-5.3a4 4 0 0 0 5.4-5.4" stroke-width="1.75" stroke-linejoin="round"/>
</svg>
""",
    "clipboard": """
<svg class="ico-svg ico-pulse" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <rect class="ico-stroke" x="6" y="4" width="12" height="16" rx="2" stroke-width="1.75"/>
  <path class="ico-stroke" d="M9 4.5h6v2H9v-2z" stroke-width="1.5"/>
  <path class="ico-accent" d="M9 11h6M9 14h4" stroke-width="1.5" stroke-linecap="round"/>
</svg>
""",
    "chart": """
<svg class="ico-svg ico-pulse" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <path class="ico-stroke" d="M4 19V5M4 19h16" stroke-width="1.75" stroke-linecap="round"/>
  <path class="ico-accent ico-bars" d="M8 16v-4M12 16V9M16 16v-7" stroke-width="2" stroke-linecap="round"/>
</svg>
""",
    "users": """
<svg class="ico-svg ico-float" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <circle class="ico-stroke" cx="9" cy="8" r="3" stroke-width="1.75"/>
  <circle class="ico-stroke" cx="17" cy="9" r="2.5" stroke-width="1.5"/>
  <path class="ico-stroke" d="M3 19c1-3 3.2-4.5 6-4.5S14 16 15 19" stroke-width="1.75" stroke-linecap="round"/>
  <path class="ico-accent" d="M15 14.5c1.8 0 3.5.8 4.5 2.5" stroke-width="1.5" stroke-linecap="round"/>
</svg>
""",
    "gear": """
<svg class="ico-svg ico-spin-slow" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <circle class="ico-stroke" cx="12" cy="12" r="3" stroke-width="1.75"/>
  <path class="ico-stroke" d="M12 3v2.2M12 18.8V21M3 12h2.2M18.8 12H21M5.6 5.6l1.6 1.6M16.8 16.8l1.6 1.6M5.6 18.4l1.6-1.6M16.8 7.2l1.6-1.6" stroke-width="1.5" stroke-linecap="round"/>
</svg>
""",
    "image": """
<svg class="ico-svg ico-pulse" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <rect class="ico-stroke" x="3" y="5" width="18" height="14" rx="2" stroke-width="1.75"/>
  <circle class="ico-accent" cx="9" cy="10" r="1.5" fill="currentColor" stroke="none"/>
  <path class="ico-stroke" d="M3 16l5-4 4 3 3-2 6 4" stroke-width="1.5" stroke-linejoin="round"/>
</svg>
""",
    "upload": """
<svg class="ico-svg ico-float" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <path class="ico-stroke" d="M12 16V6M8 9l4-4 4 4" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/>
  <path class="ico-accent" d="M5 18h14" stroke-width="1.75" stroke-linecap="round"/>
</svg>
""",
    "building": """
<svg class="ico-svg ico-pulse" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <path class="ico-stroke" d="M4 21V7l8-4 8 4v14" stroke-width="1.75" stroke-linejoin="round"/>
  <path class="ico-stroke" d="M9 21v-6h6v6" stroke-width="1.75"/>
  <path class="ico-accent" d="M9 10h.01M15 10h.01M9 14h.01M15 14h.01" stroke-width="2.5" stroke-linecap="round"/>
</svg>
""",
}

# Mapeia emoji / aliases → chave SVG
_ICON_ALIAS = {
    "🏭": "factory",
    "🛠️": "tools",
    "🔧": "wrench",
    "👨‍💼": "admin",
    "📋": "clipboard",
    "📊": "chart",
    "👥": "users",
    "⚙️": "gear",
    "🖼️": "image",
    "📥": "upload",
    "factory": "factory",
    "tools": "tools",
    "admin": "admin",
    "wrench": "wrench",
    "clipboard": "clipboard",
    "chart": "chart",
    "users": "users",
    "gear": "gear",
    "image": "image",
    "upload": "upload",
    "building": "building",
}


def _resolver_icone(icon: str) -> str:
    """Retorna HTML do SVG animado (ou o texto original se não houver mapeamento)."""
    if not icon:
        icon = "factory"
    key = _ICON_ALIAS.get(icon.strip(), _ICON_ALIAS.get(icon, None))
    if key and key in _ICONS_SVG:
        return _ICONS_SVG[key]
    # fallback: texto/emoji escapado
    return f'<span class="ico-fallback">{_html.escape(str(icon))}</span>'


def aplicar_tema():
    st.markdown(
        """
    <style>
        /* ===== Base ===== */
        .stApp {
            background:
                radial-gradient(ellipse 80% 50% at 50% -20%, rgba(220, 38, 38, 0.12), transparent),
                #0a0a0a;
            color: #f1f1f1;
        }

        /* ===== SVG icons ===== */
        .ico-svg {
            width: 28px;
            height: 28px;
            display: block;
            overflow: visible;
        }
        .section-header-icon .ico-svg { width: 22px; height: 22px; }
        .ico-stroke {
            stroke: #f5f5f5;
            fill: none;
        }
        .ico-accent {
            stroke: #ef4444;
            fill: none;
            color: #ef4444;
        }
        .ico-fallback { font-size: 1.5rem; line-height: 1; }

        @keyframes ico-pulse {
            0%, 100% { transform: scale(1); opacity: 1; }
            50% { transform: scale(1.06); opacity: 0.9; }
        }
        @keyframes ico-spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        @keyframes ico-float {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-3px); }
        }
        @keyframes ico-tilt {
            0%, 100% { transform: rotate(-8deg); }
            50% { transform: rotate(8deg); }
        }
        @keyframes ico-smoke {
            0%, 100% { opacity: 0.35; transform: translateY(0); }
            50% { opacity: 0.9; transform: translateY(-2px); }
        }
        @keyframes ico-bars {
            0%, 100% { stroke-dashoffset: 0; }
            50% { opacity: 0.7; }
        }

        .ico-pulse { animation: ico-pulse 2.8s ease-in-out infinite; }
        .ico-spin-slow { animation: ico-spin 12s linear infinite; transform-origin: center; }
        .ico-float { animation: ico-float 2.4s ease-in-out infinite; }
        .ico-tilt { animation: ico-tilt 2.6s ease-in-out infinite; transform-origin: center; }
        .ico-smoke { animation: ico-smoke 2.2s ease-in-out infinite; }
        .ico-bars { animation: ico-bars 2s ease-in-out infinite; }
        .ico-shield { animation: ico-pulse 2.5s ease-in-out infinite; }

        @media (prefers-reduced-motion: reduce) {
            .ico-pulse, .ico-spin-slow, .ico-float, .ico-tilt, .ico-smoke, .ico-bars, .ico-shield {
                animation: none !important;
            }
        }

        /* ===== Header principal (hero) ===== */
        .main-header {
            position: relative;
            overflow: hidden;
            background: linear-gradient(145deg, #141414 0%, #0f0f0f 50%, #1a1010 100%);
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 20px;
            padding: 1.75rem 1.75rem 1.75rem 1.5rem;
            margin-bottom: 1.5rem;
            box-shadow:
                0 0 0 1px rgba(220, 38, 38, 0.15),
                0 20px 50px -20px rgba(0, 0, 0, 0.8),
                0 0 40px -10px rgba(220, 38, 38, 0.25);
        }
        .main-header::before {
            content: "";
            position: absolute;
            left: 0; top: 0; bottom: 0;
            width: 4px;
            background: linear-gradient(180deg, #ef4444, #b91c1c 60%, transparent);
            border-radius: 20px 0 0 20px;
        }
        .main-header::after {
            content: "";
            position: absolute;
            right: -40%; top: -60%;
            width: 70%; height: 160%;
            background: radial-gradient(circle, rgba(239, 68, 68, 0.08), transparent 70%);
            pointer-events: none;
        }
        .main-header-inner {
            position: relative;
            z-index: 1;
            display: flex;
            align-items: center;
            gap: 1.1rem;
        }
        .main-header-icon {
            flex-shrink: 0;
            width: 56px; height: 56px;
            display: flex; align-items: center; justify-content: center;
            background: linear-gradient(145deg, #1f1f1f, #151515);
            border: 1px solid rgba(239, 68, 68, 0.35);
            border-radius: 14px;
            box-shadow: 0 0 20px rgba(239, 68, 68, 0.15);
            color: #ef4444;
        }
        .main-header-text h1 {
            margin: 0;
            font-size: clamp(1.35rem, 2.5vw, 1.85rem);
            font-weight: 700;
            letter-spacing: -0.02em;
            line-height: 1.25;
            color: #fafafa;
        }
        .main-header-text p {
            margin: 0.35rem 0 0 0;
            font-size: 0.95rem;
            color: #a3a3a3;
            font-weight: 400;
            letter-spacing: 0.01em;
        }

        /* ===== Header de seção ===== */
        .section-header {
            position: relative;
            overflow: hidden;
            background: linear-gradient(145deg, #121212, #0e0e0e);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 16px;
            padding: 1.15rem 1.35rem;
            margin-bottom: 1.25rem;
            box-shadow: 0 8px 24px -12px rgba(0, 0, 0, 0.6);
        }
        .section-header::before {
            content: "";
            position: absolute;
            left: 0; top: 12px; bottom: 12px;
            width: 3px;
            background: linear-gradient(180deg, #ef4444, #7f1d1d);
            border-radius: 2px;
        }
        .section-header-inner {
            display: flex;
            align-items: center;
            gap: 0.9rem;
            padding-left: 0.4rem;
        }
        .section-header-icon {
            flex-shrink: 0;
            width: 42px; height: 42px;
            display: flex; align-items: center; justify-content: center;
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid rgba(239, 68, 68, 0.25);
            border-radius: 11px;
            color: #ef4444;
        }
        .section-header-text h2 {
            margin: 0;
            font-size: 1.25rem;
            font-weight: 650;
            letter-spacing: -0.01em;
            color: #f5f5f5;
        }
        .section-header-text p {
            margin: 0.2rem 0 0 0;
            font-size: 0.85rem;
            color: #737373;
        }

        /* ===== Containers / forms ===== */
        .stContainer, div[data-testid="stExpander"], .stForm {
            background-color: #111111;
            border: 1px solid #2a2a2a;
            border-radius: 14px;
        }

        /* ===== Botões ===== */
        .stButton > button {
            background: linear-gradient(180deg, #dc2626, #b91c1c);
            color: white;
            height: 48px;
            font-weight: 650;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 10px;
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }
        .stButton > button:hover {
            background: linear-gradient(180deg, #ef4444, #dc2626);
            box-shadow: 0 0 24px rgba(239, 68, 68, 0.35);
            transform: translateY(-1px);
        }

        /* ===== Feedback de sucesso ===== */
        .fx-sucesso {
            display: flex;
            align-items: center;
            gap: 14px;
            margin: 0 0 1.1rem 0;
            padding: 14px 18px;
            border-radius: 14px;
            border: 1px solid rgba(34, 197, 94, 0.45);
            border-left: 5px solid #22c55e;
            background: linear-gradient(135deg, rgba(22, 101, 52, 0.35), rgba(20, 83, 45, 0.15));
            box-shadow:
                0 0 0 1px rgba(34, 197, 94, 0.12),
                0 12px 28px -12px rgba(34, 197, 94, 0.35);
            animation: fx-sucesso-in 0.45s ease-out, fx-sucesso-pulse 2.2s ease-in-out 0.45s 2;
        }
        .fx-sucesso-icone {
            flex-shrink: 0;
            width: 42px; height: 42px;
            display: flex; align-items: center; justify-content: center;
            font-size: 1.35rem;
            border-radius: 12px;
            background: rgba(34, 197, 94, 0.2);
            border: 1px solid rgba(34, 197, 94, 0.4);
        }
        .fx-sucesso-titulo {
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            color: #86efac;
            margin-bottom: 2px;
        }
        .fx-sucesso-msg {
            font-size: 0.98rem;
            font-weight: 600;
            color: #f0fdf4;
            line-height: 1.35;
        }
        @keyframes fx-sucesso-in {
            from { opacity: 0; transform: translateY(-10px) scale(0.98); }
            to   { opacity: 1; transform: translateY(0) scale(1); }
        }
        @keyframes fx-sucesso-pulse {
            0%, 100% { box-shadow: 0 0 0 1px rgba(34, 197, 94, 0.12), 0 12px 28px -12px rgba(34, 197, 94, 0.35); }
            50%      { box-shadow: 0 0 0 1px rgba(34, 197, 94, 0.25), 0 12px 32px -8px rgba(34, 197, 94, 0.55); }
        }
        @media (prefers-reduced-motion: reduce) {
            .fx-sucesso { animation: none !important; }
        }

        /* ===== Badges ===== */
        .badge {
            padding: 5px 14px;
            border-radius: 9999px;
            font-weight: 650;
            font-size: 0.8rem;
            letter-spacing: 0.02em;
        }
        .prio-critica { background: #7f1d1d; color: #fecaca; border: 1px solid #ef4444; }
        .prio-alta    { background: #78350f; color: #fde047; border: 1px solid #fbbf24; }
        .prio-media   { background: #3f3f46; color: #d1d5db; border: 1px solid #52525b; }
        .prio-baixa   { background: #14532d; color: #86efac; border: 1px solid #22c55e; }
    </style>
    """,
        unsafe_allow_html=True,
    )


def header(titulo, subtitulo=None, icon="🏭", nivel="principal"):
    """
    Header moderno com ícone SVG animado.
    icon: emoji (🏭, 🛠️, 👨‍💼…) ou chave (factory, tools, admin…)
    nivel: "principal" | "secao"
    """
    ico_html = _resolver_icone(icon)
    sub_html = f"<p>{_html.escape(subtitulo)}</p>" if subtitulo else ""
    titulo_esc = _html.escape(str(titulo))

    if nivel == "secao":
        st.markdown(
            f"""
            <div class="section-header">
                <div class="section-header-inner">
                    <div class="section-header-icon">{ico_html}</div>
                    <div class="section-header-text">
                        <h2>{titulo_esc}</h2>
                        {sub_html}
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
            <div class="main-header">
                <div class="main-header-inner">
                    <div class="main-header-icon">{ico_html}</div>
                    <div class="main-header-text">
                        <h1>{titulo_esc}</h1>
                        {sub_html}
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def badge_prioridade(prioridade):
    classes = {
        "Crítica": "prio-critica",
        "Alta": "prio-alta",
        "Média": "prio-media",
        "Baixa": "prio-baixa",
    }
    emoji = {"Crítica": "🔴", "Alta": "🟠", "Média": "🟡", "Baixa": "🟢"}
    return (
        f'<span class="badge {classes.get(prioridade, "")}">'
        f'{emoji.get(prioridade, "")} {prioridade}</span>'
    )


def badge_status(status):
    emoji = {
        "Aberto": "📌",
        "Em Atendimento": "🔧",
        "Concluído": "✅",
        "Aguardando Peça": "🛒",
    }
    return (
        f'<span class="badge" style="background:#262626;color:#e5e5e5;'
        f'border:1px solid #404040;">{emoji.get(status, "")} {status}</span>'
    )


CORES_PRIORIDADE = {
    "Crítica": "#ef4444",
    "Alta": "#f59e0b",
    "Média": "#a3a3a3",
    "Baixa": "#4ade80",
}
CORES_STATUS = {
    "Aberto": "#60a5fa",
    "Em Atendimento": "#fbbf24",
    "Aguardando Peça": "#f97316",
    "Concluído": "#4ade80",
}
