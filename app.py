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

from database import (
    # feedback
    efeito_concluido,
    agendar_efeito_concluido,
    _mostrar_efeito_pendente,
    log_error,
    logger,
    # conexão / init
    init_db,
    is_cloud,
    get_connection_string,
    sync_local_to_cloud,
    # chamados
    carregar_dados,
    salvar_chamado,
    proximo_id_chamado,
    # equipe / setores / equipamentos
    carregar_equipe,
    adicionar_membro_equipe,
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

if "chamados" not in st.session_state:
    st.session_state.chamados = carregar_dados()
if "equipe" not in st.session_state:
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
if "ultimo_alarme" not in st.session_state:
    st.session_state.ultimo_alarme = datetime.now()

PRIORIDADES = {"Crítica": 1, "Alta": 2, "Média": 3, "Baixa": 4}
SLA_TEMPO = {"Crítica": 20, "Alta": 60, "Média": 240, "Baixa": 1440}


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


# ====================== CABEÇALHO ======================
header(
    "Gestão de Chamados e Manutenção",
    "Fluxo integrado de solicitações, execução e indicadores",
    icon="🏭",
)
_mostrar_efeito_pendente()

# Indicador de modo de banco
status = st.session_state.get("db_status", {})
if status.get("cloud_ok"):
    st.sidebar.success("☁️ Local + SQLite Cloud (dual-write)")
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

            if st.form_submit_button("🚀 ENVIAR SOLICITAÇÃO", use_container_width=True, type="primary"):
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
                        agendar_efeito_concluido(
                            f"✅ Chamado Nº {novo_id} aberto com sucesso!",
                            celebrar=True,
                        )
                        st.rerun()
                else:
                    st.error("❌ Preencha os campos obrigatórios.")

    with aba_historico:
        if st.session_state.chamados:
            df = pd.DataFrame(st.session_state.chamados)
            total = len(df)
            concluidos = len(df[df["status"] == "Concluído"])
            with st.container(border=True):
                m1, m2, m3 = st.columns(3)
                m1.metric("Total", total)
                m2.metric("Concluídos", concluidos)
                m3.metric("Pendentes", total - concluidos, delta_color="inverse")

            col1, col2 = st.columns(2)
            with col1:
                df_visao = df.copy()
                df_visao["Visão"] = df_visao["status"].apply(
                    lambda x: "Solucionado" if x == "Concluído" else "Pendente"
                )
                fig = px.pie(
                    df_visao,
                    names="Visão",
                    color="Visão",
                    hole=0.45,
                    color_discrete_map={
                        "Solucionado": CORES_STATUS.get("Concluído", "#22c55e"),
                        "Pendente": CORES_STATUS.get("Aberto", "#ef4444"),
                    },
                )
                st.plotly_chart(fig, use_container_width=True)
            with col2:
                fig = px.histogram(
                    df,
                    x="prioridade",
                    color="status",
                    barmode="group",
                    color_discrete_map=CORES_STATUS,
                )
                st.plotly_chart(fig, use_container_width=True)

            st.dataframe(
                df.drop(columns=["foto_path", "foto_solucao_path"], errors="ignore"),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Nenhum chamado registrado ainda.")

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

    st_autorefresh(interval=30000, limit=None, key="refresh_maintenance")

    # Alertas sonoros (arquivo local beep-09.mp3 na pasta do app)
    chamados_abertos = [c for c in st.session_state.chamados if c.get("status") == "Aberto"]
    if chamados_abertos:
        agora = datetime.now()
        if (agora - st.session_state.ultimo_alarme).total_seconds() >= 60:
            st.success(f"🛎️ **{len(chamados_abertos)} chamado(s) ABERTO(S)** aguardando!")
            beep_path = Path("beep-09.mp3")
            if beep_path.is_file():
                import base64
                b64 = base64.b64encode(beep_path.read_bytes()).decode("ascii")
                st.markdown(
                    f'<audio autoplay><source src="data:audio/mpeg;base64,{b64}" type="audio/mpeg"></audio>',
                    unsafe_allow_html=True,
                )
            else:
                # Fallback se o arquivo não estiver na pasta do app
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
                partes.append(f"🔴 {vencidos} vencido(s)")
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
                        "🔴 VENCIDO", "#7f1d1d", "#fecaca", "#ef4444",
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
                    use_container_width=True,
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
                        use_container_width=True,
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
                        use_container_width=True,
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
                    st.caption("Prioridade (hoje / vencidos / ≤ 7 dias)")
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
            + timedelta(minutes=SLA_TEMPO.get(c.get("prioridade"), 1440))
            - datetime.now()
        ).total_seconds()
        return (prio, sla_score, abertura_dt)

    ativos_ordenados = sorted(ativos, key=ordem_chamado)

    if not ativos_ordenados:
        st.success("🎉 Nenhum chamado ativo com os filtros atuais.")
    else:
        st.subheader(f"📋 Chamados Ativos ({len(ativos_ordenados)})")
        for cham in ativos_ordenados:
            with st.container(border=True):
                abertura_dt = parse_datetime_safe(
                    cham.get("data_hora_abertura"), default=datetime.now()
                )
                prazo = abertura_dt + timedelta(
                    minutes=SLA_TEMPO.get(cham.get("prioridade"), 1440)
                )
                try:
                    min_restantes = int((prazo - datetime.now()).total_seconds() / 60)
                except (ValueError, TypeError, OverflowError):
                    min_restantes = 0
                sla_txt = (
                    "🔴 VENCIDO"
                    if min_restantes < 0
                    else "🟠 Crítico"
                    if min_restantes < 30
                    else "🟢 No prazo"
                )

                st.markdown(
                    f"""
                **OS Nº {cham.get('id')}** &nbsp;
                {badge_prioridade(cham.get('prioridade'))} &nbsp;
                {badge_status(cham.get('status'))} &nbsp;
                <span style='color:#facc15; font-weight:bold;'>{sla_txt} ({min_restantes} min)</span>
                """,
                    unsafe_allow_html=True,
                )

                c1, c2 = st.columns([3, 1])
                with c1:
                    st.write(
                        f"**Setor:** {cham.get('setor')} | **Equipamento:** {cham.get('equipamento', 'N/A')}"
                    )
                    st.write(f"**Solicitante:** {cham.get('solicitante')}")
                    if cham.get("executante"):
                        st.write(f"**Técnico:** {cham.get('executante')}")
                    st.write(f"**Descrição:** {cham.get('descricao')}")
                with c2:
                    fp = cham.get("foto_path")
                    if fp and isinstance(fp, str) and os.path.exists(fp):
                        st.image(fp, use_container_width=True)

                if cham.get("status") == "Aberto":
                    nome_tec = st.selectbox(
                        "Selecionar Técnico:",
                        tecnicos[1:] if len(tecnicos) > 1 else ["—"],
                        key=f"t_{cham.get('id')}",
                    )
                    if st.button(
                        "🚀 Iniciar Manutenção",
                        key=f"b_in_{cham.get('id')}",
                        use_container_width=True,
                        type="primary",
                    ):
                        if nome_tec and nome_tec != "—":
                            cham["status"] = "Em Atendimento"
                            cham["executante"] = nome_tec
                            cham["data_hora_inicio"] = datetime.now().isoformat()
                            if salvar_chamado(cham):
                                agendar_efeito_concluido(
                                    f"🚀 OS {cham.get('id')} iniciada por {nome_tec}!",
                                    celebrar=True,
                                )
                                st.rerun()

                elif cham.get("status") == "Aguardando Peça":
                    st.caption(f"👨‍🔧 Técnico: **{cham.get('executante')}**")
                    st.warning(
                        f"🛒 **Aguardando compra/chegada de peça:** {cham.get('peca_solicitada') or 'Não informado'}"
                    )
                    if cham.get("peca_observacao"):
                        st.caption(f"📝 Observação: {cham.get('peca_observacao')}")
                    # Status da solicitação de compras vinculada
                    compras_ch = carregar_compras_por_chamado(int(cham.get("id") or 0))
                    for cp in compras_ch:
                        st.info(
                            f"**Compras #{cp.get('id')}** · {cp.get('status')} · "
                            f"Aprovado: {cp.get('aprovado') or '—'} · "
                            f"Chegada: {cp.get('dias_para_chegada') or '—'} dia(s) · "
                            f"Valor: R$ {float(cp.get('valor_item') or 0):,.2f}"
                        )
                        if cp.get("link_compra"):
                            st.caption(f"🔗 {cp.get('link_compra')}")
                    if st.button(
                        "📦 Peça Recebida — Retomar Atendimento",
                        key=f"b_retomar_{cham.get('id')}",
                        type="primary",
                        use_container_width=True,
                    ):
                        cham["status"] = "Em Atendimento"
                        for cp in compras_ch:
                            if cp.get("status") in ("Aprovada", "Comprada", "Pendente"):
                                cp["status"] = "Recebida"
                                cp["data_recebimento"] = datetime.now().strftime(
                                    "%Y-%m-%d %H:%M:%S"
                                )
                                salvar_compra(cp)
                        if salvar_chamado(cham):
                            agendar_efeito_concluido(
                                f"📦 Peça recebida — OS {cham.get('id')} retomada!",
                                celebrar=False,
                            )
                            st.rerun()

                else:
                    st.caption(f"👨‍🔧 Técnico: **{cham.get('executante')}**")

                    with st.expander("🛒 Precisa de uma peça para o reparo?"):
                        peca_nome = st.text_input(
                            "Peça / Item necessário *", key=f"peca_nome_{cham.get('id')}"
                        )
                        peca_link = st.text_input(
                            "Link (site / Mercado Livre)",
                            key=f"peca_link_{cham.get('id')}",
                            placeholder="https://...",
                        )
                        peca_prazo = st.date_input(
                            "Prazo desejado de recebimento",
                            key=f"peca_prazo_{cham.get('id')}",
                        )
                        peca_obs = st.text_area(
                            "Observação (fornecedor, quantidade, urgência...)",
                            key=f"peca_obs_{cham.get('id')}",
                        )
                        # Histórico de compra anterior do mesmo item
                        if peca_nome and peca_nome.strip():
                            hist_c = historico_compras_item(
                                peca_nome.strip(), cham.get("equipamento")
                            )
                            if hist_c:
                                st.caption("📜 Já comprado anteriormente:")
                                for h in hist_c[:3]:
                                    st.caption(
                                        f"· {h.get('data_solicitacao') or '—'} · "
                                        f"{h.get('equipamento')} · "
                                        f"R$ {float(h.get('valor_item') or 0):,.2f} · "
                                        f"{h.get('status')}"
                                    )
                        if st.button(
                            "🛒 Solicitar Compra de Peça",
                            key=f"b_peca_{cham.get('id')}",
                            use_container_width=True,
                        ):
                            if peca_nome and peca_nome.strip():
                                prazo_str = (
                                    peca_prazo.isoformat()
                                    if hasattr(peca_prazo, "isoformat")
                                    else str(peca_prazo)
                                )
                                cham["status"] = "Aguardando Peça"
                                cham["peca_solicitada"] = peca_nome.strip()
                                cham["peca_observacao"] = peca_obs.strip() if peca_obs else ""
                                cham["data_solicitacao_peca"] = datetime.now().isoformat()
                                compra = criar_solicitacao_compra_do_chamado(
                                    cham,
                                    item_nome=peca_nome.strip(),
                                    link_compra=peca_link or "",
                                    observacao=peca_obs or "",
                                    prazo_recebimento=prazo_str,
                                    solicitante=cham.get("executante") or "",
                                )
                                if salvar_chamado(cham) and compra:
                                    agendar_efeito_concluido(
                                        f"🛒 Solicitação de compra #{compra['id']} enviada ao setor de Compras!",
                                        celebrar=True,
                                    )
                                    st.rerun()
                            else:
                                st.error("Informe o nome da peça.")

                    opcao_sol = st.radio(
                        "Foto da Solução:",
                        ["Sem foto", "Tirar foto", "Galeria"],
                        horizontal=True,
                        key=f"sol_{cham.get('id')}",
                    )
                    foto_sol = None
                    if opcao_sol == "Tirar foto":
                        f = st.camera_input("Capturar Solução", key=f"cam_sol_{cham.get('id')}")
                        if f:
                            foto_sol = comprimir_imagem(f, "solucao")
                    elif opcao_sol == "Galeria":
                        f = st.file_uploader(
                            "Selecionar foto",
                            type=["jpg", "jpeg", "png"],
                            key=f"up_sol_{cham.get('id')}",
                        )
                        if f:
                            foto_sol = comprimir_imagem(f, "solucao")

                    solucao_txt = st.text_area(
                        "Descreva a solução *", key=f"txt_{cham.get('id')}"
                    )
                    comentario_txt = st.text_area(
                        "💬 Comentário adicional (opcional)",
                        value=cham.get("comentario_conclusao") or "",
                        key=f"comentario_{cham.get('id')}",
                        help="Observações extras sobre o atendimento. Pode ser salvo antes de concluir o chamado.",
                    )
                    if st.button(
                        "💾 Salvar Comentário",
                        key=f"b_salvar_com_{cham.get('id')}",
                        use_container_width=True,
                    ):
                        cham["comentario_conclusao"] = (
                            comentario_txt.strip() if comentario_txt else ""
                        )
                        if salvar_chamado(cham):
                            agendar_efeito_concluido("💾 Comentário salvo!", celebrar=False)
                            st.rerun()

                    if st.button(
                        "✅ Concluir Chamado",
                        key=f"b_fim_{cham.get('id')}",
                        type="primary",
                        use_container_width=True,
                    ):
                        if solucao_txt and solucao_txt.strip():
                            cham["status"] = "Concluído"
                            cham["solucao_descricao"] = solucao_txt.strip()
                            cham["foto_solucao_path"] = foto_sol
                            cham["comentario_conclusao"] = (
                                comentario_txt.strip() if comentario_txt else ""
                            )
                            cham["data_hora_conclusao"] = datetime.now().isoformat()
                            if salvar_chamado(cham):
                                agendar_efeito_concluido(
                                    f"✅ Chamado Nº {cham.get('id')} concluído!",
                                    celebrar=True,
                                )
                                st.rerun()
                        else:
                            st.error("Descreva a solução.")

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
    filtro_cp = st.multiselect(
        "Status",
        ["Pendente", "Aprovada", "Rejeitada", "Recebida"],
        default=["Pendente", "Aprovada"],
        key="filtro_compras_status",
    )
    lista_cp = [c for c in compras if (c.get("status") or "Pendente") in filtro_cp]
    if not lista_cp:
        st.success("Nenhuma solicitação com os filtros atuais.")
    else:
        st.caption(f"{len(lista_cp)} solicitação(ões)")
        for cp in lista_cp:
            cid = cp.get("id")
            with st.container(border=True):
                st.markdown(
                    f"**Compra #{cid}** · OS **{cp.get('chamado_id')}** · "
                    f"{cp.get('prioridade') or '—'} · **{cp.get('status')}**"
                )
                st.write(
                    f"**Item:** {cp.get('item_nome')}  \n"
                    f"**Equipamento:** {cp.get('equipamento') or '—'}  \n"
                    f"**Solicitante:** {cp.get('solicitante') or '—'}  \n"
                    f"**Prazo recebimento:** {cp.get('prazo_recebimento') or '—'}  \n"
                    f"**Obs.:** {cp.get('observacao') or '—'}"
                )
                if cp.get("link_compra"):
                    st.markdown(f"🔗 [Abrir link de compra]({cp.get('link_compra')})")

                # Histórico do item
                hist = historico_compras_item(
                    cp.get("item_nome") or "", cp.get("equipamento")
                )
                hist_outros = [h for h in hist if h.get("id") != cid]
                if hist_outros:
                    with st.expander(f"📜 Compras anteriores deste item ({len(hist_outros)})"):
                        for h in hist_outros[:8]:
                            st.caption(
                                f"#{h.get('id')} · {h.get('data_solicitacao')} · "
                                f"{h.get('equipamento')} · R$ {float(h.get('valor_item') or 0):,.2f} · "
                                f"{h.get('status')} · aprovado={h.get('aprovado')}"
                            )

                if cp.get("status") == "Pendente":
                    with st.popover("⚙️ Analisar / Aprovar", key=f"pop_cp_{cid}"):
                        aprov = st.radio(
                            "Compra aprovada?",
                            ["Sim", "Não"],
                            horizontal=True,
                            key=f"cp_aprov_{cid}",
                        )
                        dias_ch = st.number_input(
                            "Dias para chegada (se aprovada)",
                            min_value=0,
                            max_value=365,
                            value=_safe_int(cp.get("dias_para_chegada"), 7),
                            key=f"cp_dias_{cid}",
                        )
                        valor = st.number_input(
                            "Valor do item (R$)",
                            min_value=0.0,
                            step=10.0,
                            value=_safe_float(cp.get("valor_item"), 0.0),
                            key=f"cp_valor_{cid}",
                        )
                        link_n = st.text_input(
                            "Link (atualizar se necessário)",
                            value=cp.get("link_compra") or "",
                            key=f"cp_link_{cid}",
                        )
                        obs_cp = st.text_area(
                            "Observação do comprador",
                            value=cp.get("observacao_compras") or "",
                            key=f"cp_obs_{cid}",
                        )
                        comprador = st.text_input(
                            "Seu nome (comprador)",
                            key=f"cp_nome_{cid}",
                        )
                        if st.button(
                            "💾 Registrar decisão",
                            key=f"cp_save_{cid}",
                            type="primary",
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
                                cp["valor_item"] = _safe_float(valor, 0.0)
                                msg = (
                                    f"Compra APROVADA do item '{cp.get('item_nome')}'. "
                                    f"Valor R$ {float(valor):,.2f}. "
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
                                    _notificar_chamado_compra(int(cp["chamado_id"]), msg)
                                agendar_efeito_concluido(msg, celebrar=(aprov == "Sim"))
                                st.rerun()

                elif cp.get("status") == "Aprovada":
                    st.success(
                        f"Aprovada · chegada em {cp.get('dias_para_chegada')} dia(s) · "
                        f"R$ {float(cp.get('valor_item') or 0):,.2f}"
                    )
                    if st.button(
                        "📦 Marcar como recebida",
                        key=f"cp_rec_{cid}",
                        type="primary",
                    ):
                        cp["status"] = "Recebida"
                        cp["data_recebimento"] = datetime.now().strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                        if salvar_compra(cp):
                            msg = (
                                f"Item '{cp.get('item_nome')}' RECEBIDO. "
                                f"Valor R$ {float(cp.get('valor_item') or 0):,.2f}."
                            )
                            if cp.get("chamado_id"):
                                _notificar_chamado_compra(int(cp["chamado_id"]), msg)
                                # retoma OS automaticamente
                                for c in st.session_state.chamados:
                                    if c.get("id") == cp.get("chamado_id") and c.get(
                                        "status"
                                    ) == "Aguardando Peça":
                                        c["status"] = "Em Atendimento"
                                        salvar_chamado(c)
                                        break
                            agendar_efeito_concluido(msg, celebrar=True)
                            st.rerun()

                else:
                    st.caption(
                        f"Status final: {cp.get('status')} · "
                        f"Comprador: {cp.get('comprador') or '—'} · "
                        f"Valor R$ {float(cp.get('valor_item') or 0):,.2f}"
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
                if st.form_submit_button("Efetuar Login", type="primary", use_container_width=True):
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
                if st.button("☁️ Sincronizar Local → Cloud", use_container_width=True, type="primary"):
                    with st.spinner("Sincronizando dados locais para o SQLite Cloud..."):
                        ok, msg = sync_local_to_cloud()
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)
            else:
                st.caption("Configure SQLITECLOUD_URL nos Secrets para sincronizar.")
        with col_c:
            if st.button("🚪 Sair", use_container_width=True):
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

        tab1, tab2, tab3, tab4, tab_comp, tab5, tab6, tab7, tab8, tab9 = st.tabs([
            "📊 Dashboard Geral",
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
                    use_container_width=True,
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
                    st.plotly_chart(fig, use_container_width=True)
                    if "status" in df.columns:
                        fig_s = px.pie(
                            df,
                            names="status",
                            color="status",
                            title="Distribuição por Status",
                            hole=0.4,
                            color_discrete_map=CORES_STATUS,
                        )
                        st.plotly_chart(fig_s, use_container_width=True)
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
                    st.plotly_chart(fig, use_container_width=True)
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
                            st.plotly_chart(fig_t, use_container_width=True)
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
                    st.plotly_chart(fig_e, use_container_width=True)
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
                        use_container_width=True,
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
                            use_container_width=True,
                        )

        with tab3:
            st.subheader("📊 Análise de Tempo de Execução")
            df_analise = (
                df[df["status"] == "Concluído"].copy() if not df.empty else pd.DataFrame()
            )
            if not df_analise.empty:
                df_analise["data_hora_inicio"] = pd.to_datetime(
                    df_analise["data_hora_inicio"], errors="coerce"
                )
                df_analise["data_hora_conclusao"] = pd.to_datetime(
                    df_analise["data_hora_conclusao"], errors="coerce"
                )
                df_analise["tempo_minutos"] = (
                    df_analise["data_hora_conclusao"] - df_analise["data_hora_inicio"]
                ).dt.total_seconds() / 60
                tempo_tecnico = (
                    df_analise.groupby("executante")["tempo_minutos"]
                    .mean()
                    .round(1)
                    .reset_index()
                )
                tempo_tecnico.columns = ["Técnico", "Tempo Médio (min)"]
                st.plotly_chart(
                    px.bar(
                        tempo_tecnico,
                        x="Técnico",
                        y="Tempo Médio (min)",
                        color_discrete_sequence=["#2563EB"],
                    ),
                    use_container_width=True,
                )
                tempo_prio = (
                    df_analise.groupby("prioridade")["tempo_minutos"]
                    .mean()
                    .round(1)
                    .reset_index()
                )
                st.plotly_chart(
                    px.bar(
                        tempo_prio,
                        x="prioridade",
                        y="tempo_minutos",
                        color="prioridade",
                        color_discrete_map=CORES_PRIORIDADE,
                    ),
                    use_container_width=True,
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
                    use_container_width=True,
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
                st.dataframe(df_custos, use_container_width=True, hide_index=True)
                fig = px.bar(
                    df_custos.head(15),
                    x="Equipamento",
                    y="Custo Peças (R$)",
                    color="Horas-Homem",
                    title="Top equipamentos por custo de peças",
                    color_continuous_scale="Reds",
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info(
                    "Ainda não há histórico de manutenções com custo/horas. "
                    "Registre preventivas nos alertas ou adicione no cadastro do equipamento."
                )

        with tab_comp:
            st.subheader("🛒 Compras — tabela e índices")
            if df_compras.empty:
                st.info("Nenhuma solicitação de compra registrada ainda.")
            else:
                df_c = df_compras.copy()
                # Índices
                total_c = len(df_c)
                aprov_c = len(df_c[df_c["status"].isin(["Aprovada", "Recebida"])])
                taxa_apr = (aprov_c / total_c * 100) if total_c else 0
                valor_sum = float(df_c["valor_item"].fillna(0).sum()) if "valor_item" in df_c.columns else 0
                valor_medio = float(df_c["valor_item"].fillna(0).mean()) if total_c else 0
                lead_medio = (
                    float(
                        df_c.loc[
                            df_c["status"].isin(["Aprovada", "Recebida"]),
                            "dias_para_chegada",
                        ]
                        .dropna()
                        .mean()
                    )
                    if "dias_para_chegada" in df_c.columns
                    else 0
                )

                i1, i2, i3, i4, i5 = st.columns(5)
                i1.metric("Total solicitações", total_c)
                i2.metric("Taxa aprovação", f"{taxa_apr:.0f}%")
                i3.metric("Valor total", f"R$ {valor_sum:,.2f}")
                i4.metric("Valor médio", f"R$ {valor_medio:,.2f}")
                i5.metric("Lead time médio", f"{lead_medio:.1f} d" if lead_medio else "—")

                # Tabela formatada
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
                if "valor_item" in df_cv.columns:
                    df_cv["valor_item"] = df_cv["valor_item"].fillna(0).round(2)
                df_cv = df_cv.sort_values("id", ascending=False)
                st.dataframe(
                    df_cv,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "id": st.column_config.NumberColumn("ID", width="small"),
                        "chamado_id": st.column_config.NumberColumn("OS", width="small"),
                        "valor_item": st.column_config.NumberColumn(
                            "Valor R$", format="R$ %.2f"
                        ),
                        "link_compra": st.column_config.LinkColumn("Link"),
                        "status": st.column_config.TextColumn("Status", width="medium"),
                    },
                )
                st.download_button(
                    "⬇️ Exportar compras (CSV)",
                    data=df_cv.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"compras_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    key="dl_compras_admin",
                )

                # Ranking itens / equipamentos
                st.markdown("##### Rankings")
                r1, r2 = st.columns(2)
                with r1:
                    if "item_nome" in df_c.columns:
                        rank_item = (
                            df_c.groupby("item_nome")
                            .agg(
                                qtd=("id", "count"),
                                valor=("valor_item", "sum"),
                            )
                            .reset_index()
                            .sort_values("qtd", ascending=False)
                        )
                        st.markdown("**Itens mais solicitados**")
                        st.dataframe(rank_item, use_container_width=True, hide_index=True)
                with r2:
                    if "equipamento" in df_c.columns:
                        rank_eq = (
                            df_c.groupby("equipamento")
                            .agg(
                                qtd=("id", "count"),
                                valor=("valor_item", "sum"),
                            )
                            .reset_index()
                            .sort_values("valor", ascending=False)
                        )
                        st.markdown("**Gasto por equipamento**")
                        st.dataframe(rank_eq, use_container_width=True, hide_index=True)

        with tab5:
            st.subheader("👥 Cadastro da Equipe de Manutenção")
            with st.container(border=True):
                with st.form("cadastro_equipe"):
                    nome = st.text_input("Nome Completo")
                    funcao = st.selectbox(
                        "Função",
                        ["Técnico", "Líder Técnico", "Elétrico", "Mecânico", "Auxiliar"],
                    )
                    contato = st.text_input("Contato (Telefone/WhatsApp)")
                    if st.form_submit_button("Cadastrar Membro", type="primary"):
                        if nome and nome.strip():
                            if adicionar_membro_equipe(nome.strip(), funcao, contato):
                                agendar_efeito_concluido(
                                    f"✅ Membro {nome.strip()} cadastrado!",
                                    celebrar=True,
                                )
                                st.rerun()
                        else:
                            st.error("Informe o nome.")

            if not st.session_state.equipe.empty:
                for i, row in st.session_state.equipe.iterrows():
                    with st.container(border=True):
                        col1, col2 = st.columns([5, 1])
                        with col1:
                            st.write(
                                f"**{row['nome']}** — {row['funcao']} | {row['contato']}"
                            )
                        with col2:
                            if st.button("🗑️ Excluir", key=f"del_eq_{i}"):
                                mid = row.get("id")
                                if mid is not None and excluir_membro_equipe(int(mid)):
                                    st.rerun()
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
                        if st.button("✏️ Editar", key=f"edit_eq_{i}"):
                            st.session_state.edit_equip = eq.copy()
                            st.rerun()
                    with col2:
                        if st.button("🗑️ Excluir", key=f"del_eqp_{i}"):
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
                            st.image(cham["foto_path"], use_container_width=True)
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