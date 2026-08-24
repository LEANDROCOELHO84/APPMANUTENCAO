"""
Gestão de Chamados e Manutenção — interface Streamlit.
Lógica de dados em database.py | tema em theme.py
"""
import os
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from notificacoes import (
    processar_alertas_chamados,
    ui_preferencias_notificacao,
    notificar,
)

from database import (
    # feedback
    efeito_concluido,
    agendar_efeito_concluido,
    _mostrar_efeito_pendente,
    comprimir_imagem,
    log_error,
    logger,
    # conexão / init
    init_db,
    is_cloud,
    get_connection_string,
    sync_local_to_cloud,
    _cloud_breaker_is_open,
    # chamados
    carregar_dados,
    salvar_chamado,
    proximo_id_chamado,
    # equipe / setores / equipamentos
    carregar_equipe,
    adicionar_membro_equipe,
    atualizar_membro_equipe,
    excluir_membro_equipe,
    carregar_setores,
    salvar_setores,
    carregar_equipamentos,
    salvar_equipamento,
    excluir_equipamento,
    proximo_id_equipamento,
    nome_equipamento,
    # manutenção
    carregar_historico_manutencao,
    salvar_manutencao,
    proximo_id_manutencao,
    concluir_preventiva,
    adiar_alerta_preventiva,
    custo_e_horas_por_equipamento,
    # compras
    carregar_compras,
    carregar_compras_por_chamado,
    historico_compras_item,
    criar_solicitacao_compra_do_chamado,
    salvar_compra,
    _notificar_chamado_compra,
    # util
    parse_datetime_safe,
    carregar_sla,
    salvar_sla,
    comprimir_imagem,
    reload_data,
    verificar_login_admin,
)

try:
    from theme import (
        aplicar_tema,
        header,
        badge_prioridade,
        badge_status,
        CORES_PRIORIDADE,
        CORES_STATUS,
    )
except ImportError:
    st.warning("Arquivo theme.py não encontrado. Usando tema padrão.")

    def aplicar_tema():
        pass

    def header(title, subtitle="", icon="🏭", nivel="principal"):
        st.title(f"{icon} {title}")
        if subtitle:
            st.markdown(f"_{subtitle}_")

    def badge_prioridade(prio):
        return f"**{prio}**"

    def badge_status(status):
        return f"**{status}**"

    CORES_PRIORIDADE = {}
    CORES_STATUS = {}

st.set_page_config(
    page_title="Gestão de Chamados Integrada",
    layout="wide",
    page_icon="🏭",
    initial_sidebar_state="collapsed",
)
aplicar_tema()
Path("fotos_chamados").mkdir(exist_ok=True)

# ====================== INICIALIZAÇÃO ======================
init_db()

# Sempre recarrega dados na 1ª carga da sessão (após bootstrap Cloud→Local).
# Em reruns seguintes, mantém session_state (performance); perfis de manutenção
# chamam reload_data() explicitamente.
if "chamados" not in st.session_state or st.session_state.get("_force_data_reload"):
    st.session_state.chamados = carregar_dados()
    st.session_state.equipe = carregar_equipe()
    st.session_state.setores = carregar_setores()
    st.session_state.equipamentos = carregar_equipamentos()
    st.session_state._force_data_reload = False
elif "equipe" not in st.session_state:
    st.session_state.equipe = carregar_equipe()
if "setores" not in st.session_state:
    st.session_state.setores = carregar_setores()
if "equipamentos" not in st.session_state:
    st.session_state.equipamentos = carregar_equipamentos()
if "admin_logado" not in st.session_state:
    st.session_state.admin_logado = False
if "edit_setor" not in st.session_state:
    st.session_state.edit_setor = None
if "edit_equip" not in st.session_state:
    st.session_state.edit_equip = None
if "edit_membro" not in st.session_state:
    st.session_state.edit_membro = None
if "os_em_edicao" not in st.session_state:
    st.session_state.os_em_edicao = None
if "pausar_refresh_manut" not in st.session_state:
    st.session_state.pausar_refresh_manut = False
if "ultimo_alarme" not in st.session_state:
    st.session_state.ultimo_alarme = datetime.now()

PRIORIDADES = {"Crítica": 1, "Alta": 2, "Média": 3, "Baixa": 4}
_SLA_PADRAO = {"Crítica": 20, "Alta": 60, "Média": 240, "Baixa": 1440}


def get_sla_tempo() -> dict:
    """Metas de SLA (minutos) — admin pode alterar; cache na sessão."""
    if "sla_tempo" not in st.session_state or not st.session_state.sla_tempo:
        try:
            st.session_state.sla_tempo = carregar_sla()
        except Exception:
            st.session_state.sla_tempo = dict(_SLA_PADRAO)
    return st.session_state.sla_tempo


# Compat: código legado que ainda referencia SLA_TEMPO
SLA_TEMPO = _SLA_PADRAO


def _safe_int(v, default: int = 0) -> int:
    """Converte valor para int tolerando None/NaN."""
    try:
        if v is None:
            return default
        try:
            if pd.isna(v):
                return default
        except (TypeError, ValueError):
            pass
        return int(float(v))
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_float(v, default: float = 0.0) -> float:
    """Converte valor para float tolerando None/NaN."""
    try:
        if v is None:
            return default
        try:
            if pd.isna(v):
                return default
        except (TypeError, ValueError):
            pass
        return float(v)
    except (TypeError, ValueError, OverflowError):
        return default


def formatar_duracao_minutos(minutos, *, absoluto: bool = True) -> str:
    """
    Formata duração a partir de minutos (todas as abas):
    < 60 → "X min"
    ≥ 60 → horas + minutos
    ≥ 24 h → dias + horas + minutos
    Ex.: "2 d 5 h 12 min"
    absoluto=True: ignora sinal (sempre positivo).
    """
    try:
        if minutos is None:
            return "—"
        try:
            if pd.isna(minutos):
                return "—"
        except (TypeError, ValueError):
            pass
        val = float(minutos)
        total = int(abs(val) if absoluto else max(0, val))
    except (TypeError, ValueError, OverflowError):
        return "—"
    if total < 60:
        return f"{total} min"
    dias, resto = divmod(total, 24 * 60)
    horas, mins = divmod(resto, 60)
    partes = []
    if dias:
        partes.append(f"{dias} d")
    if horas:
        partes.append(f"{horas} h")
    if mins or not partes:
        partes.append(f"{mins} min")
    return " ".join(partes)


def formatar_sla_restante(minutos) -> str:
    """
    Só o tempo do SLA (sem repetir o rótulo 'Além do prazo').
    Positivo = restante; negativo = quanto passou do esperado.
    """
    try:
        if minutos is None:
            return "—"
        try:
            if pd.isna(minutos):
                return "—"
        except (TypeError, ValueError):
            pass
        m = float(minutos)
    except (TypeError, ValueError, OverflowError):
        return "—"
    # Sempre mostra a magnitude formatada; o status (No prazo / Além do prazo)
    # fica no rótulo ao lado (sla_txt).
    return formatar_duracao_minutos(abs(m))


def formatar_duracao_horas(horas) -> str:
    """Formata duração a partir de horas (usa a mesma regra de minutos)."""
    try:
        if horas is None:
            return "—"
        try:
            if pd.isna(horas):
                return "—"
        except (TypeError, ValueError):
            pass
        return formatar_duracao_minutos(float(horas) * 60.0)
    except (TypeError, ValueError, OverflowError):
        return "—"


# Horário útil da manutenção (desconsidera descanso dos técnicos)
HORA_INICIO_EXPEDIENTE = 7   # 07:00
HORA_FIM_EXPEDIENTE = 19     # 19:00


def minutos_uteis_entre(inicio, fim=None) -> float | None:
    """
    Conta apenas minutos no expediente 07:00–19:00.
    Fora desse intervalo (noite / madrugada) não entra no tempo de demora.
    """
    try:
        if inicio is None:
            return None
        if not isinstance(inicio, datetime):
            inicio = parse_datetime_safe(inicio, default=None)
        if inicio is None:
            return None
        if fim is None:
            fim = datetime.now()
        elif not isinstance(fim, datetime):
            fim = parse_datetime_safe(fim, default=None)
            if fim is None:
                return None
        if fim <= inicio:
            return 0.0

        total = 0.0
        cursor = inicio
        # limita loops extremos (ex.: datas inválidas)
        for _ in range(370):  # ~1 ano
            if cursor >= fim:
                break
            dia_ini = cursor.replace(
                hour=HORA_INICIO_EXPEDIENTE, minute=0, second=0, microsecond=0
            )
            dia_fim = cursor.replace(
                hour=HORA_FIM_EXPEDIENTE, minute=0, second=0, microsecond=0
            )
            # janela útil deste dia ∩ [cursor, fim]
            start = max(cursor, dia_ini)
            end = min(fim, dia_fim)
            if end > start:
                total += (end - start).total_seconds() / 60.0
            # próximo dia 00:00 → na prática avança para o dia seguinte
            proximo = (cursor + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            if proximo <= cursor:
                break
            cursor = proximo
        return float(max(0.0, total))
    except Exception:
        return None


# ====================== CABEÇALHO ======================
header(
    "Gestão de Chamados e Manutenção",
    "Fluxo integrado de solicitações, execução e indicadores",
    icon="🏭",
)
_mostrar_efeito_pendente()

# Notificações push (browser + ntfy): novos abertos / aguardando peça
try:
    processar_alertas_chamados(st.session_state.get("chamados") or [])
except Exception:
    pass

# Indicador de modo de banco
status = st.session_state.get("db_status", {})
if get_connection_string() and _cloud_breaker_is_open():
    st.sidebar.warning("☁️ Cloud temporariamente instável — usando Local")
elif status.get("cloud_ok"):
    st.sidebar.success("☁️ Local + SQLite Cloud (dual-write)")
    boot = status.get("bootstrap") or ""
    if boot and "OK" in str(boot):
        st.sidebar.caption("🔄 Local reposto a partir do Cloud")
elif get_connection_string():
    st.sidebar.warning(f"⚠️ Cloud configurado mas offline: {status.get('cloud_msg', '?')}")
else:
    st.sidebar.caption("💾 Somente Local — configure SQLITECLOUD_URL nos secrets")

st.sidebar.header("🔑 Controle de Acesso")
perfil = st.sidebar.selectbox(
    "Escolha seu Perfil:",
    [
        "👤 Usuário Comum",
        "🛠️ Equipe de Manutenção",
        "🛒 Compras",
        "👨‍💼 Administrador",
    ],
)
ui_preferencias_notificacao()

# ====================== USUÁRIO COMUM ======================
if perfil == "👤 Usuário Comum":
    aba_novo, aba_historico = st.tabs(["🚀 Nova Solicitação", "📊 Histórico e Indicadores"])

    with aba_novo:
        with st.container(border=True):
            st.markdown("### 📸 Adicionar Foto (opcional)")
            foto_opcao = st.radio(
                "Como deseja adicionar a foto?",
                ["Sem foto", "Tirar foto agora", "Escolher da galeria"],
                horizontal=True,
                key="foto_novo",
            )
            foto_path = None
            if foto_opcao == "Tirar foto agora":
                foto = st.camera_input("Capturar Foto", key="cam_novo")
                if foto:
                    foto_path = comprimir_imagem(foto, "abertura")
            elif foto_opcao == "Escolher da galeria":
                arquivo = st.file_uploader(
                    "Selecione imagem", type=["jpg", "jpeg", "png"], key="up_novo"
                )
                if arquivo:
                    foto_path = comprimir_imagem(arquivo, "abertura")

        with st.form("novo_chamado", clear_on_submit=True):
            st.markdown("### 📝 Dados do chamado")
            nome = st.text_input("Solicitante *", placeholder="Seu nome completo")
            col1, col2 = st.columns(2)
            with col1:
                setor = st.selectbox("Setor / Área *", st.session_state.setores)
            with col2:
                eq_options = [nome_equipamento(eq) for eq in st.session_state.equipamentos] + ["N/A"]
                equipamento = st.selectbox("Equipamento", eq_options)
            prioridade = st.selectbox("Prioridade *", list(PRIORIDADES.keys()))
            descricao = st.text_area("Descrição do Problema *", height=120)

            if foto_path:
                st.success("✅ Foto anexada com sucesso!")

            if st.form_submit_button("🚀 ENVIAR SOLICITAÇÃO", width="stretch", type="primary"):
                if nome and descricao and setor:
                    novo_id = proximo_id_chamado()
                    novo = {
                        "id": novo_id,
                        "solicitante": nome.strip(),
                        "data_hora_abertura": datetime.now().isoformat(),
                        "setor": setor,
                        "equipamento": equipamento,
                        "prioridade": prioridade,
                        "descricao": descricao.strip(),
                        "status": "Aberto",
                        "executante": "",
                        "data_hora_inicio": None,
                        "data_hora_conclusao": None,
                        "foto_path": foto_path,
                        "solucao_descricao": "",
                        "foto_solucao_path": None,
                        "comentario_conclusao": "",
                        "peca_solicitada": "",
                        "peca_observacao": "",
                        "data_solicitacao_peca": None,
                    }
                    if salvar_chamado(novo):
                        st.session_state.chamados.append(novo)
                        try:
                            notificar(
                                f"🛎️ Novo chamado OS {novo_id}",
                                f"{prioridade} · {setor} · {nome.strip()}",
                                tag=f"novo-{novo_id}",
                            )
                        except Exception:
                            pass
                        agendar_efeito_concluido(
                            f"✅ Chamado Nº {novo_id} aberto com sucesso!",
                            celebrar=True,
                        )
                        st.rerun()
                else:
                    st.error("❌ Preencha os campos obrigatórios.")

    with aba_historico:
        header(
            "Meus indicadores",
            "Acompanhe status, tempos e o que está causando demora",
            icon="📊",
            nivel="secao",
        )
        if not st.session_state.chamados:
            st.info("Nenhum chamado registrado ainda.")
        else:
            df = pd.DataFrame(st.session_state.chamados).copy()
            if "status" not in df.columns:
                df["status"] = "Aberto"
            df["status"] = df["status"].fillna("Aberto").astype(str)

            # Filtro por solicitante (opcional) — visão do usuário
            solic_opts = ["(todos)"] + sorted(
                {
                    str(x).strip()
                    for x in df.get("solicitante", pd.Series(dtype=str)).fillna("").tolist()
                    if str(x).strip()
                }
            )
            f1, f2 = st.columns([2, 2])
            with f1:
                filtro_sol = st.selectbox(
                    "Filtrar por solicitante",
                    options=solic_opts,
                    key="hist_user_solicitante",
                )
            with f2:
                filtro_st = st.multiselect(
                    "Status",
                    options=["Aberto", "Em Atendimento", "Aguardando Peça", "Concluído"],
                    default=["Aberto", "Em Atendimento", "Aguardando Peça", "Concluído"],
                    key="hist_user_status",
                )
            if filtro_sol != "(todos)":
                df = df[df["solicitante"].astype(str) == filtro_sol]
            if filtro_st:
                df = df[df["status"].isin(filtro_st)]

            if df.empty:
                st.warning("Nenhum chamado com esses filtros.")
            else:
                n_aberto = int((df["status"] == "Aberto").sum())
                n_atend = int((df["status"] == "Em Atendimento").sum())
                n_peca = int((df["status"] == "Aguardando Peça").sum())
                n_ok = int((df["status"] == "Concluído").sum())
                total = len(df)

                # ---- Cards animados por status ----
                st.markdown(
                    """
                    <style>
                    .card-st {
                        border-radius: 14px; padding: 14px 16px; margin-bottom: 8px;
                        border: 1px solid rgba(255,255,255,.08);
                        background: linear-gradient(145deg, rgba(30,41,59,.85), rgba(15,23,42,.6));
                        transition: transform .25s ease, box-shadow .25s ease;
                    }
                    .card-st:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0,0,0,.25); }
                    .card-st .n { font-size: 1.8rem; font-weight: 800; line-height: 1.1; }
                    .card-st .lbl { font-size: .85rem; opacity: .85; margin-top: 4px; }
                    .card-aberto { border-left: 4px solid #ef4444; }
                    .card-atend { border-left: 4px solid #3b82f6; }
                    .card-peca { border-left: 4px solid #eab308; }
                    .card-ok { border-left: 4px solid #22c55e; animation: pulse-ok 2.4s ease-in-out infinite; }
                    @keyframes pulse-ok {
                        0%,100% { box-shadow: 0 0 0 0 rgba(34,197,94,.0); }
                        50% { box-shadow: 0 0 0 6px rgba(34,197,94,.12); }
                    }
                    .chip-etapa {
                        display: inline-block; padding: 4px 10px; border-radius: 999px;
                        font-size: .78rem; font-weight: 600; margin: 2px 4px 2px 0;
                        background: rgba(255,255,255,.06);
                    }
                    </style>
                    """,
                    unsafe_allow_html=True,
                )
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.markdown(
                        f'<div class="card-st card-aberto"><div class="n">{n_aberto}</div>'
                        f'<div class="lbl">🔴 Em aberto<br/><span style="opacity:.7">Na fila, aguardando técnico</span></div></div>',
                        unsafe_allow_html=True,
                    )
                with c2:
                    st.markdown(
                        f'<div class="card-st card-atend"><div class="n">{n_atend}</div>'
                        f'<div class="lbl">🔵 Em atendimento<br/><span style="opacity:.7">Técnico trabalhando</span></div></div>',
                        unsafe_allow_html=True,
                    )
                with c3:
                    st.markdown(
                        f'<div class="card-st card-peca"><div class="n">{n_peca}</div>'
                        f'<div class="lbl">🟡 Aguardando peça<br/><span style="opacity:.7">Dependendo de compras</span></div></div>',
                        unsafe_allow_html=True,
                    )
                with c4:
                    st.markdown(
                        f'<div class="card-st card-ok"><div class="n">{n_ok}</div>'
                        f'<div class="lbl">🟢 Concluídos<br/><span style="opacity:.7">Problema resolvido</span></div></div>',
                        unsafe_allow_html=True,
                    )

                # ---- SLA da equipe (metas) ----
                st.markdown("##### ⏱️ SLA da equipe de manutenção")
                st.caption(
                    "Meta de atendimento a partir da abertura do chamado "
                    "(definida pelo administrador)."
                )
                sla_eq = get_sla_tempo()
                sc1, sc2, sc3, sc4 = st.columns(4)
                sc1.metric("Crítica", formatar_duracao_minutos(sla_eq.get("Crítica", 20)))
                sc2.metric("Alta", formatar_duracao_minutos(sla_eq.get("Alta", 60)))
                sc3.metric("Média", formatar_duracao_minutos(sla_eq.get("Média", 240)))
                sc4.metric("Baixa", formatar_duracao_minutos(sla_eq.get("Baixa", 1440)))

                # ---- Por que está demorando? ----
                st.markdown("##### ⏱️ Entenda os tempos e a demora")
                st.caption(
                    f"⏱️ Conta só o **expediente {HORA_INICIO_EXPEDIENTE:02d}:00–{HORA_FIM_EXPEDIENTE:02d}:00**. "
                    "Após as 19h até as 7h é descanso da equipe e **não entra** no tempo de demora."
                )
                agora = datetime.now()

                def _min_uteis_desde(col, ate=None):
                    """Minutos úteis (07–19) desde a coluna até agora (ou até 'ate')."""
                    if col not in df.columns:
                        return pd.Series([None] * len(df), index=df.index)
                    vals = []
                    for _, row in df.iterrows():
                        vals.append(minutos_uteis_entre(row.get(col), ate or agora))
                    return pd.Series(vals, index=df.index)

                df["_min_aberto"] = _min_uteis_desde("data_hora_abertura")
                df["_min_inicio"] = _min_uteis_desde("data_hora_inicio")
                df["_min_peca"] = _min_uteis_desde("data_solicitacao_peca")

                abertos = df[df["status"] == "Aberto"]
                em_atend = df[df["status"] == "Em Atendimento"]
                aguard_peca = df[df["status"] == "Aguardando Peça"]
                concl = df[df["status"] == "Concluído"].copy()

                # Ciclo conclusão: só minutos úteis abertura → conclusão
                if (
                    not concl.empty
                    and "data_hora_abertura" in concl.columns
                    and "data_hora_conclusao" in concl.columns
                ):
                    durs = []
                    for _, row in concl.iterrows():
                        m = minutos_uteis_entre(
                            row.get("data_hora_abertura"),
                            row.get("data_hora_conclusao"),
                        )
                        durs.append((m / 60.0) if m is not None else None)
                    concl["_duracao_h"] = durs
                else:
                    concl["_duracao_h"] = pd.Series(dtype=float)

                media_fila = (
                    float(abertos["_min_aberto"].dropna().mean())
                    if len(abertos) and abertos["_min_aberto"].notna().any()
                    else None
                )
                media_atend = (
                    float(em_atend["_min_inicio"].dropna().mean())
                    if len(em_atend) and em_atend["_min_inicio"].notna().any()
                    else None
                )
                media_peca = (
                    float(aguard_peca["_min_peca"].dropna().mean())
                    if len(aguard_peca) and aguard_peca["_min_peca"].notna().any()
                    else None
                )
                media_ciclo = (
                    float(pd.Series(concl["_duracao_h"]).dropna().mean())
                    if len(concl) and pd.Series(concl["_duracao_h"]).notna().any()
                    else None
                )

                e1, e2, e3, e4 = st.columns(4)
                e1.metric(
                    "Tempo médio na fila",
                    formatar_duracao_minutos(media_fila),
                    help="Chamados ainda Abertos: tempo desde a abertura",
                )
                e2.metric(
                    "Em atendimento há",
                    formatar_duracao_minutos(media_atend),
                    help="Média desde o início do atendimento",
                )
                e3.metric(
                    "Aguardando peça há",
                    formatar_duracao_minutos(media_peca),
                    help="Média desde a solicitação da peça",
                )
                e4.metric(
                    "Ciclo até concluir",
                    formatar_duracao_horas(media_ciclo),
                    help="Tempo médio abertura → conclusão (já finalizados)",
                )

                # Explicação visual das etapas
                st.markdown(
                    """
                    <div style="margin:8px 0 12px 0;opacity:.9;font-size:.92rem;line-height:1.5">
                    <span class="chip-etapa">1️⃣ Aberto</span> → fila de prioridade (Crítica atende antes)<br/>
                    <span class="chip-etapa">2️⃣ Em atendimento</span> → técnico diagnosticando / reparando<br/>
                    <span class="chip-etapa">3️⃣ Aguardando peça</span> → compras cotando, aprovando e recebendo material<br/>
                    <span class="chip-etapa">4️⃣ Concluído</span> → serviço finalizado
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                # Gráficos relevantes
                g1, g2 = st.columns(2)
                with g1:
                    st_counts = (
                        df["status"]
                        .value_counts()
                        .reindex(
                            ["Aberto", "Em Atendimento", "Aguardando Peça", "Concluído"]
                        )
                        .fillna(0)
                        .reset_index()
                    )
                    st_counts.columns = ["status", "qtd"]
                    fig_st = px.pie(
                        st_counts[st_counts["qtd"] > 0],
                        names="status",
                        values="qtd",
                        hole=0.45,
                        title="Onde estão seus chamados agora",
                        color="status",
                        color_discrete_map={
                            "Aberto": CORES_STATUS.get("Aberto", "#ef4444"),
                            "Em Atendimento": CORES_STATUS.get("Em Atendimento", "#3b82f6"),
                            "Aguardando Peça": CORES_STATUS.get("Aguardando Peça", "#eab308"),
                            "Concluído": CORES_STATUS.get("Concluído", "#22c55e"),
                        },
                    )
                    st.plotly_chart(fig_st, width="stretch")
                with g2:
                    # Tempo em espera por status (ativos)
                    rows_wait = []
                    for _, r in df.iterrows():
                        stt = r.get("status")
                        if stt == "Aberto" and pd.notna(r.get("_min_aberto")):
                            rows_wait.append({"etapa": "Na fila (Aberto)", "minutos": max(0, float(r["_min_aberto"]))})
                        elif stt == "Em Atendimento" and pd.notna(r.get("_min_inicio")):
                            rows_wait.append({"etapa": "Em atendimento", "minutos": max(0, float(r["_min_inicio"]))})
                        elif stt == "Aguardando Peça" and pd.notna(r.get("_min_peca")):
                            rows_wait.append({"etapa": "Aguardando peça", "minutos": max(0, float(r["_min_peca"]))})
                    if rows_wait:
                        df_w = pd.DataFrame(rows_wait)
                        med = df_w.groupby("etapa", as_index=False)["minutos"].mean()
                        # Eixo em horas se média geral >= 60 min
                        usar_horas = float(med["minutos"].mean()) >= 60
                        if usar_horas:
                            med["tempo"] = (med["minutos"] / 60.0).round(1)
                            ycol, ylabel = "tempo", "Horas"
                        else:
                            med["tempo"] = med["minutos"].round(0)
                            ycol, ylabel = "tempo", "Minutos"
                        med["rotulo"] = med["minutos"].apply(formatar_duracao_minutos)
                        fig_w = px.bar(
                            med,
                            x="etapa",
                            y=ycol,
                            title="Tempo médio de espera por etapa (ativos)",
                            color="etapa",
                            text="rotulo",
                            color_discrete_sequence=["#ef4444", "#3b82f6", "#eab308"],
                        )
                        fig_w.update_traces(textposition="outside")
                        fig_w.update_layout(yaxis_title=ylabel, showlegend=False)
                        st.plotly_chart(fig_w, width="stretch")
                    else:
                        st.info("Sem chamados ativos para medir espera.")

                # Tempo de ciclo dos concluídos + prioridade
                h1, h2 = st.columns(2)
                with h1:
                    if not concl.empty and concl["_duracao_h"].notna().any():
                        fig_c = px.histogram(
                            concl.dropna(subset=["_duracao_h"]),
                            x="_duracao_h",
                            nbins=12,
                            title="Quanto tempo levou para concluir (horas)",
                            color_discrete_sequence=["#22c55e"],
                        )
                        fig_c.update_layout(xaxis_title="Horas", yaxis_title="Qtd")
                        st.plotly_chart(fig_c, width="stretch")
                    else:
                        st.caption("Ainda não há chamados concluídos com datas completas.")
                with h2:
                    if "prioridade" in df.columns:
                        fig_p = px.histogram(
                            df,
                            x="prioridade",
                            color="status",
                            barmode="group",
                            title="Prioridade × status (quem sobe na fila)",
                            color_discrete_map={
                                "Aberto": CORES_STATUS.get("Aberto", "#ef4444"),
                                "Em Atendimento": CORES_STATUS.get("Em Atendimento", "#3b82f6"),
                                "Aguardando Peça": CORES_STATUS.get("Aguardando Peça", "#eab308"),
                                "Concluído": CORES_STATUS.get("Concluído", "#22c55e"),
                            },
                            category_orders={
                                "prioridade": ["Crítica", "Alta", "Média", "Baixa"]
                            },
                        )
                        st.plotly_chart(fig_p, width="stretch")

                # Lista amigável dos chamados do solicitante
                st.markdown("##### 📋 Seus chamados")
                cols_show = [
                    c
                    for c in [
                        "id",
                        "status",
                        "prioridade",
                        "setor",
                        "equipamento",
                        "solicitante",
                        "executante",
                        "data_hora_abertura",
                        "data_hora_inicio",
                        "data_solicitacao_peca",
                        "data_hora_conclusao",
                        "peca_solicitada",
                        "descricao",
                        "solucao_descricao",
                    ]
                    if c in df.columns
                ]
                df_show = df[cols_show].copy()
                if "id" in df_show.columns:
                    df_show = df_show.sort_values("id", ascending=False)
                st.dataframe(
                    df_show,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "id": st.column_config.NumberColumn("OS", width="small"),
                        "status": st.column_config.TextColumn("Status", width="medium"),
                        "prioridade": st.column_config.TextColumn("Prioridade", width="small"),
                        "peca_solicitada": st.column_config.TextColumn("Peça", width="medium"),
                    },
                )

                # Detalhe de demora dos ativos
                ativos = df[df["status"].isin(["Aberto", "Em Atendimento", "Aguardando Peça"])]
                if not ativos.empty:
                    with st.expander("🔍 Detalhe: por que meu chamado pode estar demorando", expanded=False):
                        for _, r in ativos.sort_values("id", ascending=False).iterrows():
                            stt = r.get("status")
                            osid = r.get("id")
                            prio = r.get("prioridade") or "—"
                            motivo = ""
                            if stt == "Aberto":
                                m = r.get("_min_aberto")
                                motivo = (
                                    f"Na **fila** há **{formatar_duracao_minutos(m)}**. "
                                    f"Prioridade **{prio}** — chamados Crítica/Alta passam na frente."
                                    if pd.notna(m)
                                    else "Aguardando técnico assumir."
                                )
                            elif stt == "Em Atendimento":
                                m = r.get("_min_inicio")
                                tec = r.get("executante") or "técnico"
                                motivo = (
                                    f"Com **{tec}** há **{formatar_duracao_minutos(m)}**. "
                                    "Pode envolver diagnóstico, teste ou desmontagem."
                                    if pd.notna(m)
                                    else f"Em atendimento por {tec}."
                                )
                            else:
                                m = r.get("_min_peca")
                                peca = r.get("peca_solicitada") or "peça"
                                motivo = (
                                    f"Aguardando **{peca}** há **{formatar_duracao_minutos(m)}**. "
                                    "Etapa de compras (cotação → aprovação → entrega)."
                                    if pd.notna(m)
                                    else f"Aguardando peça: {peca}."
                                )
                            st.markdown(
                                f"**OS {osid}** · {stt} · {r.get('equipamento') or '—'}  \n"
                                f"{motivo}"
                            )

# ====================== EQUIPE DE MANUTENÇÃO ======================
elif perfil == "🛠️ Equipe de Manutenção":
    header(
        "Fila de Manutenção",
        "Chamados priorizados e alertas preventivos",
        icon="🛠️",
        nivel="secao",
    )
    reload_data()

    col_f1, col_f2, col_f3 = st.columns([3, 2, 2])
    with col_f1:
        tecnicos = ["Todos os Técnicos"] + [
            row["nome"]
            for _, row in st.session_state.equipe.iterrows()
            if row.get("ativo") == 1
        ]
        filtro_tecnico = st.selectbox("🔎 Filtrar por Técnico", tecnicos, key="filtro_tecnico_main")
    with col_f2:
        filtro_status = st.multiselect(
            "Status",
            ["Aberto", "Em Atendimento", "Aguardando Peça"],
            default=["Aberto", "Em Atendimento", "Aguardando Peça"],
            key="filtro_status_main",
        )
    with col_f3:
        filtro_setor = st.multiselect("Setor", st.session_state.setores, key="filtro_setor_main")

    # Pausa o auto-refresh enquanto o técnico preenche formulário (evita sumir o texto)
    if "pausar_refresh_manut" not in st.session_state:
        st.session_state.pausar_refresh_manut = False
    if st.session_state.get("os_em_edicao"):
        st.session_state.pausar_refresh_manut = True
    col_rf1, col_rf2 = st.columns([3, 2])
    with col_rf1:
        st.session_state.pausar_refresh_manut = st.checkbox(
            "⏸️ Pausar atualização automática (recomendado ao digitar)",
            value=bool(st.session_state.pausar_refresh_manut),
            key="chk_pausar_refresh_manut",
            help="Desliga o reload automático para o texto do formulário não sumir.",
        )
    with col_rf2:
        if st.session_state.get("os_em_edicao"):
            st.info(f"✏️ Editando OS **{st.session_state.os_em_edicao}**")
            if st.button("Fechar edição", key="btn_fechar_os_edicao"):
                st.session_state.os_em_edicao = None
                st.session_state.pausar_refresh_manut = False
                st.rerun()
    if not st.session_state.pausar_refresh_manut:
        # 45s: reduz carga no Cloud e risco de instabilidade do driver sqlitecloud
        st_autorefresh(interval=45000, limit=None, key="refresh_maintenance")
    else:
        st.caption("🔄 Atualização automática pausada")


    # Alertas sonoros + notificação periódica (beep + push)
    chamados_abertos = [c for c in st.session_state.chamados if c.get("status") == "Aberto"]
    if chamados_abertos:
        agora = datetime.now()
        if (agora - st.session_state.ultimo_alarme).total_seconds() >= 60:
            st.success(f"🛎️ **{len(chamados_abertos)} chamado(s) ABERTO(S)** aguardando!")
            try:
                notificar(
                    f"🛎️ {len(chamados_abertos)} chamado(s) aberto(s)",
                    "Há OS aguardando atendimento na fila de manutenção.",
                    tag="fila-abertos",
                )
            except Exception:
                pass
            beep_path = Path("beep-09.mp3")
            if beep_path.is_file():
                import base64
                b64 = base64.b64encode(beep_path.read_bytes()).decode("ascii")
                st.markdown(
                    f'<audio autoplay><source src="data:audio/mpeg;base64,{b64}" type="audio/mpeg"></audio>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<audio autoplay><source src="https://www.soundjay.com/buttons/beep-07.mp3" type="audio/mpeg"></audio>',
                    unsafe_allow_html=True,
                )
            st.session_state.ultimo_alarme = agora

    # ====================== ALERTAS PREVENTIVOS (compacto · tema + ações) ======================
    hoje = datetime.now().date()
    alertas_lista = []
    nomes_tecnicos_ativos = [
        row["nome"]
        for _, row in st.session_state.equipe.iterrows()
        if row.get("ativo") == 1
    ]

    for eq in st.session_state.equipamentos:
        if not eq.get("proxima_preventiva"):
            continue
        try:
            # Respeita silenciar_ate (adiar alerta)
            sil = eq.get("silenciar_ate")
            if sil:
                try:
                    sil_dt = datetime.fromisoformat(str(sil)).date()
                    if sil_dt > hoje:
                        continue
                except Exception:
                    pass
            prox = datetime.fromisoformat(str(eq["proxima_preventiva"])).date()
            if prox <= hoje + timedelta(days=30):
                dias = (prox - hoje).days
                alertas_lista.append({
                    "eq": eq,
                    "id": eq.get("id"),
                    "nome": nome_equipamento(eq),
                    "setor": eq.get("setor") or "—",
                    "data": prox.strftime("%d/%m/%Y"),
                    "dias": dias,
                })
        except Exception:
            continue

    with st.container(border=True):
        if not alertas_lista:
            st.success("✅ Nenhum alerta preventivo nos próximos 30 dias.")
        else:
            alertas_lista.sort(key=lambda x: x["dias"])
            vencidos = sum(1 for a in alertas_lista if a["dias"] < 0)
            urgentes = sum(1 for a in alertas_lista if 0 <= a["dias"] <= 7)
            normais = len(alertas_lista) - vencidos - urgentes

            partes = [f"{len(alertas_lista)} alerta(s)"]
            if vencidos:
                partes.append(f"🔴 {vencidos} fora do prazo")
            if urgentes:
                partes.append(f"🟠 {urgentes} ≤ 7 dias")
            if normais:
                partes.append(f"🟡 {normais} em até 30 dias")

            # Expander principal sempre fechado; só prioritários visíveis ao abrir
            prioritarios = [a for a in alertas_lista if a["dias"] <= 7]
            demais = [a for a in alertas_lista if a["dias"] > 7]

            def _render_alerta_prev(a, idx, prefix):
                eq_id = a["id"]
                uk = f"{prefix}_{eq_id}_{idx}"
                if a["dias"] < 0:
                    badge_txt, badge_bg, badge_fg, border = (
                        "🔴 Fora do prazo", "#7f1d1d", "#fecaca", "#ef4444",
                    )
                    prazo = f"há {abs(a['dias'])} dia(s)"
                elif a["dias"] == 0:
                    badge_txt, badge_bg, badge_fg, border = (
                        "🔴 HOJE", "#7f1d1d", "#fecaca", "#ef4444",
                    )
                    prazo = "hoje"
                elif a["dias"] <= 7:
                    badge_txt, badge_bg, badge_fg, border = (
                        "🟠 URGENTE", "#78350f", "#fde047", "#fbbf24",
                    )
                    prazo = f"em {a['dias']} dia(s)"
                else:
                    badge_txt, badge_bg, badge_fg, border = (
                        "🟡 EM BREVE", "#3f3f46", "#facc15", "#a3a3a3",
                    )
                    prazo = f"em {a['dias']} dia(s)"

                st.markdown(
                    f"""
                    <div style="
                        display:flex; align-items:center; justify-content:space-between;
                        gap:12px; padding:10px 14px; margin:6px 0 2px 0;
                        border-radius:12px; border:1px solid #333;
                        border-left:4px solid {border};
                        background:#111111;
                    ">
                        <div style="flex:1; min-width:0;">
                            <div style="font-weight:700; color:#f1f1f1; font-size:0.95rem;
                                        white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                                {a['nome']}
                            </div>
                            <div style="font-size:0.82rem; color:#a3a3a3; margin-top:2px;">
                                {a['setor']} · {a['data']} · {prazo}
                            </div>
                        </div>
                        <span class="badge" style="
                            flex-shrink:0; background:{badge_bg}; color:{badge_fg};
                            border:1px solid {border}; padding:5px 12px;
                            border-radius:9999px; font-weight:700; font-size:0.75rem;
                        ">{badge_txt}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                with st.popover(
                    "⚙️ Registrar / Adiar",
                    key=f"pop_prev_{uk}",
                    width="stretch",
                ):
                    st.caption(f"**{a['nome']}**")
                    tec = st.selectbox(
                        "Executante",
                        [""] + nomes_tecnicos_ativos,
                        key=f"prev_tec_{uk}",
                    )
                    desc = st.text_area(
                        "Descrição / serviços realizados",
                        key=f"prev_desc_{uk}",
                        height=70,
                    )
                    pecas = st.text_input(
                        "Peças trocadas",
                        key=f"prev_pecas_{uk}",
                        placeholder="Ex.: rolamento 6205, correia A",
                    )
                    c1, c2 = st.columns(2)
                    with c1:
                        custo = st.number_input(
                            "Custo peças (R$)",
                            min_value=0.0,
                            step=10.0,
                            key=f"prev_custo_{uk}",
                        )
                    with c2:
                        horas = st.number_input(
                            "Horas-homem",
                            min_value=0.0,
                            step=0.5,
                            key=f"prev_horas_{uk}",
                        )
                    if st.button(
                        "✅ Concluir preventiva",
                        key=f"prev_ok_{uk}",
                        type="primary",
                        width="stretch",
                    ):
                        if concluir_preventiva(
                            a["eq"],
                            executante=tec or "",
                            descricao=desc or "",
                            pecas=pecas or "",
                            custo_pecas=float(custo or 0),
                            horas_homem=float(horas or 0),
                        ):
                            agendar_efeito_concluido(
                                "✅ Preventiva concluída e próxima data recalculada!",
                                celebrar=True,
                            )
                            reload_data()
                            st.rerun()

                    st.divider()
                    dias_adiar = st.selectbox(
                        "Adiar alerta por",
                        [7, 14, 30],
                        format_func=lambda d: f"{d} dias",
                        key=f"prev_adiar_d_{uk}",
                    )
                    if st.button(
                        "🔕 Silenciar alerta",
                        key=f"prev_adiar_{uk}",
                        width="stretch",
                    ):
                        if adiar_alerta_preventiva(a["eq"], dias=int(dias_adiar)):
                            agendar_efeito_concluido(
                                f"🔕 Alerta silenciado por {dias_adiar} dias.",
                                celebrar=False,
                            )
                            reload_data()
                            st.rerun()

            with st.expander(
                f"⚠️ Manutenção Preventiva — {' · '.join(partes)}",
                expanded=False,
            ):
                if prioritarios:
                    st.caption("Prioridade (hoje / fora do prazo / ≤ 7 dias)")
                    for idx, a in enumerate(prioritarios):
                        _render_alerta_prev(a, idx, "prio")
                if demais:
                    with st.expander(
                        f"Em breve (8–30 dias) — {len(demais)} item(ns)",
                        expanded=False,
                    ):
                        for idx, a in enumerate(demais):
                            _render_alerta_prev(a, idx, "demais")

    # Filtragem
    ativos = [c for c in st.session_state.chamados if c.get("status") in filtro_status]
    if filtro_tecnico != "Todos os Técnicos":
        ativos = [c for c in ativos if c.get("executante") == filtro_tecnico]
    if filtro_setor:
        ativos = [c for c in ativos if c.get("setor") in filtro_setor]

    def ordem_chamado(c):
        prio = PRIORIDADES.get(c.get("prioridade"), 999)
        abertura_dt = parse_datetime_safe(c.get("data_hora_abertura"), default=datetime.min)
        sla_score = (
            abertura_dt
            + timedelta(minutes=get_sla_tempo().get(c.get("prioridade"), 1440))
            - datetime.now()
        ).total_seconds()
        return (prio, sla_score, abertura_dt)

    ativos_ordenados = sorted(ativos, key=ordem_chamado)

    if not ativos_ordenados:
        st.success("🎉 Nenhum chamado ativo com os filtros atuais.")
    else:
        st.subheader(f"📋 Chamados Ativos ({len(ativos_ordenados)})")
        st.caption(
            "Lista compacta: abra o **popover** do chamado para atender. "
            "Marque **Pausar atualização** antes de digitar a solução."
        )

        for cham in ativos_ordenados:
            cid = cham.get("id")
            try:
                cid_int = int(cid)
            except (TypeError, ValueError):
                cid_int = cid

            abertura_dt = parse_datetime_safe(
                cham.get("data_hora_abertura"), default=datetime.now()
            )
            prazo = abertura_dt + timedelta(
                minutes=get_sla_tempo().get(cham.get("prioridade"), 1440)
            )
            try:
                min_restantes = int((prazo - datetime.now()).total_seconds() / 60)
            except (ValueError, TypeError, OverflowError):
                min_restantes = 0
            prio = cham.get("prioridade") or "—"
            setor = cham.get("setor") or "—"
            sol = cham.get("solicitante") or "—"
            status = cham.get("status") or "—"
            equip = (cham.get("equipamento") or "").strip() or "N/A"

            # Indicador de andamento + prazo SLA (meta da prioridade)
            sla_map = get_sla_tempo()
            try:
                meta_min = int(sla_map.get(prio, 1440))
            except (TypeError, ValueError):
                meta_min = 1440
            prazo_txt = formatar_sla_restante(min_restantes)
            if min_restantes < 0:
                prazo_html = (
                    f'<span class="os-prazo-alem">⏱️ Prazo: além · {prazo_txt}</span>'
                )
            elif min_restantes < 30:
                prazo_html = (
                    f'<span class="os-prazo-atencao">⏱️ Prazo: {prazo_txt} restantes</span>'
                )
            else:
                prazo_html = (
                    f'<span class="os-prazo-ok">⏱️ Prazo: {prazo_txt} restantes</span>'
                )

            if status == "Em Atendimento":
                ind_html = (
                    '<span class="os-trabalhando">'
                    '<span class="os-trab-dot"></span> '
                    '⚙️ Trabalhando · rumo à conclusão'
                    '</span>'
                )
            elif status == "Aberto":
                ind_html = (
                    '<span class="os-fila">'
                    '<span class="os-fila-pulse"></span> '
                    '⏳ Na fila · aguardando técnico'
                    '</span>'
                )
            elif status == "Aguardando Peça":
                ind_html = (
                    '<span class="os-peca">'
                    '🛒 Aguardando peça / material'
                    '</span>'
                )
            elif status == "Concluído":
                ind_html = (
                    '<span class="os-ok">✅ Concluído</span>'
                )
                prazo_html = ""  # concluído não precisa de prazo restante
            else:
                ind_html = ""

            # Linha compacta: OS · prioridade · setor · equipamento · solicitante
            with st.container(border=True):
                c_sum, c_pop = st.columns([5, 2])
                with c_sum:
                    st.markdown(
                        f"**OS {cid}** &nbsp; {badge_prioridade(prio)} &nbsp; "
                        f"{badge_status(status)} &nbsp; {ind_html}"
                        + (f" &nbsp; {prazo_html}" if prazo_html else "")
                        + "<br/>"
                        f"<span style='opacity:.9'>🏭 {setor}</span> · "
                        f"<span style='opacity:.95;font-weight:600'>⚙️ {equip}</span> · "
                        f"<span style='opacity:.9'>👤 {sol}</span>"
                        + (
                            f" · 🔧 {cham.get('executante')}"
                            if cham.get("executante")
                            else ""
                        ),
                        unsafe_allow_html=True,
                    )
                with c_pop:
                    # Rótulo do popover com equipamento
                    equip_curto = equip if len(equip) <= 28 else equip[:25] + "…"
                    pop_label = f"OS {cid} · {equip_curto}"
                    with st.popover(pop_label, key=f"pop_os_{cid}", width="stretch"):
                        st.markdown(f"### OS Nº {cid}")
                        st.markdown(
                            f"{badge_prioridade(prio)} {badge_status(status)} &nbsp; {ind_html}"
                            + (f"<br/>{prazo_html}" if prazo_html else ""),
                            unsafe_allow_html=True,
                        )
                        st.markdown(f"**⚙️ Equipamento:** {equip}")
                        st.write(f"**Setor:** {setor}")
                        st.write(f"**Solicitante:** {sol}")
                        if cham.get("executante"):
                            st.write(f"**Técnico:** {cham.get('executante')}")
                        st.write(f"**Descrição:** {cham.get('descricao') or '—'}")
                        fp = cham.get("foto_path")
                        if fp and isinstance(fp, str) and os.path.exists(fp):
                            st.image(fp, width="stretch")

                        # Marca OS em edição → pausa refresh
                        if st.button(
                            "✏️ Preencher neste chamado",
                            key=f"focus_os_{cid}",
                            width="stretch",
                        ):
                            st.session_state.os_em_edicao = cid_int
                            st.session_state.pausar_refresh_manut = True
                            st.rerun()

                        if cham.get("status") == "Aberto":
                            nome_tec = st.selectbox(
                                "Selecionar Técnico:",
                                tecnicos[1:] if len(tecnicos) > 1 else ["—"],
                                key=f"t_{cid}",
                            )
                            if st.button(
                                "🚀 Iniciar Atendimento",
                                key=f"b_ini_{cid}",
                                type="primary",
                                width="stretch",
                            ):
                                if nome_tec and nome_tec != "—":
                                    cham["status"] = "Em Atendimento"
                                    cham["executante"] = nome_tec
                                    cham["data_hora_inicio"] = datetime.now().isoformat()
                                    if salvar_chamado(cham):
                                        st.session_state.os_em_edicao = None
                                        agendar_efeito_concluido(
                                            f"🚀 OS {cid} iniciada por {nome_tec}!",
                                            celebrar=True,
                                        )
                                        st.rerun()

                        elif cham.get("status") == "Aguardando Peça":
                            st.caption(f"👨‍🔧 Técnico: **{cham.get('executante')}**")
                            st.warning(
                                f"🛒 Aguardando peça: "
                                f"**{cham.get('peca_solicitada') or 'Não informado'}**"
                            )
                            if cham.get("peca_observacao"):
                                st.caption(f"📝 {cham.get('peca_observacao')}")
                            compras_ch = carregar_compras_por_chamado(int(cid_int or 0))
                            peca_ja_recebida = False
                            for cp in compras_ch:
                                st.info(
                                    f"**Compras #{cp.get('id')}** · {cp.get('status')} · "
                                    f"Valor: R$ {float(cp.get('valor_item') or 0):,.2f}"
                                )
                                if str(cp.get("status") or "") == "Recebida":
                                    peca_ja_recebida = True
                            if peca_ja_recebida:
                                st.success("✅ Compra recebida — pode retomar.")
                            if st.button(
                                "📦 Peça Recebida — Retomar Atendimento",
                                key=f"b_retomar_{cid}",
                                type="primary",
                                width="stretch",
                            ):
                                agora = datetime.now()
                                cham["status"] = "Em Atendimento"
                                if not cham.get("data_hora_inicio"):
                                    cham["data_hora_inicio"] = agora.isoformat()
                                for cp in compras_ch:
                                    if cp.get("status") in (
                                        "Aprovada",
                                        "Comprada",
                                        "Pendente",
                                        "Recebida",
                                    ):
                                        cp["status"] = "Recebida"
                                        if not cp.get("data_recebimento"):
                                            cp["data_recebimento"] = agora.strftime(
                                                "%Y-%m-%d %H:%M:%S"
                                            )
                                        salvar_compra(cp)
                                if salvar_chamado(cham):
                                    agendar_efeito_concluido(
                                        f"📦 OS {cid} retomada!",
                                        celebrar=True,
                                    )
                                    st.rerun()

                        else:
                            # Em Atendimento
                            st.caption(f"👨‍🔧 Técnico: **{cham.get('executante')}**")

                            # Rascunhos em session_state (sobrevivem ao rerun)
                            k_sol = f"draft_solucao_{cid}"
                            k_com = f"draft_comentario_{cid}"
                            k_peca = f"draft_peca_{cid}"
                            k_pobs = f"draft_peca_obs_{cid}"
                            if k_sol not in st.session_state:
                                st.session_state[k_sol] = cham.get("solucao_descricao") or ""
                            if k_com not in st.session_state:
                                st.session_state[k_com] = cham.get("comentario_conclusao") or ""
                            if k_peca not in st.session_state:
                                st.session_state[k_peca] = cham.get("peca_solicitada") or ""
                            if k_pobs not in st.session_state:
                                st.session_state[k_pobs] = cham.get("peca_observacao") or ""

                            with st.expander("🛒 Solicitar peça / material", expanded=False):
                                st.text_input(
                                    "Peça / material necessário",
                                    key=k_peca,
                                )
                                st.text_area(
                                    "Observação da solicitação",
                                    key=k_pobs,
                                    height=70,
                                )
                                if st.button(
                                    "📤 Enviar para Compras",
                                    key=f"b_peca_{cid}",
                                    type="primary",
                                    width="stretch",
                                ):
                                    peca = (st.session_state.get(k_peca) or "").strip()
                                    if not peca:
                                        st.error("Informe a peça.")
                                    else:
                                        pobs = (st.session_state.get(k_pobs) or "").strip()
                                        cham["status"] = "Aguardando Peça"
                                        cham["peca_solicitada"] = peca
                                        cham["peca_observacao"] = pobs
                                        cham["data_solicitacao_peca"] = (
                                            datetime.now().isoformat()
                                        )
                                        salvar_chamado(cham)
                                        try:
                                            salvar_compra(
                                                {
                                                    "chamado_id": int(cid_int),
                                                    "item_nome": peca,
                                                    "equipamento": cham.get("equipamento")
                                                    or "",
                                                    "solicitante": cham.get("executante")
                                                    or "",
                                                    "status": "Pendente",
                                                    "observacao": pobs,
                                                    "data_solicitacao": datetime.now().strftime(
                                                        "%Y-%m-%d %H:%M:%S"
                                                    ),
                                                }
                                            )
                                        except Exception:
                                            pass
                                        st.session_state.os_em_edicao = None
                                        agendar_efeito_concluido(
                                            f"🛒 OS {cid}: peça solicitada!",
                                            celebrar=False,
                                        )
                                        st.rerun()

                            st.text_area(
                                "📝 Descrição da solução *",
                                key=k_sol,
                                height=120,
                                help="Texto fica salvo na sessão mesmo se a tela atualizar.",
                            )
                            foto_op_sol = st.radio(
                                "📷 Foto da solução",
                                ["Sem foto", "Tirar foto", "Galeria"],
                                horizontal=True,
                                key=f"foto_op_sol_{cid}",
                            )
                            if foto_op_sol == "Tirar foto":
                                st.camera_input(
                                    "Capturar foto da solução",
                                    key=f"foto_sol_{cid}",
                                )
                            elif foto_op_sol == "Galeria":
                                st.file_uploader(
                                    "Enviar imagem",
                                    type=["jpg", "jpeg", "png", "webp"],
                                    key=f"foto_sol_up_{cid}",
                                )
                            st.text_area(
                                "💬 Comentário adicional",
                                key=k_com,
                                height=70,
                            )

                            b1, b2 = st.columns(2)
                            with b1:
                                if st.button(
                                    "💾 Salvar rascunho",
                                    key=f"b_salvar_com_{cid}",
                                    width="stretch",
                                ):
                                    cham["solucao_descricao"] = (
                                        st.session_state.get(k_sol) or ""
                                    ).strip()
                                    cham["comentario_conclusao"] = (
                                        st.session_state.get(k_com) or ""
                                    ).strip()
                                    if salvar_chamado(cham):
                                        agendar_efeito_concluido(
                                            "💾 Rascunho salvo!",
                                            celebrar=False,
                                        )
                                        st.rerun()
                            with b2:
                                if st.button(
                                    "✅ Concluir Chamado",
                                    key=f"b_fim_{cid}",
                                    type="primary",
                                    width="stretch",
                                ):
                                    solucao_txt = (
                                        st.session_state.get(k_sol) or ""
                                    ).strip()
                                    if not solucao_txt:
                                        st.error("Descreva a solução.")
                                    else:
                                        foto_sol = None
                                        foto_widget = st.session_state.get(
                                            f"foto_sol_{cid}"
                                        ) or st.session_state.get(
                                            f"foto_sol_up_{cid}"
                                        )
                                        if foto_widget is not None:
                                            try:
                                                foto_sol = comprimir_imagem(
                                                    foto_widget, prefixo=f"solucao_{cid}"
                                                )
                                            except Exception:
                                                foto_sol = None
                                        cham["status"] = "Concluído"
                                        cham["solucao_descricao"] = solucao_txt
                                        cham["foto_solucao_path"] = foto_sol
                                        cham["comentario_conclusao"] = (
                                            st.session_state.get(k_com) or ""
                                        ).strip()
                                        cham["data_hora_conclusao"] = (
                                            datetime.now().isoformat()
                                        )
                                        if salvar_chamado(cham):
                                            for k in (k_sol, k_com, k_peca, k_pobs):
                                                st.session_state.pop(k, None)
                                            st.session_state.os_em_edicao = None
                                            agendar_efeito_concluido(
                                                f"✅ Chamado Nº {cid} concluído!",
                                                celebrar=True,
                                            )
                                            st.rerun()

        # Se há OS focada, mostra formulário expandido FORA do popover
        # (popover fecha fácil; o painel fixo evita perder o texto)
        os_foco = st.session_state.get("os_em_edicao")
        if os_foco is not None:
            cham_foco = next(
                (
                    c
                    for c in ativos_ordenados
                    if str(c.get("id")) == str(os_foco)
                ),
                None,
            )
            if cham_foco and cham_foco.get("status") == "Em Atendimento":
                st.divider()
                st.markdown(f"### ✏️ Atendimento — OS **{os_foco}**")
                st.caption(
                    f"{cham_foco.get('setor')} · {cham_foco.get('prioridade')} · "
                    f"{cham_foco.get('solicitante')} · {cham_foco.get('equipamento') or ''}"
                )
                st.info(cham_foco.get("descricao") or "")
                k_sol = f"draft_solucao_{os_foco}"
                k_com = f"draft_comentario_{os_foco}"
                if k_sol not in st.session_state:
                    st.session_state[k_sol] = cham_foco.get("solucao_descricao") or ""
                if k_com not in st.session_state:
                    st.session_state[k_com] = cham_foco.get("comentario_conclusao") or ""
                st.text_area("📝 Solução *", key=k_sol, height=140)
                st.text_area("💬 Comentário", key=k_com, height=80)
                foto_op_foco = st.radio(
                    "📷 Foto da solução",
                    ["Sem foto", "Tirar foto", "Galeria"],
                    horizontal=True,
                    key=f"foto_op_foco_{os_foco}",
                )
                if foto_op_foco == "Tirar foto":
                    st.camera_input(
                        "Capturar foto da solução",
                        key=f"foto_sol_foco_{os_foco}",
                    )
                elif foto_op_foco == "Galeria":
                    st.file_uploader(
                        "Enviar imagem",
                        type=["jpg", "jpeg", "png", "webp"],
                        key=f"foto_sol_foco_up_{os_foco}",
                    )
                fb1, fb2, fb3 = st.columns(3)
                with fb1:
                    if st.button("💾 Salvar rascunho", key="foco_salvar", width="stretch"):
                        cham_foco["solucao_descricao"] = (
                            st.session_state.get(k_sol) or ""
                        ).strip()
                        cham_foco["comentario_conclusao"] = (
                            st.session_state.get(k_com) or ""
                        ).strip()
                        if salvar_chamado(cham_foco):
                            agendar_efeito_concluido("💾 Rascunho salvo!", celebrar=False)
                            st.rerun()
                with fb2:
                    if st.button(
                        "✅ Concluir",
                        key="foco_concluir",
                        type="primary",
                        width="stretch",
                    ):
                        solucao_txt = (st.session_state.get(k_sol) or "").strip()
                        if not solucao_txt:
                            st.error("Descreva a solução.")
                        else:
                            foto_sol = None
                            fw = st.session_state.get(
                                f"foto_sol_foco_{os_foco}"
                            ) or st.session_state.get(
                                f"foto_sol_foco_up_{os_foco}"
                            )
                            if fw is not None:
                                try:
                                    foto_sol = comprimir_imagem(
                                        fw, prefixo=f"solucao_{os_foco}"
                                    )
                                except Exception:
                                    pass
                            cham_foco["status"] = "Concluído"
                            cham_foco["solucao_descricao"] = solucao_txt
                            cham_foco["comentario_conclusao"] = (
                                st.session_state.get(k_com) or ""
                            ).strip()
                            cham_foco["foto_solucao_path"] = foto_sol
                            cham_foco["data_hora_conclusao"] = datetime.now().isoformat()
                            if salvar_chamado(cham_foco):
                                st.session_state.os_em_edicao = None
                                st.session_state.pausar_refresh_manut = False
                                agendar_efeito_concluido(
                                    f"✅ OS {os_foco} concluída!",
                                    celebrar=True,
                                )
                                st.rerun()
                with fb3:
                    if st.button("Fechar painel", key="foco_fechar", width="stretch"):
                        st.session_state.os_em_edicao = None
                        st.rerun()


# ====================== COMPRAS ======================
elif perfil == "🛒 Compras":
    header(
        "Setor de Compras",
        "Solicitações de peças · aprovação · recebimento",
        icon="🛒",
        nivel="secao",
    )
    reload_data()
    compras = carregar_compras()

    col_f1, col_f2 = st.columns([3, 2])
    with col_f1:
        filtro_cp = st.multiselect(
            "Status",
            ["Pendente", "Aprovada", "Rejeitada", "Recebida"],
            default=["Pendente", "Aprovada"],
            key="filtro_compras_status",
        )
    with col_f2:
        busca_cp = st.text_input(
            "🔍 Buscar (item, OS, equipamento)",
            key="busca_compras",
            placeholder="Ex.: painel, OS 50…",
        )

    lista_cp = [c for c in compras if (c.get("status") or "Pendente") in filtro_cp]
    if busca_cp and busca_cp.strip():
        q = busca_cp.strip().lower()
        lista_cp = [
            c
            for c in lista_cp
            if q in str(c.get("item_nome") or "").lower()
            or q in str(c.get("chamado_id") or "").lower()
            or q in str(c.get("equipamento") or "").lower()
            or q in str(c.get("solicitante") or "").lower()
        ]

    # Ordena: Pendente primeiro, depois Aprovada
    ordem_st = {"Pendente": 0, "Aprovada": 1, "Rejeitada": 2, "Recebida": 3}
    lista_cp = sorted(
        lista_cp,
        key=lambda c: (
            ordem_st.get(str(c.get("status") or "Pendente"), 9),
            -(int(c.get("id") or 0) if str(c.get("id") or "").isdigit() else 0),
        ),
    )

    if not lista_cp:
        st.success("🎉 Nenhuma solicitação com os filtros atuais.")
    else:
        st.subheader(f"🛒 Solicitações ({len(lista_cp)})")
        st.caption(
            "Lista compacta — abra o **popover** para analisar, aprovar ou marcar recebimento."
        )

        for cp in lista_cp:
            cid = cp.get("id")
            status = cp.get("status") or "Pendente"
            item = (cp.get("item_nome") or "—").strip()
            equip = (cp.get("equipamento") or "—").strip()
            os_n = cp.get("chamado_id") or "—"
            prio = cp.get("prioridade") or "—"
            sol = cp.get("solicitante") or "—"
            valor = float(cp.get("valor_item") or 0)

            # Badge simples de status
            if status == "Pendente":
                badge_st = "🟡 Pendente"
            elif status == "Aprovada":
                badge_st = "🟢 Aprovada"
            elif status == "Recebida":
                badge_st = "🔵 Recebida"
            else:
                badge_st = f"🔴 {status}"

            item_curto = item if len(item) <= 32 else item[:29] + "…"
            equip_curto = equip if len(equip) <= 24 else equip[:21] + "…"

            with st.container(border=True):
                c_sum, c_pop = st.columns([5, 2])
                with c_sum:
                    st.markdown(
                        f"**Compra #{cid}** · OS **{os_n}** &nbsp; "
                        f"**{badge_st}**"
                        + (
                            f" &nbsp; {badge_prioridade(prio)}"
                            if prio and prio != "—"
                            else ""
                        )
                        + f"<br/>"
                        f"<span style='opacity:.95;font-weight:600'>📦 {item}</span><br/>"
                        f"<span style='opacity:.9'>⚙️ {equip}</span> · "
                        f"<span style='opacity:.9'>👤 {sol}</span>"
                        + (
                            f" · <span style='opacity:.9'>R$ {valor:,.2f}</span>"
                            if valor
                            else ""
                        ),
                        unsafe_allow_html=True,
                    )
                with c_pop:
                    pop_label = f"#{cid} · {item_curto}"
                    with st.popover(pop_label, key=f"pop_cp_{cid}", width="stretch"):
                        st.markdown(f"### Compra #{cid}")
                        st.markdown(
                            f"**{badge_st}** · OS **{os_n}**"
                            + (
                                f" · {badge_prioridade(prio)}"
                                if prio and prio != "—"
                                else ""
                            ),
                            unsafe_allow_html=True,
                        )
                        st.markdown(f"**📦 Item:** {item}")
                        st.write(f"**⚙️ Equipamento:** {equip}")
                        st.write(f"**Solicitante:** {sol}")
                        if cp.get("prazo_recebimento"):
                            st.write(
                                f"**Prazo recebimento:** {cp.get('prazo_recebimento')}"
                            )
                        if cp.get("observacao"):
                            st.caption(f"Obs.: {cp.get('observacao')}")
                        if cp.get("link_compra"):
                            st.markdown(
                                f"🔗 [Abrir link de compra]({cp.get('link_compra')})"
                            )

                        # Histórico do item
                        try:
                            hist = historico_compras_item(
                                cp.get("item_nome") or "", cp.get("equipamento")
                            )
                            hist_outros = [h for h in hist if h.get("id") != cid]
                        except Exception:
                            hist_outros = []
                        if hist_outros:
                            with st.expander(
                                f"📜 Compras anteriores ({len(hist_outros)})"
                            ):
                                for h in hist_outros[:8]:
                                    st.caption(
                                        f"#{h.get('id')} · {h.get('data_solicitacao')} · "
                                        f"R$ {float(h.get('valor_item') or 0):,.2f} · "
                                        f"{h.get('status')}"
                                    )

                        if status == "Pendente":
                            st.divider()
                            st.markdown("#### Analisar / Aprovar")
                            aprov = st.radio(
                                "Aprovar compra?",
                                ["Sim", "Não"],
                                horizontal=True,
                                key=f"cp_aprov_{cid}",
                            )
                            link_n = st.text_input(
                                "Link da compra (opcional)",
                                value=cp.get("link_compra") or "",
                                key=f"cp_link_{cid}",
                            )
                            if aprov == "Sim":
                                dias_ch = st.number_input(
                                    "Dias para chegada",
                                    min_value=0,
                                    max_value=365,
                                    value=_safe_int(cp.get("dias_para_chegada"), 0)
                                    or 0,
                                    key=f"cp_dias_{cid}",
                                )
                                valor_in = st.number_input(
                                    "Valor do item (R$)",
                                    min_value=0.0,
                                    value=float(cp.get("valor_item") or 0),
                                    step=0.01,
                                    format="%.2f",
                                    key=f"cp_valor_{cid}",
                                )
                            else:
                                dias_ch = 0
                                valor_in = float(cp.get("valor_item") or 0)
                            obs_cp = st.text_area(
                                "Observação compras",
                                value=cp.get("observacao_compras") or "",
                                key=f"cp_obs_{cid}",
                                height=70,
                            )
                            comprador = st.text_input(
                                "Seu nome (comprador)",
                                key=f"cp_nome_{cid}",
                            )
                            if st.button(
                                "💾 Registrar decisão",
                                key=f"cp_save_{cid}",
                                type="primary",
                                width="stretch",
                            ):
                                cp["aprovado"] = aprov
                                cp["link_compra"] = link_n
                                cp["observacao_compras"] = obs_cp
                                cp["comprador"] = comprador
                                cp["data_aprovacao"] = datetime.now().strftime(
                                    "%Y-%m-%d %H:%M:%S"
                                )
                                if aprov == "Sim":
                                    cp["status"] = "Aprovada"
                                    cp["dias_para_chegada"] = _safe_int(dias_ch, 0)
                                    cp["valor_item"] = _safe_float(valor_in, 0.0)
                                    msg = (
                                        f"Compra APROVADA do item '{cp.get('item_nome')}'. "
                                        f"Valor R$ {float(valor_in):,.2f}. "
                                        f"Previsão de chegada: {int(dias_ch)} dia(s)."
                                    )
                                else:
                                    cp["status"] = "Rejeitada"
                                    cp["dias_para_chegada"] = None
                                    msg = (
                                        f"Compra REJEITADA do item '{cp.get('item_nome')}'. "
                                        f"{obs_cp or ''}"
                                    )
                                if salvar_compra(cp):
                                    if cp.get("chamado_id"):
                                        try:
                                            _notificar_chamado_compra(
                                                int(cp["chamado_id"]), msg
                                            )
                                        except Exception:
                                            pass
                                    agendar_efeito_concluido(
                                        msg, celebrar=(aprov == "Sim")
                                    )
                                    st.rerun()

                        elif status == "Aprovada":
                            st.success(
                                f"Aprovada · chegada em {cp.get('dias_para_chegada')} dia(s) · "
                                f"R$ {valor:,.2f}"
                            )
                            if cp.get("comprador"):
                                st.caption(f"Comprador: {cp.get('comprador')}")
                            if st.button(
                                "📦 Marcar como recebida",
                                key=f"cp_rec_{cid}",
                                type="primary",
                                width="stretch",
                            ):
                                cp["status"] = "Recebida"
                                cp["data_recebimento"] = datetime.now().strftime(
                                    "%Y-%m-%d %H:%M:%S"
                                )
                                if salvar_compra(cp):
                                    msg = (
                                        f"Item '{cp.get('item_nome')}' RECEBIDO. "
                                        f"Valor R$ {valor:,.2f}."
                                    )
                                    if cp.get("chamado_id"):
                                        try:
                                            _notificar_chamado_compra(
                                                int(cp["chamado_id"]), msg
                                            )
                                            cid_os = int(cp["chamado_id"])
                                            for c in st.session_state.chamados:
                                                if int(c.get("id") or 0) == cid_os and c.get(
                                                    "status"
                                                ) == "Aguardando Peça":
                                                    c["status"] = "Em Atendimento"
                                                    if not c.get("data_hora_inicio"):
                                                        c["data_hora_inicio"] = (
                                                            datetime.now().isoformat()
                                                        )
                                                    salvar_chamado(c)
                                                    break
                                        except Exception:
                                            pass
                                    agendar_efeito_concluido(
                                        msg + " OS retomada para atendimento.",
                                        celebrar=True,
                                    )
                                    st.rerun()

                        else:
                            st.caption(
                                f"Status: **{status}** · "
                                f"Comprador: {cp.get('comprador') or '—'} · "
                                f"Valor R$ {valor:,.2f}"
                            )
                            if cp.get("data_recebimento"):
                                st.caption(
                                    f"Recebido em: {cp.get('data_recebimento')}"
                                )


# ====================== ADMINISTRADOR ======================
elif perfil == "👨‍💼 Administrador":
    if not st.session_state.admin_logado:
        header(
            "Área do Administrador",
            "Autentique-se para acessar os painéis",
            icon="👨‍💼",
            nivel="secao",
        )
        with st.container(border=True):
            with st.form("login_admin"):
                usuario_input = st.text_input("Usuário:", placeholder="Leandro Coelho")
                senha_input = st.text_input("Senha:", type="password")
                if st.form_submit_button("Efetuar Login", type="primary", width="stretch"):
                    if verificar_login_admin(usuario_input, senha_input):
                        st.session_state.admin_logado = True
                        st.rerun()
                    else:
                        st.error("❌ Usuário ou senha incorretos.")
                        log_error(f"Tentativa de login admin falhou: {usuario_input}")
    else:
        header(
            "Painel do Administrador",
            "Indicadores, cadastros e importações",
            icon="👨‍💼",
            nivel="secao",
        )
        col_a, col_b, col_c = st.columns([5, 2, 1])
        col_a.success("🔓 Sessão administrativa ativa.")
        with col_b:
            if is_cloud():
                if st.button("☁️ Merge Local ↔ Cloud (sem apagar)", width="stretch", type="primary"):
                    with st.spinner("Sincronizando dados locais para o SQLite Cloud..."):
                        ok, msg = sync_local_to_cloud()
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)
            else:
                st.caption("Configure SQLITECLOUD_URL nos Secrets para sincronizar.")
        with col_c:
            if st.button("🚪 Sair", width="stretch"):
                st.session_state.admin_logado = False
                st.rerun()

        reload_data()
        df = pd.DataFrame(st.session_state.chamados) if st.session_state.chamados else pd.DataFrame()
        compras_all = carregar_compras()
        df_compras = pd.DataFrame(compras_all) if compras_all else pd.DataFrame()
        hist_all = carregar_historico_manutencao()
        df_custos = custo_e_horas_por_equipamento(
            historico=hist_all,
            chamados=st.session_state.chamados,
        )

        tab1, tab_edit, tab_sla, tab2, tab3, tab4, tab_comp, tab5, tab6, tab7, tab8, tab9 = st.tabs([
            "📊 Dashboard Geral",
            "✏️ Editar Chamados",
            "⏱️ SLA",
            "📈 Análise Gráfica",
            "📊 Análise de Tempo",
            "🛠️ Ocorrências por Equipamento",
            "🛒 Compras & Índices",
            "👥 Cadastro de Equipe",
            "🏭 Cadastro de Setores",
            "🔧 Cadastro de Equipamentos",
            "🖼️ Galeria de Fotos",
            "📥 Importar Planilha",
        ])

        with tab1:
            st.subheader("📊 Painel consolidado")
            # ---- KPIs Chamados ----
            if not df.empty:
                df = df.copy()
                df["data_hora_abertura"] = pd.to_datetime(
                    df["data_hora_abertura"], errors="coerce"
                )
                with st.container(border=True):
                    colf1, colf2, colf3, colf4 = st.columns(4)
                    with colf1:
                        filtro_setor = st.multiselect(
                            "Setor",
                            sorted(df["setor"].dropna().unique().tolist()),
                            key="f1",
                        )
                    with colf2:
                        filtro_prioridade = st.multiselect(
                            "Prioridade",
                            df["prioridade"].dropna().unique().tolist(),
                            key="f2",
                        )
                    with colf3:
                        filtro_status = st.multiselect(
                            "Status",
                            ["Aberto", "Em Atendimento", "Aguardando Peça", "Concluído"],
                            key="f3",
                        )
                    with colf4:
                        filtro_tecnico = st.multiselect(
                            "Técnico",
                            [x for x in df["executante"].dropna().unique().tolist() if x],
                            key="f4",
                        )
                df_filtrado = df.copy()
                if filtro_setor:
                    df_filtrado = df_filtrado[df_filtrado["setor"].isin(filtro_setor)]
                if filtro_prioridade:
                    df_filtrado = df_filtrado[
                        df_filtrado["prioridade"].isin(filtro_prioridade)
                    ]
                if filtro_status:
                    df_filtrado = df_filtrado[df_filtrado["status"].isin(filtro_status)]
                if filtro_tecnico:
                    df_filtrado = df_filtrado[
                        df_filtrado["executante"].isin(filtro_tecnico)
                    ]
            else:
                df_filtrado = df

            n_total = len(df_filtrado) if not df_filtrado.empty else 0
            n_ab = (
                len(df_filtrado[df_filtrado["status"] == "Aberto"])
                if n_total
                else 0
            )
            n_at = (
                len(df_filtrado[df_filtrado["status"] == "Em Atendimento"])
                if n_total
                else 0
            )
            n_ap = (
                len(df_filtrado[df_filtrado["status"] == "Aguardando Peça"])
                if n_total
                else 0
            )
            n_ok = (
                len(df_filtrado[df_filtrado["status"] == "Concluído"])
                if n_total
                else 0
            )
            taxa_conc = (n_ok / n_total * 100) if n_total else 0

            st.markdown("##### Chamados")
            k1, k2, k3, k4, k5, k6 = st.columns(6)
            k1.metric("Total", n_total)
            k2.metric("Abertos", n_ab)
            k3.metric("Em atendimento", n_at)
            k4.metric("Aguard. peça", n_ap)
            k5.metric("Concluídos", n_ok)
            k6.metric("Taxa conclusão", f"{taxa_conc:.0f}%")

            # ---- KPIs Compras ----
            n_cp = len(df_compras)
            n_pend = (
                len(df_compras[df_compras["status"] == "Pendente"]) if n_cp else 0
            )
            n_apr = (
                len(df_compras[df_compras["status"] == "Aprovada"]) if n_cp else 0
            )
            n_rec = (
                len(df_compras[df_compras["status"] == "Recebida"]) if n_cp else 0
            )
            n_rej = (
                len(df_compras[df_compras["status"] == "Rejeitada"]) if n_cp else 0
            )
            valor_total = (
                float(df_compras["valor_item"].fillna(0).sum()) if n_cp else 0.0
            )
            lead = (
                float(
                    df_compras.loc[
                        df_compras["status"].isin(["Aprovada", "Recebida"]),
                        "dias_para_chegada",
                    ]
                    .dropna()
                    .mean()
                )
                if n_cp and "dias_para_chegada" in df_compras.columns
                else 0.0
            )

            st.markdown("##### Compras de peças")
            c1, c2, c3, c4, c5, c6 = st.columns(6)
            c1.metric("Solicitações", n_cp)
            c2.metric("Pendentes", n_pend)
            c3.metric("Aprovadas", n_apr)
            c4.metric("Recebidas", n_rec)
            c5.metric("Rejeitadas", n_rej)
            c6.metric("Valor total", f"R$ {valor_total:,.2f}")

            m1, m2, m3 = st.columns(3)
            m1.metric("Lead time médio (dias)", f"{lead:.1f}" if lead else "—")
            m2.metric(
                "Custo peças (histórico manut.)",
                f"R$ {df_custos['Custo Peças (R$)'].sum():,.2f}"
                if not df_custos.empty
                else "R$ 0,00",
            )
            m3.metric(
                "Horas-homem total",
                f"{df_custos['Horas-Homem'].sum():.1f} h"
                if not df_custos.empty
                else "0 h",
            )

            # ---- Listagem aprimorada ----
            st.markdown("##### Listagem de chamados")
            if not df_filtrado.empty:
                cols_show = [
                    c
                    for c in [
                        "id",
                        "status",
                        "prioridade",
                        "setor",
                        "equipamento",
                        "solicitante",
                        "executante",
                        "data_hora_abertura",
                        "data_hora_inicio",
                        "data_hora_conclusao",
                        "peca_solicitada",
                        "descricao",
                        "solucao_descricao",
                        "comentario_conclusao",
                    ]
                    if c in df_filtrado.columns
                ]
                df_view = df_filtrado[cols_show].copy()
                for col in [
                    "data_hora_abertura",
                    "data_hora_inicio",
                    "data_hora_conclusao",
                ]:
                    if col in df_view.columns:
                        df_view[col] = pd.to_datetime(
                            df_view[col], errors="coerce"
                        ).dt.strftime("%d/%m/%Y %H:%M")
                df_view = df_view.sort_values("id", ascending=False)
                st.dataframe(
                    df_view,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "id": st.column_config.NumberColumn("OS", width="small"),
                        "status": st.column_config.TextColumn("Status", width="medium"),
                        "prioridade": st.column_config.TextColumn("Prioridade", width="small"),
                        "descricao": st.column_config.TextColumn("Descrição", width="large"),
                    },
                )
                csv = df_view.to_csv(index=False).encode("utf-8-sig")
                st.download_button(
                    "⬇️ Exportar chamados (CSV)",
                    data=csv,
                    file_name=f"chamados_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    key="dl_chamados_dash",
                )
            else:
                st.info("Nenhum chamado registrado / filtrado.")

        with tab_edit:
            st.subheader("✏️ Editar chamado por número da OS")
            st.caption(
                "Digite o número da OS e altere qualquer campo. "
                "Também é possível corrigir nomes de técnicos em massa."
            )
            reload_data()
            lista_ch = list(st.session_state.chamados or [])
            by_id = {}
            for c in lista_ch:
                try:
                    by_id[int(c.get("id"))] = c
                except (TypeError, ValueError):
                    continue
            ids_disp = sorted(by_id.keys(), reverse=True)

            if not ids_disp:
                st.info("Nenhum chamado registrado.")
            else:
                # ---- Seleção pela OS ----
                with st.container(border=True):
                    c_os1, c_os2, c_os3 = st.columns([2, 2, 2])
                    with c_os1:
                        os_num = st.number_input(
                            "Nº da OS *",
                            min_value=int(min(ids_disp)),
                            max_value=int(max(ids_disp)) + 1000,
                            value=int(ids_disp[0]),
                            step=1,
                            key="edit_os_num",
                        )
                    with c_os2:
                        os_sel = st.selectbox(
                            "Ou escolha na lista",
                            options=ids_disp,
                            format_func=lambda i: (
                                f"OS {i} · {by_id[i].get('status') or '—'} · "
                                f"{by_id[i].get('executante') or 'sem técnico'}"
                            ),
                            key="edit_os_sel",
                        )
                    with c_os3:
                        usar = st.radio(
                            "Usar",
                            ["Número digitado", "Lista"],
                            horizontal=True,
                            key="edit_os_modo",
                        )

                    cid_sel = int(os_num) if usar == "Número digitado" else int(os_sel)
                    cham = by_id.get(cid_sel)
                    if cham is None:
                        st.error(
                            f"OS {cid_sel} não encontrada. "
                            f"IDs existentes: {min(ids_disp)} … {max(ids_disp)}"
                        )
                    else:
                        st.success(
                            f"Editando **OS {cid_sel}** · "
                            f"{cham.get('status') or '—'} · "
                            f"{cham.get('setor') or '—'} · "
                            f"{cham.get('solicitante') or '—'}"
                        )

                        nomes_equipe = []
                        try:
                            if not st.session_state.equipe.empty:
                                nomes_equipe = [
                                    str(r["nome"]).strip()
                                    for _, r in st.session_state.equipe.iterrows()
                                    if str(r.get("nome") or "").strip()
                                ]
                        except Exception:
                            pass

                        with st.form(f"form_edit_os_{cid_sel}"):
                            st.markdown("#### Dados gerais")
                            g1, g2, g3 = st.columns(3)
                            with g1:
                                novo_sol = st.text_input(
                                    "Solicitante",
                                    value=str(cham.get("solicitante") or ""),
                                )
                                setores_opts = list(st.session_state.setores or [])
                                setor_atual = str(cham.get("setor") or "")
                                if setor_atual and setor_atual not in setores_opts:
                                    setores_opts = [setor_atual] + setores_opts
                                idx_setor = (
                                    setores_opts.index(setor_atual)
                                    if setor_atual in setores_opts
                                    else 0
                                )
                                novo_setor = st.selectbox(
                                    "Setor",
                                    options=setores_opts or [""],
                                    index=idx_setor if setores_opts else 0,
                                )
                                novo_equip = st.text_input(
                                    "Equipamento",
                                    value=str(cham.get("equipamento") or ""),
                                )
                            with g2:
                                status_opts = [
                                    "Aberto",
                                    "Em Atendimento",
                                    "Aguardando Peça",
                                    "Concluído",
                                ]
                                st_atual = str(cham.get("status") or "Aberto")
                                if st_atual not in status_opts:
                                    status_opts = [st_atual] + status_opts
                                novo_status = st.selectbox(
                                    "Status",
                                    options=status_opts,
                                    index=status_opts.index(st_atual),
                                )
                                prio_opts = ["Crítica", "Alta", "Média", "Baixa"]
                                pr_atual = str(cham.get("prioridade") or "Média")
                                if pr_atual not in prio_opts:
                                    prio_opts = [pr_atual] + prio_opts
                                novo_prio = st.selectbox(
                                    "Prioridade",
                                    options=prio_opts,
                                    index=prio_opts.index(pr_atual),
                                )
                                exec_atual = str(cham.get("executante") or "")
                                op_exec = [""] + sorted(
                                    set(
                                        nomes_equipe
                                        + ([exec_atual] if exec_atual else [])
                                    )
                                )
                                idx_exec = (
                                    op_exec.index(exec_atual)
                                    if exec_atual in op_exec
                                    else 0
                                )
                                novo_exec_sel = st.selectbox(
                                    "Executante (equipe)",
                                    options=op_exec,
                                    index=idx_exec,
                                )
                                novo_exec_txt = st.text_input(
                                    "Ou digite o executante",
                                    value=exec_atual,
                                )
                            with g3:
                                nova_abertura = st.text_input(
                                    "Data/hora abertura",
                                    value=str(cham.get("data_hora_abertura") or ""),
                                    help="Formato: YYYY-MM-DD HH:MM:SS",
                                )
                                novo_inicio = st.text_input(
                                    "Data/hora início",
                                    value=str(cham.get("data_hora_inicio") or ""),
                                )
                                nova_conclusao = st.text_input(
                                    "Data/hora conclusão",
                                    value=str(cham.get("data_hora_conclusao") or ""),
                                )

                            st.markdown("#### Descrição e solução")
                            nova_desc = st.text_area(
                                "Descrição do problema",
                                value=str(cham.get("descricao") or ""),
                                height=100,
                            )
                            nova_solucao = st.text_area(
                                "Solução / serviços realizados",
                                value=str(cham.get("solucao_descricao") or ""),
                                height=100,
                            )
                            novo_comentario = st.text_area(
                                "Comentário / observações de conclusão",
                                value=str(cham.get("comentario_conclusao") or ""),
                                height=80,
                            )

                            st.markdown("#### Peça / compras vinculadas")
                            p1, p2 = st.columns(2)
                            with p1:
                                nova_peca = st.text_input(
                                    "Peça solicitada",
                                    value=str(cham.get("peca_solicitada") or ""),
                                )
                                nova_data_peca = st.text_input(
                                    "Data solicitação peça",
                                    value=str(cham.get("data_solicitacao_peca") or ""),
                                )
                            with p2:
                                nova_peca_obs = st.text_area(
                                    "Observação da peça",
                                    value=str(cham.get("peca_observacao") or ""),
                                    height=80,
                                )

                            st.markdown("#### Fotos (caminhos)")
                            f1, f2 = st.columns(2)
                            with f1:
                                nova_foto = st.text_input(
                                    "Foto abertura (path)",
                                    value=str(cham.get("foto_path") or ""),
                                )
                            with f2:
                                nova_foto_sol = st.text_input(
                                    "Foto solução (path)",
                                    value=str(cham.get("foto_solucao_path") or ""),
                                )

                            if st.form_submit_button(
                                "💾 Salvar todas as alterações da OS",
                                type="primary",
                                width="stretch",
                            ):
                                exec_final = (
                                    novo_exec_txt or novo_exec_sel or ""
                                ).strip()
                                cham["solicitante"] = (novo_sol or "").strip()
                                cham["setor"] = novo_setor
                                cham["equipamento"] = (novo_equip or "").strip()
                                cham["status"] = novo_status
                                cham["prioridade"] = novo_prio
                                cham["executante"] = exec_final
                                cham["descricao"] = (nova_desc or "").strip()
                                cham["solucao_descricao"] = (nova_solucao or "").strip()
                                cham["comentario_conclusao"] = (
                                    novo_comentario or ""
                                ).strip()
                                cham["peca_solicitada"] = (nova_peca or "").strip()
                                cham["peca_observacao"] = (nova_peca_obs or "").strip()
                                # Datas: string vazia vira None
                                def _dt(v):
                                    s = (v or "").strip()
                                    return s if s else None

                                cham["data_hora_abertura"] = _dt(nova_abertura)
                                cham["data_hora_inicio"] = _dt(novo_inicio)
                                cham["data_hora_conclusao"] = _dt(nova_conclusao)
                                cham["data_solicitacao_peca"] = _dt(nova_data_peca)
                                fp = (nova_foto or "").strip()
                                cham["foto_path"] = fp if fp else None
                                fs = (nova_foto_sol or "").strip()
                                cham["foto_solucao_path"] = fs if fs else None

                                if salvar_chamado(cham):
                                    for i, c in enumerate(st.session_state.chamados):
                                        try:
                                            if int(c.get("id")) == cid_sel:
                                                st.session_state.chamados[i] = dict(cham)
                                                break
                                        except (TypeError, ValueError):
                                            pass
                                    agendar_efeito_concluido(
                                        f"✅ OS {cid_sel} salva com sucesso!",
                                        celebrar=True,
                                    )
                                    st.rerun()
                                else:
                                    st.error("Falha ao salvar. Verifique o log.")

                # ---- Correção em massa de executante ----
                with st.expander("🔄 Corrigir nome do técnico em massa", expanded=False):
                    nomes_atuais = sorted(
                        {
                            str(c.get("executante") or "").strip()
                            for c in lista_ch
                            if str(c.get("executante") or "").strip()
                        }
                    )
                    nomes_equipe_b = []
                    try:
                        if not st.session_state.equipe.empty:
                            nomes_equipe_b = [
                                str(r["nome"]).strip()
                                for _, r in st.session_state.equipe.iterrows()
                                if str(r.get("nome") or "").strip()
                            ]
                    except Exception:
                        pass
                    opcoes_destino = sorted(set(nomes_equipe_b + nomes_atuais))
                    col_m1, col_m2, col_m3 = st.columns([2, 2, 1])
                    with col_m1:
                        de_nome = st.multiselect(
                            "Nomes errados / variantes",
                            options=nomes_atuais,
                            key="bulk_exec_de",
                        )
                    with col_m2:
                        para_nome = st.selectbox(
                            "Nome correto (lista)",
                            options=[""] + opcoes_destino,
                            key="bulk_exec_para",
                        )
                        para_livre = st.text_input(
                            "Ou digite o nome correto",
                            key="bulk_exec_para_txt",
                            placeholder="Ailton Silva",
                        )
                    with col_m3:
                        st.write("")
                        st.write("")
                        if st.button(
                            "✅ Aplicar",
                            key="bulk_exec_ok",
                            type="primary",
                            width="stretch",
                        ):
                            destino = (para_livre or para_nome or "").strip()
                            if not de_nome or not destino:
                                st.error("Selecione as variantes e o nome correto.")
                            else:
                                n_ok = 0
                                de_set = {x.strip().lower() for x in de_nome}
                                for c in lista_ch:
                                    atual = str(c.get("executante") or "").strip()
                                    if atual.lower() in de_set and atual != destino:
                                        c["executante"] = destino
                                        if salvar_chamado(c):
                                            n_ok += 1
                                reload_data()
                                agendar_efeito_concluido(
                                    f"✅ {n_ok} chamado(s) → '{destino}'",
                                    celebrar=True,
                                )
                                st.rerun()


        with tab_sla:
            st.subheader("⏱️ Metas de SLA da equipe")
            st.caption(
                "Tempo-alvo a partir da **abertura** do chamado (relógio corrido). "
                "Usado na ordenação da fila e no prazo exibido nos cards."
            )
            sla_atual = get_sla_tempo()
            with st.form("form_sla_admin"):
                st.markdown("##### Minutos por prioridade")
                c1, c2 = st.columns(2)
                novos = {}
                with c1:
                    novos["Crítica"] = st.number_input(
                        "Crítica (min)",
                        min_value=1,
                        max_value=10080,
                        value=int(sla_atual.get("Crítica", 20)),
                        step=5,
                        key="sla_critica",
                    )
                    novos["Alta"] = st.number_input(
                        "Alta (min)",
                        min_value=1,
                        max_value=10080,
                        value=int(sla_atual.get("Alta", 60)),
                        step=5,
                        key="sla_alta",
                    )
                with c2:
                    novos["Média"] = st.number_input(
                        "Média (min)",
                        min_value=1,
                        max_value=10080,
                        value=int(sla_atual.get("Média", 240)),
                        step=15,
                        key="sla_media",
                    )
                    novos["Baixa"] = st.number_input(
                        "Baixa (min)",
                        min_value=1,
                        max_value=10080,
                        value=int(sla_atual.get("Baixa", 1440)),
                        step=30,
                        key="sla_baixa",
                    )
                st.markdown("**Pré-visualização**")
                for p, m in novos.items():
                    st.write(f"· **{p}**: {formatar_duracao_minutos(m)} (meta)")
                if st.form_submit_button("💾 Salvar SLA", type="primary", width="stretch"):
                    if salvar_sla(novos):
                        st.session_state.sla_tempo = dict(novos)
                        agendar_efeito_concluido("✅ SLA atualizado!", celebrar=True)
                        st.rerun()

            st.divider()
            st.markdown("##### Como o prazo é calculado")
            st.info(
                "prazo = data/hora de **abertura** + meta da **prioridade**.\n\n"
                "Se o tempo restante for positivo → ainda no prazo.\n"
                "Se for negativo → além do prazo (mostra quanto passou).\n\n"
                "Os indicadores de demora do usuário (fila/atendimento/peça) "
                "continuam em **horário útil 07h–19h**, separados deste SLA."
            )


        with tab2:
            if not df.empty:
                col1, col2 = st.columns(2)
                with col1:
                    fig = px.pie(
                        df,
                        names="prioridade",
                        color="prioridade",
                        title="Distribuição por Prioridade",
                        hole=0.4,
                        color_discrete_map=CORES_PRIORIDADE,
                    )
                    st.plotly_chart(fig, width="stretch")
                    if "status" in df.columns:
                        fig_s = px.pie(
                            df,
                            names="status",
                            color="status",
                            title="Distribuição por Status",
                            hole=0.4,
                            color_discrete_map=CORES_STATUS,
                        )
                        st.plotly_chart(fig_s, width="stretch")
                with col2:
                    setor_df = df["setor"].value_counts().reset_index()
                    setor_df.columns = ["setor", "count"]
                    fig = px.bar(
                        setor_df,
                        x="setor",
                        y="count",
                        title="Chamados por Setor",
                        color_discrete_sequence=["#ef4444"],
                    )
                    st.plotly_chart(fig, width="stretch")
                    if "executante" in df.columns:
                        tec_df = (
                            df[df["executante"].fillna("").astype(str).str.len() > 0][
                                "executante"
                            ]
                            .value_counts()
                            .reset_index()
                        )
                        tec_df.columns = ["tecnico", "count"]
                        if not tec_df.empty:
                            fig_t = px.bar(
                                tec_df,
                                x="tecnico",
                                y="count",
                                title="Chamados por Técnico",
                                color_discrete_sequence=["#f59e0b"],
                            )
                            st.plotly_chart(fig_t, width="stretch")
                # Evolução temporal
                df_t = df.copy()
                df_t["data_hora_abertura"] = pd.to_datetime(
                    df_t["data_hora_abertura"], errors="coerce"
                )
                df_t = df_t.dropna(subset=["data_hora_abertura"])
                if not df_t.empty:
                    df_t["dia"] = df_t["data_hora_abertura"].dt.date
                    evol = df_t.groupby("dia").size().reset_index(name="chamados")
                    fig_e = px.line(
                        evol,
                        x="dia",
                        y="chamados",
                        markers=True,
                        title="Aberturas por dia",
                    )
                    st.plotly_chart(fig_e, width="stretch")
            else:
                st.info("Sem dados para gráficos.")

            if not df_compras.empty and "status" in df_compras.columns:
                st.markdown("##### Compras")
                g1, g2 = st.columns(2)
                with g1:
                    st.plotly_chart(
                        px.pie(
                            df_compras,
                            names="status",
                            title="Compras por status",
                            hole=0.4,
                        ),
                        width="stretch",
                    )
                with g2:
                    if "valor_item" in df_compras.columns:
                        top_itens = (
                            df_compras.groupby("item_nome")["valor_item"]
                            .sum()
                            .reset_index()
                            .sort_values("valor_item", ascending=False)
                            .head(10)
                        )
                        st.plotly_chart(
                            px.bar(
                                top_itens,
                                x="item_nome",
                                y="valor_item",
                                title="Top itens por valor (R$)",
                                color_discrete_sequence=["#ef4444"],
                            ),
                            width="stretch",
                        )

        with tab3:
            st.subheader("📊 Análise de Tempo de Execução")
            st.caption(
                f"Tempos em expediente {HORA_INICIO_EXPEDIENTE:02d}:00–{HORA_FIM_EXPEDIENTE:02d}:00 · "
                "formato: min / h + min / d + h + min"
            )
            df_analise = (
                df[df["status"] == "Concluído"].copy() if not df.empty else pd.DataFrame()
            )
            if not df_analise.empty:
                tempos = []
                for _, row in df_analise.iterrows():
                    m = minutos_uteis_entre(
                        row.get("data_hora_inicio") or row.get("data_hora_abertura"),
                        row.get("data_hora_conclusao"),
                    )
                    tempos.append(m)
                df_analise["tempo_minutos"] = tempos
                df_analise = df_analise.dropna(subset=["tempo_minutos"])
                if df_analise.empty:
                    st.info("Sem datas válidas para calcular tempos.")
                else:
                    tempo_tecnico = (
                        df_analise.groupby("executante")["tempo_minutos"]
                        .mean()
                        .reset_index()
                    )
                    tempo_tecnico.columns = ["Técnico", "tempo_min"]
                    tempo_tecnico["rótulo"] = tempo_tecnico["tempo_min"].apply(
                        formatar_duracao_minutos
                    )
                    # eixo em horas se média alta
                    media_t = float(tempo_tecnico["tempo_min"].mean())
                    if media_t >= 60:
                        tempo_tecnico["eixo"] = (tempo_tecnico["tempo_min"] / 60).round(2)
                        ylab = "Horas úteis"
                    else:
                        tempo_tecnico["eixo"] = tempo_tecnico["tempo_min"].round(0)
                        ylab = "Minutos úteis"
                    fig_t = px.bar(
                        tempo_tecnico,
                        x="Técnico",
                        y="eixo",
                        text="rótulo",
                        title="Tempo médio por técnico",
                        color_discrete_sequence=["#2563EB"],
                    )
                    fig_t.update_traces(textposition="outside")
                    fig_t.update_layout(yaxis_title=ylab)
                    st.plotly_chart(fig_t, width="stretch")

                    tempo_prio = (
                        df_analise.groupby("prioridade")["tempo_minutos"]
                        .mean()
                        .reset_index()
                    )
                    tempo_prio["rótulo"] = tempo_prio["tempo_minutos"].apply(
                        formatar_duracao_minutos
                    )
                    media_p = float(tempo_prio["tempo_minutos"].mean())
                    if media_p >= 60:
                        tempo_prio["eixo"] = (tempo_prio["tempo_minutos"] / 60).round(2)
                        ylab2 = "Horas úteis"
                    else:
                        tempo_prio["eixo"] = tempo_prio["tempo_minutos"].round(0)
                        ylab2 = "Minutos úteis"
                    fig_p = px.bar(
                        tempo_prio,
                        x="prioridade",
                        y="eixo",
                        text="rótulo",
                        color="prioridade",
                        title="Tempo médio por prioridade",
                        color_discrete_map=CORES_PRIORIDADE,
                        category_orders={
                            "prioridade": ["Crítica", "Alta", "Média", "Baixa"]
                        },
                    )
                    fig_p.update_traces(textposition="outside")
                    fig_p.update_layout(yaxis_title=ylab2, showlegend=False)
                    st.plotly_chart(fig_p, width="stretch")

                    # Tabela legível
                    resumo = df_analise.copy()
                    resumo["duração"] = resumo["tempo_minutos"].apply(
                        formatar_duracao_minutos
                    )
                    cols_r = [
                        c
                        for c in ["id", "executante", "prioridade", "equipamento", "duração"]
                        if c in resumo.columns
                    ]
                    st.dataframe(
                        resumo[cols_r].sort_values("id", ascending=False)
                        if "id" in resumo.columns
                        else resumo[cols_r],
                        width="stretch",
                        hide_index=True,
                    )
            else:
                st.info("Ainda não há chamados concluídos para análise.")

        with tab4:
            st.subheader("🛠️ Ocorrências e Custos por Equipamento")
            hist_all = carregar_historico_manutencao()
            df_custos = custo_e_horas_por_equipamento(
                historico=hist_all,
                chamados=st.session_state.chamados,
            )

            if not df.empty:
                df_equip = df.groupby("equipamento").size().reset_index(name="Chamados")
                st.markdown("**Chamados por equipamento**")
                st.dataframe(
                    df_equip.sort_values("Chamados", ascending=False),
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info("Sem chamados registrados.")

            st.markdown("**Custo de manutenção e horas-homem**")
            if not df_custos.empty:
                c1, c2, c3 = st.columns(3)
                c1.metric("Custo total peças", f"R$ {df_custos['Custo Peças (R$)'].sum():,.2f}")
                c2.metric("Horas-homem total", f"{df_custos['Horas-Homem'].sum():,.1f} h")
                c3.metric("Equipamentos com histórico", len(df_custos))
                st.dataframe(df_custos, width="stretch", hide_index=True)
                fig = px.bar(
                    df_custos.head(15),
                    x="Equipamento",
                    y="Custo Peças (R$)",
                    color="Horas-Homem",
                    title="Top equipamentos por custo de peças",
                    color_continuous_scale="Reds",
                )
                st.plotly_chart(fig, width="stretch")
            else:
                st.info(
                    "Ainda não há histórico de manutenções com custo/horas. "
                    "Registre preventivas nos alertas ou adicione no cadastro do equipamento."
                )

        with tab_comp:
            st.subheader("🛒 Compras — índices e histórico")
            if df_compras.empty:
                st.info("Nenhuma solicitação de compra registrada ainda.")
            else:
                df_c = df_compras.copy()
                if "valor_item" not in df_c.columns:
                    df_c["valor_item"] = 0.0
                df_c["valor_item"] = pd.to_numeric(df_c["valor_item"], errors="coerce").fillna(0)
                if "status" not in df_c.columns:
                    df_c["status"] = "Pendente"
                df_c["status"] = df_c["status"].fillna("Pendente").astype(str)
                if "item_nome" not in df_c.columns:
                    df_c["item_nome"] = "—"
                df_c["item_nome"] = df_c["item_nome"].fillna("—").astype(str)
                if "equipamento" not in df_c.columns:
                    df_c["equipamento"] = "—"
                df_c["equipamento"] = df_c["equipamento"].fillna("—").astype(str)

                # ---- KPIs principais ----
                total_c = len(df_c)
                n_pend = int((df_c["status"] == "Pendente").sum())
                n_apr = int(df_c["status"].isin(["Aprovada", "Recebida"]).sum())
                n_rej = int((df_c["status"] == "Rejeitada").sum())
                n_rec = int((df_c["status"] == "Recebida").sum())
                # % aprovação sobre decisões (aprovadas+rejeitadas), não inclui pendentes
                n_decididos = n_apr + n_rej
                taxa_apr = (n_apr / n_decididos * 100) if n_decididos else 0.0
                taxa_rej = (n_rej / n_decididos * 100) if n_decididos else 0.0
                taxa_apr_total = (n_apr / total_c * 100) if total_c else 0.0
                valor_sum = float(df_c["valor_item"].sum())
                valor_aprov = float(
                    df_c.loc[df_c["status"].isin(["Aprovada", "Recebida"]), "valor_item"].sum()
                )
                valor_medio_apr = (
                    float(
                        df_c.loc[
                            df_c["status"].isin(["Aprovada", "Recebida"])
                            & (df_c["valor_item"] > 0),
                            "valor_item",
                        ].mean()
                    )
                    if n_apr
                    else 0.0
                )
                lead_medio = 0.0
                if "dias_para_chegada" in df_c.columns:
                    lead_s = pd.to_numeric(
                        df_c.loc[
                            df_c["status"].isin(["Aprovada", "Recebida"]),
                            "dias_para_chegada",
                        ],
                        errors="coerce",
                    ).dropna()
                    if len(lead_s):
                        lead_medio = float(lead_s.mean())

                st.markdown("##### 📊 Indicadores gerais")
                k1, k2, k3, k4, k5, k6 = st.columns(6)
                k1.metric("Solicitações", total_c)
                k2.metric(
                    "% Aprovação",
                    f"{taxa_apr:.0f}%",
                    help="Sobre decisões (aprovadas + rejeitadas). Pendentes fora.",
                )
                k3.metric("% Rejeição", f"{taxa_rej:.0f}%")
                k4.metric("Pendentes", n_pend)
                k5.metric("Valor aprovado", f"R$ {valor_aprov:,.2f}")
                k6.metric(
                    "Custo médio (aprov.)",
                    f"R$ {valor_medio_apr:,.2f}" if valor_medio_apr else "—",
                )

                m1, m2, m3 = st.columns(3)
                m1.metric("Recebidas", n_rec)
                m2.metric("Lead time médio", formatar_duracao_horas(lead_medio * 24) if lead_medio else "—")
                m3.metric(
                    "Aprov. s/ total",
                    f"{taxa_apr_total:.0f}%",
                    help="Aprovadas+Recebidas ÷ todas as solicitações",
                )

                # Gráfico status
                g1, g2 = st.columns(2)
                with g1:
                    st_counts = (
                        df_c["status"]
                        .value_counts()
                        .rename_axis("status")
                        .reset_index(name="qtd")
                    )
                    fig_st = px.pie(
                        st_counts,
                        names="status",
                        values="qtd",
                        title="Distribuição por status",
                        hole=0.4,
                        color="status",
                        color_discrete_map={
                            "Pendente": "#eab308",
                            "Aprovada": "#22c55e",
                            "Recebida": "#3b82f6",
                            "Rejeitada": "#ef4444",
                        },
                    )
                    st.plotly_chart(fig_st, width="stretch")
                with g2:
                    if valor_aprov > 0 or valor_sum > 0:
                        por_st = (
                            df_c.groupby("status", as_index=False)["valor_item"]
                            .sum()
                            .sort_values("valor_item", ascending=False)
                        )
                        fig_v = px.bar(
                            por_st,
                            x="status",
                            y="valor_item",
                            title="Valor (R$) por status",
                            color="status",
                            color_discrete_map={
                                "Pendente": "#eab308",
                                "Aprovada": "#22c55e",
                                "Recebida": "#3b82f6",
                                "Rejeitada": "#ef4444",
                            },
                        )
                        st.plotly_chart(fig_v, width="stretch")

                # ---- Custo médio por item e por equipamento ----
                st.markdown("##### 💰 Custo médio por item e equipamento")
                df_val = df_c[df_c["valor_item"] > 0].copy()
                if df_val.empty:
                    st.caption(
                        "Ainda não há valores preenchidos nas compras aprovadas/recebidas."
                    )
                else:
                    c_i, c_e = st.columns(2)
                    with c_i:
                        custo_item = (
                            df_val.groupby("item_nome", as_index=False)
                            .agg(
                                qtd=("id", "count"),
                                valor_total=("valor_item", "sum"),
                                custo_medio=("valor_item", "mean"),
                                custo_min=("valor_item", "min"),
                                custo_max=("valor_item", "max"),
                            )
                            .sort_values("valor_total", ascending=False)
                        )
                        custo_item["custo_medio"] = custo_item["custo_medio"].round(2)
                        custo_item["valor_total"] = custo_item["valor_total"].round(2)
                        st.markdown("**Por item**")
                        st.dataframe(
                            custo_item.rename(
                                columns={
                                    "item_nome": "Item",
                                    "qtd": "Qtd",
                                    "valor_total": "Total R$",
                                    "custo_medio": "Médio R$",
                                    "custo_min": "Mín R$",
                                    "custo_max": "Máx R$",
                                }
                            ),
                            width="stretch",
                            hide_index=True,
                        )
                    with c_e:
                        custo_eq = (
                            df_val.groupby("equipamento", as_index=False)
                            .agg(
                                qtd=("id", "count"),
                                valor_total=("valor_item", "sum"),
                                custo_medio=("valor_item", "mean"),
                            )
                            .sort_values("valor_total", ascending=False)
                        )
                        custo_eq["custo_medio"] = custo_eq["custo_medio"].round(2)
                        custo_eq["valor_total"] = custo_eq["valor_total"].round(2)
                        st.markdown("**Por equipamento**")
                        st.dataframe(
                            custo_eq.rename(
                                columns={
                                    "equipamento": "Equipamento",
                                    "qtd": "Qtd",
                                    "valor_total": "Total R$",
                                    "custo_medio": "Médio R$",
                                }
                            ),
                            width="stretch",
                            hide_index=True,
                        )

                    # Cruzamento item × equipamento
                    st.markdown("**Custo médio do item por equipamento**")
                    cruz = (
                        df_val.groupby(["item_nome", "equipamento"], as_index=False)
                        .agg(
                            qtd=("id", "count"),
                            custo_medio=("valor_item", "mean"),
                            valor_total=("valor_item", "sum"),
                        )
                        .sort_values("valor_total", ascending=False)
                    )
                    cruz["custo_medio"] = cruz["custo_medio"].round(2)
                    cruz["valor_total"] = cruz["valor_total"].round(2)
                    st.dataframe(
                        cruz.rename(
                            columns={
                                "item_nome": "Item",
                                "equipamento": "Equipamento",
                                "qtd": "Qtd",
                                "custo_medio": "Médio R$",
                                "valor_total": "Total R$",
                            }
                        ),
                        width="stretch",
                        hide_index=True,
                    )

                    fig_cruz = px.bar(
                        cruz.head(15),
                        x="item_nome",
                        y="custo_medio",
                        color="equipamento",
                        title="Top 15 — custo médio item × equipamento",
                        barmode="group",
                    )
                    st.plotly_chart(fig_cruz, width="stretch")

                # ---- Histórico de item comprado ----
                st.markdown("##### 📜 Histórico de item comprado")
                itens_opts = sorted(
                    {
                        str(x).strip()
                        for x in df_c["item_nome"].tolist()
                        if str(x).strip() and str(x).strip() != "—"
                    }
                )
                if not itens_opts:
                    st.caption("Sem itens para filtrar.")
                else:
                    item_sel = st.selectbox(
                        "Selecione o item",
                        options=itens_opts,
                        key="hist_item_compras_admin",
                    )
                    eq_opts = ["(todos)"] + sorted(
                        {
                            str(x).strip()
                            for x in df_c.loc[
                                df_c["item_nome"] == item_sel, "equipamento"
                            ].tolist()
                            if str(x).strip()
                        }
                    )
                    eq_sel = st.selectbox(
                        "Equipamento (opcional)",
                        options=eq_opts,
                        key="hist_eq_compras_admin",
                    )
                    mask = df_c["item_nome"] == item_sel
                    if eq_sel != "(todos)":
                        mask = mask & (df_c["equipamento"] == eq_sel)
                    hist_df = df_c.loc[mask].copy()
                    if hist_df.empty:
                        st.warning("Nenhum registro para este filtro.")
                    else:
                        # resumo do item
                        h_apr = hist_df[hist_df["status"].isin(["Aprovada", "Recebida"])]
                        h_rej = hist_df[hist_df["status"] == "Rejeitada"]
                        h_dec = len(h_apr) + len(h_rej)
                        pct_item = (len(h_apr) / h_dec * 100) if h_dec else 0.0
                        r1, r2, r3, r4 = st.columns(4)
                        r1.metric("Compras deste item", len(hist_df))
                        r2.metric("% aprovação", f"{pct_item:.0f}%")
                        r3.metric(
                            "Custo médio",
                            f"R$ {float(h_apr['valor_item'].mean()):,.2f}"
                            if len(h_apr) and float(h_apr["valor_item"].sum()) > 0
                            else "—",
                        )
                        r4.metric(
                            "Total gasto",
                            f"R$ {float(h_apr['valor_item'].sum()):,.2f}",
                        )

                        cols_h = [
                            c
                            for c in [
                                "id",
                                "status",
                                "equipamento",
                                "chamado_id",
                                "solicitante",
                                "comprador",
                                "valor_item",
                                "dias_para_chegada",
                                "data_solicitacao",
                                "data_aprovacao",
                                "data_recebimento",
                                "link_compra",
                                "observacao",
                                "observacao_compras",
                            ]
                            if c in hist_df.columns
                        ]
                        hist_show = hist_df[cols_h].sort_values(
                            by="id", ascending=False
                        ) if "id" in hist_df.columns else hist_df[cols_h]
                        st.dataframe(
                            hist_show,
                            width="stretch",
                            hide_index=True,
                            column_config={
                                "valor_item": st.column_config.NumberColumn(
                                    "Valor R$", format="R$ %.2f"
                                ),
                                "link_compra": st.column_config.LinkColumn("Link"),
                                "chamado_id": st.column_config.NumberColumn(
                                    "OS", width="small"
                                ),
                            },
                        )

                # ---- Tabela completa + export ----
                # ---- Sazonalidade de compras ----
                st.markdown("##### 📅 Análise de sazonalidade")
                # Data de referência: solicitação > aprovação > recebimento
                data_ref = None
                for col_d in ("data_solicitacao", "data_aprovacao", "data_recebimento"):
                    if col_d in df_c.columns:
                        parsed = pd.to_datetime(df_c[col_d], errors="coerce")
                        if data_ref is None:
                            data_ref = parsed
                        else:
                            data_ref = data_ref.fillna(parsed)
                if data_ref is None or data_ref.notna().sum() == 0:
                    st.caption(
                        "Sem datas válidas em data_solicitacao / aprovação / recebimento "
                        "para montar a sazonalidade."
                    )
                else:
                    df_saz = df_c.copy()
                    df_saz["_data"] = data_ref
                    df_saz = df_saz.dropna(subset=["_data"])
                    df_saz["_ano"] = df_saz["_data"].dt.year
                    df_saz["_mes"] = df_saz["_data"].dt.month
                    df_saz["_mes_nome"] = df_saz["_data"].dt.strftime("%Y-%m")
                    df_saz["_semana"] = df_saz["_data"].dt.isocalendar().week.astype(int)
                    df_saz["_dia_semana"] = df_saz["_data"].dt.dayofweek  # 0=seg
                    df_saz["_dia_nome"] = df_saz["_data"].dt.day_name()

                    nomes_mes = {
                        1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr",
                        5: "Mai", 6: "Jun", 7: "Jul", 8: "Ago",
                        9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
                    }
                    nomes_dia = {
                        0: "Seg", 1: "Ter", 2: "Qua", 3: "Qui",
                        4: "Sex", 5: "Sáb", 6: "Dom",
                    }
                    df_saz["_mes_lbl"] = df_saz["_mes"].map(nomes_mes)
                    df_saz["_dia_lbl"] = df_saz["_dia_semana"].map(nomes_dia)

                    # Filtro de período
                    anos = sorted(df_saz["_ano"].dropna().unique().tolist())
                    f1, f2 = st.columns([2, 3])
                    with f1:
                        anos_sel = st.multiselect(
                            "Anos",
                            options=anos,
                            default=anos,
                            key="saz_anos_compras",
                        )
                    with f2:
                        base_status = st.multiselect(
                            "Status na sazonalidade",
                            options=sorted(df_saz["status"].unique().tolist()),
                            default=sorted(df_saz["status"].unique().tolist()),
                            key="saz_status_compras",
                        )
                    df_sz = df_saz[
                        df_saz["_ano"].isin(anos_sel if anos_sel else anos)
                        & df_saz["status"].isin(
                            base_status if base_status else df_saz["status"].unique()
                        )
                    ]
                    if df_sz.empty:
                        st.warning("Nenhum registro no período filtrado.")
                    else:
                        # ---- Gráfico de linha temporal ----
                        st.markdown("**📈 Linha temporal (quantidade e valor)**")
                        gran = st.radio(
                            "Granularidade",
                            ["Mês", "Semana", "Dia"],
                            horizontal=True,
                            key="saz_granularidade",
                        )
                        df_tmp = df_sz.copy()
                        if gran == "Mês":
                            df_tmp["_periodo"] = df_tmp["_data"].dt.to_period("M").astype(str)
                        elif gran == "Semana":
                            # início da semana (segunda)
                            df_tmp["_periodo"] = (
                                df_tmp["_data"] - pd.to_timedelta(df_tmp["_data"].dt.dayofweek, unit="D")
                            ).dt.strftime("%Y-%m-%d")
                        else:
                            df_tmp["_periodo"] = df_tmp["_data"].dt.strftime("%Y-%m-%d")

                        temporal = (
                            df_tmp.groupby("_periodo", as_index=False)
                            .agg(
                                qtd=("id", "count"),
                                valor=("valor_item", "sum"),
                                custo_medio=("valor_item", "mean"),
                            )
                            .sort_values("_periodo")
                        )
                        temporal["custo_medio"] = temporal["custo_medio"].round(2)
                        temporal["valor"] = temporal["valor"].round(2)

                        # Linha dupla: qtd + valor (eixo secundário)
                        import plotly.graph_objects as go
                        from plotly.subplots import make_subplots

                        fig_lin = make_subplots(specs=[[{"secondary_y": True}]])
                        fig_lin.add_trace(
                            go.Scatter(
                                x=temporal["_periodo"],
                                y=temporal["qtd"],
                                name="Qtd solicitações",
                                mode="lines+markers",
                                line=dict(color="#3b82f6", width=2.5),
                                marker=dict(size=7),
                            ),
                            secondary_y=False,
                        )
                        fig_lin.add_trace(
                            go.Scatter(
                                x=temporal["_periodo"],
                                y=temporal["valor"],
                                name="Valor R$",
                                mode="lines+markers",
                                line=dict(color="#22c55e", width=2.5, dash="dot"),
                                marker=dict(size=7),
                            ),
                            secondary_y=True,
                        )
                        fig_lin.update_layout(
                            title=f"Evolução temporal de compras ({gran.lower()})",
                            hovermode="x unified",
                            legend=dict(orientation="h", yanchor="bottom", y=1.02),
                            margin=dict(t=60, b=40),
                        )
                        fig_lin.update_xaxes(title_text="Período")
                        fig_lin.update_yaxes(title_text="Quantidade", secondary_y=False)
                        fig_lin.update_yaxes(title_text="Valor (R$)", secondary_y=True)
                        st.plotly_chart(fig_lin, width="stretch")

                        # Comparativo lado a lado
                        mensal = (
                            df_sz.assign(
                                _mes_nome=df_sz["_data"].dt.strftime("%Y-%m")
                            )
                            .groupby("_mes_nome", as_index=False)
                            .agg(qtd=("id", "count"), valor=("valor_item", "sum"))
                            .sort_values("_mes_nome")
                        )
                        s1, s2 = st.columns(2)
                        with s1:
                            fig_m_q = px.line(
                                mensal,
                                x="_mes_nome",
                                y="qtd",
                                markers=True,
                                title="Volume de compras por mês",
                            )
                            fig_m_q.update_layout(
                                xaxis_title="Mês", yaxis_title="Qtd solicitações"
                            )
                            st.plotly_chart(fig_m_q, width="stretch")
                        with s2:
                            fig_m_v = px.line(
                                mensal,
                                x="_mes_nome",
                                y="valor",
                                markers=True,
                                title="Valor (R$) por mês",
                                color_discrete_sequence=["#22c55e"],
                            )
                            fig_m_v.update_layout(
                                xaxis_title="Mês", yaxis_title="R$"
                            )
                            st.plotly_chart(fig_m_v, width="stretch")

                        # Padrão por mês do ano (sazonalidade clássica)
                        por_mes = (
                            df_sz.groupby("_mes", as_index=False)
                            .agg(
                                qtd=("id", "count"),
                                valor=("valor_item", "sum"),
                                custo_medio=("valor_item", "mean"),
                            )
                            .sort_values("_mes")
                        )
                        por_mes["_mes_lbl"] = por_mes["_mes"].map(nomes_mes)
                        media_q = float(por_mes["qtd"].mean()) if len(por_mes) else 0
                        por_mes["vs_media"] = (
                            ((por_mes["qtd"] - media_q) / media_q * 100)
                            if media_q
                            else 0
                        )

                        s3, s4 = st.columns(2)
                        with s3:
                            fig_saz = px.bar(
                                por_mes,
                                x="_mes_lbl",
                                y="qtd",
                                title="Sazonalidade — média por mês do ano",
                                color="vs_media",
                                color_continuous_scale="RdYlGn",
                                labels={"_mes_lbl": "Mês", "qtd": "Qtd", "vs_media": "% vs média"},
                            )
                            st.plotly_chart(fig_saz, width="stretch")
                        with s4:
                            por_dia = (
                                df_sz.groupby("_dia_semana", as_index=False)
                                .agg(qtd=("id", "count"), valor=("valor_item", "sum"))
                                .sort_values("_dia_semana")
                            )
                            por_dia["_dia_lbl"] = por_dia["_dia_semana"].map(nomes_dia)
                            fig_dia = px.bar(
                                por_dia,
                                x="_dia_lbl",
                                y="qtd",
                                title="Distribuição por dia da semana",
                                color_discrete_sequence=["#3b82f6"],
                            )
                            st.plotly_chart(fig_dia, width="stretch")

                        # Insights automáticos
                        if len(por_mes) >= 2:
                            pico = por_mes.loc[por_mes["qtd"].idxmax()]
                            vale = por_mes.loc[por_mes["qtd"].idxmin()]
                            st.info(
                                f"📈 **Pico:** {pico['_mes_lbl']} ({int(pico['qtd'])} compras, "
                                f"{pico['vs_media']:+.0f}% vs média) · "
                                f"📉 **Menor:** {vale['_mes_lbl']} ({int(vale['qtd'])} compras, "
                                f"{vale['vs_media']:+.0f}% vs média)"
                            )

                        # Top itens nos meses de pico
                        st.markdown("**Itens mais comprados nos meses de maior volume**")
                        if len(por_mes) and int(por_mes["qtd"].max()) > 0:
                            meses_pico = por_mes.nlargest(
                                min(3, len(por_mes)), "qtd"
                            )["_mes"].tolist()
                            top_pico = (
                                df_sz[df_sz["_mes"].isin(meses_pico)]
                                .groupby("item_nome", as_index=False)
                                .agg(
                                    qtd=("id", "count"),
                                    valor=("valor_item", "sum"),
                                )
                                .sort_values("qtd", ascending=False)
                                .head(10)
                            )
                            t1, t2 = st.columns(2)
                            with t1:
                                st.dataframe(
                                    top_pico.rename(
                                        columns={
                                            "item_nome": "Item",
                                            "qtd": "Qtd",
                                            "valor": "Total R$",
                                        }
                                    ),
                                    width="stretch",
                                    hide_index=True,
                                )
                            with t2:
                                if not top_pico.empty:
                                    fig_top = px.bar(
                                        top_pico,
                                        x="qtd",
                                        y="item_nome",
                                        orientation="h",
                                        title="Top itens nos meses de pico",
                                        color_discrete_sequence=["#f59e0b"],
                                    )
                                    fig_top.update_layout(
                                        yaxis={"categoryorder": "total ascending"}
                                    )
                                    st.plotly_chart(fig_top, width="stretch")

                        with st.expander("📋 Tabela mensal detalhada", expanded=False):
                            det = por_mes[
                                ["_mes_lbl", "qtd", "valor", "custo_medio", "vs_media"]
                            ].copy()
                            det["valor"] = det["valor"].round(2)
                            det["custo_medio"] = det["custo_medio"].round(2)
                            det["vs_media"] = det["vs_media"].round(1)
                            st.dataframe(
                                det.rename(
                                    columns={
                                        "_mes_lbl": "Mês",
                                        "qtd": "Qtd",
                                        "valor": "Total R$",
                                        "custo_medio": "Médio R$",
                                        "vs_media": "% vs média",
                                    }
                                ),
                                width="stretch",
                                hide_index=True,
                            )

                with st.expander("📋 Tabela completa de compras", expanded=False):
                    cols_cp = [
                        c
                        for c in [
                            "id",
                            "status",
                            "aprovado",
                            "item_nome",
                            "equipamento",
                            "prioridade",
                            "chamado_id",
                            "solicitante",
                            "comprador",
                            "prazo_recebimento",
                            "dias_para_chegada",
                            "valor_item",
                            "link_compra",
                            "data_solicitacao",
                            "data_aprovacao",
                            "data_recebimento",
                            "observacao",
                            "observacao_compras",
                        ]
                        if c in df_c.columns
                    ]
                    df_cv = df_c[cols_cp].copy()
                    if "id" in df_cv.columns:
                        df_cv = df_cv.sort_values("id", ascending=False)
                    st.dataframe(
                        df_cv,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "id": st.column_config.NumberColumn("ID", width="small"),
                            "chamado_id": st.column_config.NumberColumn(
                                "OS", width="small"
                            ),
                            "valor_item": st.column_config.NumberColumn(
                                "Valor R$", format="R$ %.2f"
                            ),
                            "link_compra": st.column_config.LinkColumn("Link"),
                        },
                    )
                    st.download_button(
                        "⬇️ Exportar compras (CSV)",
                        data=df_cv.to_csv(index=False).encode("utf-8-sig"),
                        file_name=f"compras_{datetime.now().strftime('%Y%m%d')}.csv",
                        mime="text/csv",
                        key="dl_compras_admin",
                    )


        with tab5:
            st.subheader("👥 Cadastro da Equipe de Manutenção")
            funcoes = ["Técnico", "Líder Técnico", "Elétrico", "Mecânico", "Auxiliar"]
            edit_m = st.session_state.get("edit_membro")

            with st.container(border=True):
                if edit_m:
                    st.markdown(f"##### ✏️ Editando: **{edit_m.get('nome') or ''}**")
                    with st.form("editar_equipe"):
                        nome = st.text_input(
                            "Nome Completo",
                            value=str(edit_m.get("nome") or ""),
                        )
                        f_atual = str(edit_m.get("funcao") or "Técnico")
                        if f_atual not in funcoes:
                            funcoes_opts = [f_atual] + funcoes
                        else:
                            funcoes_opts = funcoes
                        funcao = st.selectbox(
                            "Função",
                            funcoes_opts,
                            index=funcoes_opts.index(f_atual),
                        )
                        contato = st.text_input(
                            "Contato (Telefone/WhatsApp)",
                            value=str(edit_m.get("contato") or ""),
                        )
                        ativo_val = int(edit_m.get("ativo") or 1) == 1
                        ativo = st.checkbox("Ativo (aparece na fila de manutenção)", value=ativo_val)
                        c_save, c_cancel = st.columns(2)
                        with c_save:
                            salvar = st.form_submit_button(
                                "💾 Salvar alterações", type="primary", width="stretch"
                            )
                        with c_cancel:
                            cancelar = st.form_submit_button("Cancelar", width="stretch")
                        if cancelar:
                            st.session_state.edit_membro = None
                            st.rerun()
                        if salvar:
                            if nome and nome.strip():
                                mid = edit_m.get("id")  # pode ser None → gera id novo
                                if atualizar_membro_equipe(
                                    mid,
                                    nome.strip(),
                                    funcao,
                                    contato,
                                    ativo=1 if ativo else 0,
                                ):
                                    st.session_state.edit_membro = None
                                    reload_data()
                                    agendar_efeito_concluido(
                                        f"✅ Membro '{nome.strip()}' salvo!",
                                        celebrar=True,
                                    )
                                    st.rerun()
                            else:
                                st.error("Informe o nome.")
                else:
                    st.markdown("##### ➕ Novo membro")
                    with st.form("cadastro_equipe"):
                        nome = st.text_input("Nome Completo")
                        funcao = st.selectbox("Função", funcoes)
                        contato = st.text_input("Contato (Telefone/WhatsApp)")
                        if st.form_submit_button("Cadastrar Membro", type="primary"):
                            if nome and nome.strip():
                                if adicionar_membro_equipe(nome.strip(), funcao, contato):
                                    reload_data()
                                    agendar_efeito_concluido(
                                        f"✅ Membro {nome.strip()} cadastrado!",
                                        celebrar=True,
                                    )
                                    st.rerun()
                            else:
                                st.error("Informe o nome.")

            if not st.session_state.equipe.empty:
                st.markdown("##### Membros cadastrados")
                # enumerate garante chave única mesmo se id for None/duplicado
                for idx, (_, row) in enumerate(st.session_state.equipe.iterrows()):
                    with st.container(border=True):
                        try:
                            raw_id = row["id"] if "id" in row.index else None
                            try:
                                if raw_id is not None and pd.isna(raw_id):
                                    raw_id = None
                            except (TypeError, ValueError):
                                pass
                            mid = (
                                int(float(raw_id))
                                if raw_id is not None
                                and str(raw_id).strip() not in ("", "None", "nan", "NaN")
                                else None
                            )
                        except (TypeError, ValueError):
                            mid = None
                        ativo_flag = int(row.get("ativo") or 1) == 1
                        col1, col2, col3 = st.columns([5, 1, 1])
                        with col1:
                            badge = "🟢" if ativo_flag else "⚪"
                            st.write(
                                f"{badge} **{row['nome']}** — {row['funcao']} | {row['contato']}"
                            )
                            if mid is None:
                                st.caption("⚠️ Sem ID no banco — edite e salve para corrigir")
                            if not ativo_flag:
                                st.caption("Inativo — não aparece na fila de manutenção")
                        with col2:
                            if st.button("✏️ Editar", key=f"edit_membro_row_{idx}"):
                                st.session_state.edit_membro = {
                                    "id": mid,
                                    "nome": row.get("nome"),
                                    "funcao": row.get("funcao"),
                                    "contato": row.get("contato"),
                                    "ativo": row.get("ativo", 1),
                                }
                                st.rerun()
                        with col3:
                            if st.button("🗑️ Excluir", key=f"del_membro_row_{idx}"):
                                if mid is not None and excluir_membro_equipe(int(mid)):
                                    reload_data()
                                    st.rerun()
                                else:
                                    st.error("Não foi possível excluir: membro sem ID válido.")
            else:
                st.info("Nenhum membro cadastrado.")

        with tab6:
            st.subheader("🏭 Cadastro de Setores / Áreas")
            busca_setor = st.text_input("🔍 Buscar setor", key="busca_setor")
            with st.container(border=True):
                with st.form("cadastro_setor"):
                    if st.session_state.edit_setor:
                        novo_setor = st.text_input(
                            "Nome do Setor", value=st.session_state.edit_setor
                        )
                    else:
                        novo_setor = st.text_input("Nome do Setor / Área")
                    label_btn = "💾 Salvar" if st.session_state.edit_setor else "Adicionar Setor"
                    if st.form_submit_button(label_btn, type="primary"):
                        if novo_setor and novo_setor.strip():
                            lista = list(st.session_state.setores)
                            if st.session_state.edit_setor:
                                try:
                                    idx = lista.index(st.session_state.edit_setor)
                                    lista[idx] = novo_setor.strip()
                                    msg_setor = f"✅ Setor '{novo_setor.strip()}' atualizado!"
                                except ValueError:
                                    lista.append(novo_setor.strip())
                                    msg_setor = f"✅ Setor '{novo_setor.strip()}' adicionado!"
                                st.session_state.edit_setor = None
                            else:
                                if novo_setor.strip() not in lista:
                                    lista.append(novo_setor.strip())
                                    msg_setor = f"✅ Setor '{novo_setor.strip()}' cadastrado!"
                                else:
                                    st.warning("Setor já existe.")
                                    msg_setor = None
                            if salvar_setores(lista):
                                if msg_setor:
                                    agendar_efeito_concluido(msg_setor, celebrar=True)
                                st.rerun()

            setores_filtrados = (
                [s for s in st.session_state.setores if busca_setor.lower() in s.lower()]
                if busca_setor
                else st.session_state.setores
            )
            for i, setor in enumerate(setores_filtrados):
                col1, col2, col3 = st.columns([6, 1, 1])
                with col1:
                    st.write(f"• {setor}")
                with col2:
                    if st.button("✏️ Editar", key=f"edit_s_{i}"):
                        st.session_state.edit_setor = setor
                        st.rerun()
                with col3:
                    if st.button("🗑️ Excluir", key=f"del_s_{i}"):
                        lista = [s for s in st.session_state.setores if s != setor]
                        if salvar_setores(lista):
                            st.rerun()

        with tab7:
            st.subheader("🔧 Cadastro de Equipamentos")
            busca_equip = st.text_input("🔍 Buscar equipamento", key="busca_equip")
            with st.container(border=True):
                with st.form("cadastro_equipamento"):
                    col1, col2 = st.columns(2)
                    edit = st.session_state.edit_equip
                    with col1:
                        nome = st.text_input(
                            "Nome do Equipamento *",
                            value=edit.get("nome", "") if edit else "",
                        )
                        marca = st.text_input(
                            "Marca", value=edit.get("marca", "") if edit else ""
                        )
                        modelo = st.text_input(
                            "Modelo", value=edit.get("modelo", "") if edit else ""
                        )
                        patrimonio = st.text_input(
                            "Número Patrimônio *",
                            value=edit.get("numero_patrimonio", "") if edit else "",
                        )
                    with col2:
                        setor_default = (
                            edit.get("setor")
                            if edit
                            else (st.session_state.setores[0] if st.session_state.setores else "")
                        )
                        setor_idx = (
                            st.session_state.setores.index(setor_default)
                            if setor_default in st.session_state.setores
                            else 0
                        )
                        setor = st.selectbox(
                            "Setor", st.session_state.setores, index=setor_idx
                        )
                        ano = st.number_input(
                            "Ano de Aquisição",
                            min_value=1900,
                            max_value=datetime.now().year,
                            value=int(edit.get("ano_aquisicao", datetime.now().year))
                            if edit
                            else datetime.now().year,
                        )
                        sazonalidade = st.number_input(
                            "Sazonalidade Preventiva (meses)",
                            min_value=1,
                            max_value=60,
                            value=int(edit.get("sazonalidade_meses", 6)) if edit else 6,
                        )
                    label_btn = "💾 Salvar" if edit else "Cadastrar Equipamento"
                    if st.form_submit_button(label_btn, type="primary"):
                        if nome and patrimonio:
                            eq_id = (
                                edit.get("id", proximo_id_equipamento())
                                if edit
                                else proximo_id_equipamento()
                            )
                            novo = {
                                "id": eq_id,
                                "nome": nome.strip(),
                                "marca": marca,
                                "modelo": modelo,
                                "ano_aquisicao": ano,
                                "numero_patrimonio": patrimonio.strip(),
                                "setor": setor,
                                "sazonalidade_meses": sazonalidade,
                                "ultima_preventiva": edit.get(
                                    "ultima_preventiva",
                                    datetime.now().date().isoformat(),
                                )
                                if edit
                                else datetime.now().date().isoformat(),
                                "proxima_preventiva": (
                                    datetime.now() + timedelta(days=sazonalidade * 30)
                                )
                                .date()
                                .isoformat()
                                if not edit
                                else edit.get(
                                    "proxima_preventiva",
                                    (
                                        datetime.now()
                                        + timedelta(days=sazonalidade * 30)
                                    )
                                    .date()
                                    .isoformat(),
                                ),
                                "silenciar_ate": edit.get("silenciar_ate")
                                if edit
                                else None,
                            }
                            if salvar_equipamento(novo):
                                st.session_state.edit_equip = None
                                agendar_efeito_concluido(
                                    f"✅ Equipamento '{nome.strip()}' "
                                    + ("atualizado!" if edit else "cadastrado!"),
                                    celebrar=True,
                                )
                                st.rerun()
                        else:
                            st.error("Nome e patrimônio são obrigatórios.")

            equipamentos_filtrados = (
                [
                    eq
                    for eq in st.session_state.equipamentos
                    if busca_equip.lower() in nome_equipamento(eq).lower()
                    or busca_equip.lower()
                    in str(eq.get("numero_patrimonio", "")).lower()
                ]
                if busca_equip
                else st.session_state.equipamentos
            )
            for i, eq in enumerate(equipamentos_filtrados):
                nome_eq = nome_equipamento(eq)
                eq_id = eq.get("id")
                hist_eq = carregar_historico_manutencao(eq_id)
                custo_eq = sum(float(h.get("custo_pecas") or 0) for h in hist_eq)
                horas_eq = sum(float(h.get("horas_homem") or 0) for h in hist_eq)
                n_hist = len(hist_eq)
                label = (
                    f"{nome_eq} · Pat {eq.get('numero_patrimonio', 'N/A')} "
                    f"· 🔧 {n_hist} · R$ {custo_eq:,.0f} · {horas_eq:.1f}h"
                )
                with st.expander(label):
                    # Resumo cadastral
                    c_a, c_b, c_c = st.columns(3)
                    with c_a:
                        st.markdown(f"**Marca / Modelo**\n\n{eq.get('marca') or '—'} / {eq.get('modelo') or '—'}")
                        st.markdown(f"**Setor**\n\n{eq.get('setor') or '—'}")
                    with c_b:
                        st.markdown(f"**Ano**\n\n{eq.get('ano_aquisicao') or '—'}")
                        st.markdown(f"**Sazonalidade**\n\n{eq.get('sazonalidade_meses') or 6} meses")
                    with c_c:
                        st.markdown(f"**Última preventiva**\n\n{eq.get('ultima_preventiva') or '—'}")
                        st.markdown(f"**Próxima**\n\n{eq.get('proxima_preventiva') or '—'}")
                        if eq.get("silenciar_ate"):
                            st.caption(f"🔕 Alerta silenciado até {eq.get('silenciar_ate')}")

                    m1, m2, m3 = st.columns(3)
                    m1.metric("Custo peças", f"R$ {custo_eq:,.2f}")
                    m2.metric("Horas-homem", f"{horas_eq:.1f} h")
                    m3.metric("Registros", n_hist)

                    st.markdown("#### 📋 Histórico de manutenções")
                    if hist_eq:
                        for h in hist_eq:
                            tipo = h.get("tipo") or "—"
                            data_h = h.get("data_manutencao") or "—"
                            st.markdown(
                                f"""
                                <div style="padding:8px 12px;margin:4px 0;border-radius:10px;
                                            border:1px solid #333;background:#111;border-left:3px solid #dc2626;">
                                    <b style="color:#f1f1f1;">{tipo}</b>
                                    <span style="color:#a3a3a3;"> · {data_h}</span><br/>
                                    <span style="color:#ddd;">{h.get('descricao') or ''}</span><br/>
                                    <span style="color:#a3a3a3;font-size:0.85rem;">
                                        👤 {h.get('executante') or '—'} ·
                                        🔩 {h.get('pecas_trocadas') or '—'} ·
                                        💰 R$ {float(h.get('custo_pecas') or 0):,.2f} ·
                                        ⏱ {float(h.get('horas_homem') or 0):.1f} h
                                    </span>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )
                    else:
                        st.caption("Nenhuma manutenção registrada ainda.")

                    with st.popover("➕ Registrar manutenção", key=f"pop_hist_{eq_id}_{i}"):
                        tipo_m = st.selectbox(
                            "Tipo",
                            ["Preventiva", "Corretiva", "Preditiva", "Outros"],
                            key=f"hist_tipo_{eq_id}_{i}",
                        )
                        exec_m = st.text_input("Executante", key=f"hist_exec_{eq_id}_{i}")
                        desc_m = st.text_area("Descrição", key=f"hist_desc_{eq_id}_{i}")
                        pecas_m = st.text_input("Peças trocadas", key=f"hist_pecas_{eq_id}_{i}")
                        cc1, cc2 = st.columns(2)
                        with cc1:
                            custo_m = st.number_input(
                                "Custo peças (R$)", min_value=0.0, step=10.0, key=f"hist_custo_{eq_id}_{i}"
                            )
                        with cc2:
                            horas_m = st.number_input(
                                "Horas-homem", min_value=0.0, step=0.5, key=f"hist_horas_{eq_id}_{i}"
                            )
                        obs_m = st.text_input("Observação", key=f"hist_obs_{eq_id}_{i}")
                        if st.button("💾 Salvar registro", key=f"hist_save_{eq_id}_{i}", type="primary"):
                            if tipo_m == "Preventiva":
                                ok = concluir_preventiva(
                                    eq,
                                    executante=exec_m or "",
                                    descricao=desc_m or "Manutenção preventiva",
                                    pecas=pecas_m or "",
                                    custo_pecas=float(custo_m or 0),
                                    horas_homem=float(horas_m or 0),
                                    observacao=obs_m or "",
                                )
                            else:
                                reg = {
                                    "id": proximo_id_manutencao(),
                                    "equipamento_id": eq_id,
                                    "equipamento_nome": nome_eq,
                                    "tipo": tipo_m,
                                    "data_manutencao": datetime.now().strftime(
                                        "%Y-%m-%d %H:%M:%S"
                                    ),
                                    "executante": exec_m,
                                    "descricao": desc_m,
                                    "pecas_trocadas": pecas_m,
                                    "custo_pecas": float(custo_m or 0),
                                    "horas_homem": float(horas_m or 0),
                                    "chamado_id": None,
                                    "observacao": obs_m,
                                }
                                ok = salvar_manutencao(reg)
                            if ok:
                                agendar_efeito_concluido(
                                    f"✅ Manutenção ({tipo_m}) registrada!",
                                    celebrar=True,
                                )
                                st.rerun()

                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("✏️ Editar", key=f"edit_eqp_{i}_{eq_id}"):
                            st.session_state.edit_equip = eq.copy()
                            st.rerun()
                    with col2:
                        if st.button("🗑️ Excluir", key=f"del_eqp_{i}_{eq_id}"):
                            if excluir_equipamento(int(eq_id)):
                                st.rerun()

        with tab8:
            st.subheader("🖼️ Galeria de Fotos")
            com_foto = [
                c
                for c in st.session_state.chamados
                if c.get("foto_path")
                and isinstance(c.get("foto_path"), str)
                and os.path.exists(c.get("foto_path"))
            ]
            if com_foto:
                cols = st.columns(3)
                for i, cham in enumerate(com_foto):
                    with cols[i % 3]:
                        with st.container(border=True):
                            st.image(cham["foto_path"], width="stretch")
                            st.caption(f"OS {cham['id']} — {cham.get('setor')}")
            else:
                st.info("Nenhuma foto registrada ainda.")

        with tab9:
            st.subheader("📥 Importar Ordens de Serviço")
            with st.container(border=True):
                uploaded_file = st.file_uploader(
                    "Selecione o arquivo MANUTENÇÃO CRN - 2026.xlsx", type=["xlsx"]
                )
                if st.button("🔄 Importar Dados da Planilha", type="primary"):
                    if uploaded_file:
                        try:
                            df_import = pd.read_excel(uploaded_file, sheet_name="Planilha1")
                            st.success(f"✅ {len(df_import)} linhas lidas da planilha!")
                            st.dataframe(df_import.head())
                            # (Importação completa pode ser expandida depois)
                        except Exception as e:
                            log_error("Importar planilha falhou", e)
                            st.error(f"Erro: {e}")
                    else:
                        st.warning("Selecione o arquivo.")

st.caption(
    f"**Sistema v1.5 (Dual-Write Local↔Cloud)** — By Leandro Coelho | Logs em `logs/app_errors.log`"
)