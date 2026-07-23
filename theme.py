import streamlit as st

def aplicar_tema():
    st.markdown("""
    <style>
        .stApp { background-color: #0a0a0a; color: #f1f1f1; }
        .main-header {
            background: linear-gradient(135deg, #111111, #1f1f1f);
            border: 3px solid #dc2626;
            color: white;
            padding: 1.6rem 2rem;
            border-radius: 16px;
            margin-bottom: 2rem;
            box-shadow: 0 10px 30px rgba(220, 38, 38, 0.35);
        }
        .main-header h1 { font-size: 2.4rem; margin: 0; }
        .main-header p { color: #facc15; margin-top: 0.4rem; font-size: 1.1rem; }

        .stContainer, div[data-testid="stExpander"], .stForm { background-color: #111111; border: 1px solid #444; border-radius: 14px; }
        
        .stButton > button { background-color: #b91c1c; color: white; height: 52px; font-weight: 700; }
        .stButton > button:hover { background-color: #ef4444; box-shadow: 0 0 20px #ef4444; }

        .badge { padding: 6px 16px; border-radius: 9999px; font-weight: 700; }
        .prio-critica { background: #7f1d1d; color: #fecaca; border: 2px solid #ef4444; }
        .prio-alta    { background: #78350f; color: #fde047; border: 1px solid #fbbf24; }
        .prio-media   { background: #3f3f46; color: #d1d5db; }
        .prio-baixa   { background: #14532d; color: #86efac; }
    </style>
    """, unsafe_allow_html=True)

def header(titulo, subtitulo=None, icon="🏭"):
    st.markdown(f"""
    <div class="main-header">
        <h1>{icon} {titulo}</h1>
        {f'<p>{subtitulo}</p>' if subtitulo else ''}
    </div>
    """, unsafe_allow_html=True)

def badge_prioridade(prioridade):
    classes = {"Crítica": "prio-critica", "Alta": "prio-alta", "Média": "prio-media", "Baixa": "prio-baixa"}
    emoji = {"Crítica": "🔴", "Alta": "🟠", "Média": "🟡", "Baixa": "🟢"}
    return f'<span class="badge {classes.get(prioridade, "")}">{emoji.get(prioridade, "")} {prioridade}</span>'

def badge_status(status):
    emoji = {"Aberto": "📌", "Em Atendimento": "🔧", "Concluído": "✅"}
    return f'<span class="badge" style="background:#333;color:#ddd;">{emoji.get(status, "")} {status}</span>'

CORES_PRIORIDADE = {"Crítica": "#ef4444", "Alta": "#f59e0b", "Média": "#a3a3a3", "Baixa": "#4ade80"}
CORES_STATUS = {"Aberto": "#60a5fa", "Em Atendimento": "#fbbf24", "Concluído": "#4ade80"}