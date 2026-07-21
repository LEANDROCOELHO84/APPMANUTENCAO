import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import os
from PIL import Image, ImageOps
import plotly.express as px
import hashlib
import sqlite3
from streamlit_autorefresh import st_autorefresh

# ====================== CONFIGURAÇÃO ======================
st.set_page_config(
    page_title="Gestão de Chamados Integrada",
    layout="wide",
    page_icon="🏭",
    initial_sidebar_state="collapsed"
)

if not os.path.exists("fotos_chamados"):
    os.makedirs("fotos_chamados")

DB_PATH = "banco_chamados.db"

# ====================== BANCO DE DADOS ======================
def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS chamados (
            id INTEGER PRIMARY KEY, solicitante TEXT, data_hora_abertura TEXT, setor TEXT,
            equipamento TEXT, prioridade TEXT, descricao TEXT, status TEXT,
            executante TEXT, data_hora_inicio TEXT, data_hora_conclusao TEXT,
            foto_path TEXT, solucao_descricao TEXT, foto_solucao_path TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS equipe (
            id INTEGER PRIMARY KEY, nome TEXT, funcao TEXT, contato TEXT, ativo INTEGER DEFAULT 1)''')
        cursor.execute('CREATE TABLE IF NOT EXISTS setores (id INTEGER PRIMARY KEY, setor TEXT UNIQUE)')
        cursor.execute('''CREATE TABLE IF NOT EXISTS equipamentos (
            id INTEGER PRIMARY KEY, nome TEXT, marca TEXT, modelo TEXT,
            ano_aquisicao INTEGER, numero_patrimonio TEXT, setor TEXT,
            sazonalidade_meses INTEGER, ultima_preventiva TEXT, proxima_preventiva TEXT)''')
        conn.commit()
        conn.close()
    except Exception as e:
        st.error(f"Erro ao criar tabelas: {e}")

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def migrate_from_excel():
    if os.path.exists("banco_chamados.xlsx"):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM chamados")
        if cursor.fetchone()[0] == 0:
            try:
                df = pd.read_excel("banco_chamados.xlsx")
                df.to_sql("chamados", conn, if_exists="replace", index=False)
                st.success("✅ Chamados migrados do Excel!")
            except Exception as e:
                st.warning(f"Erro na migração: {e}")
        conn.close()

init_db()
migrate_from_excel()

# ====================== FUNÇÕES ======================
def comprimir_imagem(image_bytes, prefixo="chamado", max_size=900, quality=82):
    try:
        img = Image.open(image_bytes)
        img = ImageOps.exif_transpose(img)
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            new_size = tuple(int(dim * ratio) for dim in img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        output_path = f"fotos_chamados/{prefixo}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
        img.save(output_path, "JPEG", quality=quality, optimize=True)
        return output_path
    except Exception as e:
        st.error(f"Erro ao comprimir imagem: {e}")
        return None

def carregar_dados():
    try:
        conn = get_db_connection()
        if not conn:
            return []
        df = pd.read_sql("SELECT * FROM chamados", conn)
        conn.close()
        if not df.empty:
            for col in ["data_hora_abertura", "data_hora_inicio", "data_hora_conclusao"]:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], errors='coerce')
        return df.to_dict(orient="records")
    except Exception as e:
        st.error(f"Erro ao carregar chamados: {e}")
        return []

def salvar_dados(chamados_list):
    try:
        conn = get_db_connection()
        if not conn:
            return False
        df = pd.DataFrame(chamados_list)
        for col in ["data_hora_abertura", "data_hora_inicio", "data_hora_conclusao"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S')
        df = df.where(pd.notnull(df), None)
        df.to_sql("chamados", conn, if_exists="replace", index=False)
        conn.close()
        return True
    except Exception as e:
        st.error(f"Erro ao salvar dados: {e}")
        return False

def carregar_equipe():
    try:
        conn = get_db_connection()
        if not conn: return pd.DataFrame()
        df = pd.read_sql("SELECT * FROM equipe", conn)
        conn.close()
        return df
    except:
        return pd.DataFrame()

def salvar_equipe(df):
    try:
        conn = get_db_connection()
        if conn:
            df.to_sql("equipe", conn, if_exists="replace", index=False)
            conn.close()
    except Exception as e:
        st.error(f"Erro ao salvar equipe: {e}")

def carregar_setores():
    try:
        conn = get_db_connection()
        if not conn:
            return ["Fracionamento 1", "Fracionamento 2", "Mistura 1", "Mistura 2", "Mistura 3", "Mistura 4",
                    "Envase 1", "Envase 2", "RH 1", "Laboratório", "Outros"]
        df = pd.read_sql("SELECT setor FROM setores", conn)
        conn.close()
        return df["setor"].tolist() if not df.empty else ["Fracionamento 1", "Fracionamento 2", "Mistura 1", "Mistura 2", "Mistura 3", "Mistura 4",
                    "Envase 1", "Envase 2", "RH 1", "Laboratório", "Outros"]
    except:
        return ["Fracionamento 1", "Fracionamento 2", "Mistura 1", "Mistura 2", "Mistura 3", "Mistura 4",
                "Envase 1", "Envase 2", "RH 1", "Laboratório", "Outros"]

def salvar_setores(lista):
    try:
        conn = get_db_connection()
        if conn:
            pd.DataFrame({"setor": lista}).to_sql("setores", conn, if_exists="replace", index=False)
            conn.close()
    except Exception as e:
        st.error(f"Erro ao salvar setores: {e}")

def carregar_equipamentos():
    try:
        conn = get_db_connection()
        if not conn: return []
        df = pd.read_sql("SELECT * FROM equipamentos", conn)
        conn.close()
        return df.to_dict(orient="records")
    except:
        return []

def salvar_equipamentos(lista):
    try:
        conn = get_db_connection()
        if conn:
            pd.DataFrame(lista).to_sql("equipamentos", conn, if_exists="replace", index=False)
            conn.close()
    except Exception as e:
        st.error(f"Erro ao salvar equipamentos: {e}")

def nome_equipamento(eq):
    try:
        return eq.get("nome") or eq.get("Equipamento") or "N/A"
    except:
        return "N/A"

# ====================== INICIALIZAÇÃO ======================
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

# ====================== CABEÇALHO ======================
st.title("🏭 Gestão de Chamados e Manutenção")
st.sidebar.header("🔑 Controle de Acesso")
perfil = st.sidebar.selectbox("Escolha seu Perfil:",
                             ["👤 Usuário Comum", "🛠️ Equipe de Manutenção", "👨‍💼 Administrador"])

# ====================== USUÁRIO COMUM ======================
if perfil == "👤 Usuário Comum":
    aba_novo, aba_historico = st.tabs(["🚀 Nova Solicitação", "📊 Histórico e Indicadores"])
    
    with aba_novo:
        st.success("💡 Solicite seu chamado rapidamente")
        st.markdown("### 📸 Adicionar Foto (Opcional)")
        foto_opcao = st.radio("Como deseja adicionar a foto?",
                            ["Sem foto", "Tirar foto agora", "Escolher da galeria"],
                            horizontal=True, key="foto_novo")
        
        foto_path = None
        if foto_opcao == "Tirar foto agora":
            foto = st.camera_input("Capturar Foto", key="cam_novo")
            if foto: foto_path = comprimir_imagem(foto, "abertura")
        elif foto_opcao == "Escolher da galeria":
            arquivo = st.file_uploader("Selecione imagem", type=["jpg","jpeg","png"], key="up_novo")
            if arquivo: foto_path = comprimir_imagem(arquivo, "abertura")
        
        with st.form("novo_chamado", clear_on_submit=True):
            nome = st.text_input("Solicitante *", placeholder="Seu nome completo")
            col1, col2 = st.columns(2)
            with col1:
                setor = st.selectbox("Setor / Área *", st.session_state.setores or ["Outros"])
            with col2:
                eq_options = [nome_equipamento(eq) for eq in st.session_state.equipamentos] + ["N/A"]
                equipamento = st.selectbox("Equipamento", eq_options)
            
            prioridade = st.selectbox("Prioridade *", list(PRIORIDADES.keys()))
            descricao = st.text_area("Descrição do Problema *", height=120)
            
            if foto_path: st.info("✅ Foto pronta para envio!")
            
            if st.form_submit_button("🚀 ENVIAR SOLICITAÇÃO", use_container_width=True, type="primary"):
                try:
                    if nome and descricao and setor:
                        ids = [c.get("id", 0) for c in st.session_state.chamados]
                        novo_id = max(ids) + 1 if ids else 1
                        
                        st.session_state.chamados.append({
                            "id": novo_id,
                            "solicitante": nome,
                            "data_hora_abertura": datetime.now().isoformat(),
                            "setor": setor,
                            "equipamento": equipamento,
                            "prioridade": prioridade,
                            "descricao": descricao,
                            "status": "Aberto",
                            "executante": "",
                            "data_hora_inicio": None,
                            "data_hora_conclusao": None,
                            "foto_path": foto_path,
                            "solucao_descricao": "",
                            "foto_solucao_path": None
                        })
                        if salvar_dados(st.session_state.chamados):
                            st.success(f"✅ Chamado Nº **{novo_id}** registrado com sucesso!")
                            st.balloons()
                            st.rerun()
                    else:
                        st.error("❌ Preencha os campos obrigatórios.")
                except Exception as e:
                    st.error(f"Erro ao registrar chamado: {e}")

    with aba_historico:
        try:
            if st.session_state.chamados:
                df = pd.DataFrame(st.session_state.chamados)
                total = len(df)
                concluidos = len(df[df["status"] == "Concluído"])
                m1, m2, m3 = st.columns(3)
                m1.metric("Total", total)
                m2.metric("Concluídos", concluidos)
                m3.metric("Pendentes", total - concluidos, delta_color="inverse")
                
                col1, col2 = st.columns(2)
                with col1:
                    df_visao = df.copy()
                    df_visao["Visão"] = df_visao["status"].apply(lambda x: "Solucionado" if x == "Concluído" else "Pendente")
                    st.plotly_chart(px.pie(df_visao, names="Visão", color="Visão", hole=0.4), use_container_width=True)
                with col2:
                    st.plotly_chart(px.histogram(df, x="prioridade", color="status", barmode="group"), use_container_width=True)
                
                st.dataframe(df.drop(columns=["foto_path", "foto_solucao_path"], errors="ignore"),
                            use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Erro ao carregar histórico: {e}")

# ====================== EQUIPE DE MANUTENÇÃO ======================
elif perfil == "🛠️ Equipe de Manutenção":
    # Recarregar dados
    st.session_state.chamados = carregar_dados()
    st.session_state.equipe = carregar_equipe()

    st.header("🛠️ Fila de Manutenção + Preventivas")
    
    st.subheader("⚠️ Alertas de Manutenção Preventiva")
    hoje = datetime.now().date()
    for eq in st.session_state.equipamentos:
        if eq.get("proxima_preventiva"):
            try:
                prox = datetime.fromisoformat(eq["proxima_preventiva"]).date()
                if prox <= hoje + timedelta(days=30):
                    st.warning(f"**{nome_equipamento(eq)}** - Preventiva próxima ou vencida ({prox.strftime('%d/%m/%Y')})")
            except:
                pass

    # Filtros
    col1, col2, col3 = st.columns([3, 2, 2])
    with col1:
        tecnicos_ativos = ["Todos"] + st.session_state.equipe[st.session_state.equipe["ativo"] == 1]["nome"].tolist()
        filtro_tecnico = st.selectbox("Filtrar por Técnico", tecnicos_ativos)
    with col2:
        filtro_status = st.multiselect("Status", ["Aberto", "Em Atendimento"], default=["Aberto", "Em Atendimento"])
    with col3:
        filtro_setor = st.multiselect("Setor", st.session_state.setores)

    st_autorefresh(interval=3000, key="refresh_maint")

    # Alerta Sonoro
    if any(c.get("status") == "Aberto" for c in st.session_state.chamados):
        if (datetime.now() - st.session_state.ultimo_alarme).total_seconds() >= 60:
            st.success("🛎️ Há chamados abertos aguardando!")
            st.audio("https://www.soundjay.com/buttons/beep-07.mp3", autoplay=True)
            st.session_state.ultimo_alarme = datetime.now()

    # ==================== FILTRAGEM E EXIBIÇÃO ====================
    try:
        # Filtragem segura
        ativos = [c for c in st.session_state.chamados if c.get("status") in filtro_status]
        
        if filtro_tecnico != "Todos":
            ativos = [c for c in ativos if c.get("executante") == filtro_tecnico]
        if filtro_setor:
            ativos = [c for c in ativos if c.get("setor") in filtro_setor]

        def ordem(c):
            try:
                prio = PRIORIDADES.get(c.get("prioridade"), 999)
                dt = c.get("data_hora_abertura")
                if isinstance(dt, str):
                    dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
                sla = (dt + timedelta(minutes=SLA_TEMPO.get(c.get("prioridade"), 1440)) - datetime.now()).total_seconds()
                return (prio, sla)
            except:
                return (999, 0)

        for cham in sorted(ativos, key=ordem):
            with st.container(border=True):
                # Data de abertura segura
                abertura = cham.get("data_hora_abertura")
                if isinstance(abertura, str):
                    try:
                        abertura_dt = datetime.fromisoformat(abertura.replace("Z", "+00:00"))
                    except:
                        abertura_dt = datetime.now()
                elif isinstance(abertura, datetime):
                    abertura_dt = abertura
                else:
                    abertura_dt = datetime.now()
                
                prazo = abertura_dt + timedelta(minutes=SLA_TEMPO.get(cham.get("prioridade"), 1440))
                min_restantes = int((prazo - datetime.now()).total_seconds() / 60)
                cor = "red" if min_restantes < 0 else "orange" if min_restantes < 20 else "green"
                
                st.markdown(f"**OS Nº {cham.get('id', 'N/A')}** — :{cor}[{cham.get('prioridade', 'Média')}]")
                st.write(f"**Setor:** {cham.get('setor', 'N/A')} | **Equipamento:** {cham.get('equipamento', 'N/A')}")
                st.write(f"**Solicitante:** {cham.get('solicitante', 'N/A')}")
                st.write(f"**Descrição:** {cham.get('descricao', '')}")
                
                # Foto de abertura
                foto_path = cham.get("foto_path")
                if foto_path and isinstance(foto_path, str) and os.path.exists(foto_path):
                    st.image(foto_path, use_container_width=True)
                
                if cham.get("status") == "Aberto":
                    nome_tec = st.selectbox("Selecionar Técnico:", tecnicos_ativos[1:], key=f"t_{cham.get('id')}")
                    if st.button("🚀 Iniciar Manutenção", key=f"b_in_{cham.get('id')}", use_container_width=True):
                        if nome_tec:
                            cham["status"] = "Em Atendimento"
                            cham["executante"] = nome_tec
                            cham["data_hora_inicio"] = datetime.now().isoformat()
                            salvar_dados(st.session_state.chamados)
                            st.rerun()
                else:
                    st.caption(f"👨‍🔧 Técnico: **{cham.get('executante', 'Não atribuído')}**")
                    opcao_sol = st.radio("Foto da Solução:", ["Sem foto", "Tirar foto", "Galeria"],
                                       horizontal=True, key=f"sol_{cham.get('id')}")
                    foto_sol = None
                    if opcao_sol == "Tirar foto":
                        f = st.camera_input("Capturar Solução", key=f"cam_sol_{cham.get('id')}")
                        if f: foto_sol = comprimir_imagem(f, "solucao")
                    elif opcao_sol == "Galeria":
                        f = st.file_uploader("Selecionar foto", type=["jpg","jpeg","png"], key=f"up_sol_{cham.get('id')}")
                        if f: foto_sol = comprimir_imagem(f, "solucao")
                    
                    solucao_txt = st.text_area("Descreva a solução *", key=f"txt_{cham.get('id')}")
                    
                    if st.button("✅ Concluir Chamado", key=f"b_fim_{cham.get('id')}", type="primary"):
                        if solucao_txt and solucao_txt.strip():
                            cham["status"] = "Concluído"
                            cham["solucao_descricao"] = solucao_txt
                            cham["foto_solucao_path"] = foto_sol
                            cham["data_hora_conclusao"] = datetime.now().isoformat()
                            salvar_dados(st.session_state.chamados)
                            st.success("Chamado concluído!")
                            st.rerun()
                        else:
                            st.error("Descreva a solução.")
    except Exception as e:
        st.error(f"Erro ao exibir fila de manutenção: {e}")

# ====================== ADMINISTRADOR ======================
elif perfil == "👨‍💼 Administrador":
    if not st.session_state.admin_logado:
        with st.form("login_admin"):
            usuario_input = st.text_input("Usuário:", placeholder="Leandro Coelho")
            senha_input = st.text_input("Senha:", type="password", placeholder="123")
            if st.form_submit_button("Efetuar Login"):
                if usuario_input.strip() == "Leandro Coelho" and senha_input == "123":
                    st.session_state.admin_logado = True
                    st.rerun()
                else:
                    st.error("❌ Usuário ou senha incorretos.")
    else:
        st.success("🔓 Bem-vindo, Administrador!")
        if st.button("🚪 Sair"):
            st.session_state.admin_logado = False
            st.rerun()
        
        df = pd.DataFrame(st.session_state.chamados)
        
        tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs([
            "📊 Dashboard Geral", "📈 Análise Gráfica", "📊 Análise de Tempo",
            "🛠️ Ocorrências por Equipamento", "👥 Cadastro de Equipe",
            "🏭 Cadastro de Setores", "🔧 Cadastro de Equipamentos",
            "🖼️ Galeria de Fotos", "📥 Importar Planilha"
        ])
        
        with tab1:
            if not df.empty:
                df = df.copy()
                df['data_hora_abertura'] = pd.to_datetime(df['data_hora_abertura'], errors='coerce')
                colf1, colf2, colf3, colf4 = st.columns(4)
                with colf1: filtro_setor = st.multiselect("Setor", sorted(df["setor"].dropna().unique()), default=[])
                with colf2: filtro_prioridade = st.multiselect("Prioridade", df["prioridade"].dropna().unique(), default=[])
                with colf3: filtro_status = st.multiselect("Status", ["Aberto", "Em Atendimento", "Concluído"], default=[])
                with colf4: filtro_tecnico = st.multiselect("Técnico", [t for t in df["executante"].dropna().unique() if t], default=[])
                
                df_filtrado = df.copy()
                if filtro_setor: df_filtrado = df_filtrado[df_filtrado["setor"].isin(filtro_setor)]
                if filtro_prioridade: df_filtrado = df_filtrado[df_filtrado["prioridade"].isin(filtro_prioridade)]
                if filtro_status: df_filtrado = df_filtrado[df_filtrado["status"].isin(filtro_status)]
                if filtro_tecnico: df_filtrado = df_filtrado[df_filtrado["executante"].isin(filtro_tecnico)]
                
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Total Filtrado", len(df_filtrado))
                m2.metric("Abertos", len(df_filtrado[df_filtrado["status"] == "Aberto"]))
                m3.metric("Em Atendimento", len(df_filtrado[df_filtrado["status"] == "Em Atendimento"]))
                m4.metric("Concluídos", len(df_filtrado[df_filtrado["status"] == "Concluído"]))
                st.dataframe(df_filtrado.drop(columns=["foto_path", "foto_solucao_path"], errors="ignore"), use_container_width=True)
        
        with tab2:
            if not df.empty:
                col1, col2 = st.columns(2)
                with col1: st.plotly_chart(px.pie(df, names="prioridade", title="Distribuição por Prioridade"), use_container_width=True)
                with col2: st.plotly_chart(px.bar(df["setor"].value_counts().reset_index(), x="setor", y="count", title="Chamados por Setor"), use_container_width=True)
        
        with tab3:
            st.subheader("📊 Análise de Tempo de Execução")
            df_analise = df[df["status"] == "Concluído"].copy()
            if not df_analise.empty:
                df_analise['data_hora_inicio'] = pd.to_datetime(df_analise['data_hora_inicio'], errors='coerce')
                df_analise['data_hora_conclusao'] = pd.to_datetime(df_analise['data_hora_conclusao'], errors='coerce')
                df_analise["tempo_minutos"] = (df_analise["data_hora_conclusao"] - df_analise["data_hora_inicio"]).dt.total_seconds() / 60
                tempo_tecnico = df_analise.groupby("executante")["tempo_minutos"].mean().round(1).reset_index()
                tempo_tecnico.columns = ["Técnico", "Tempo Médio (min)"]
                st.plotly_chart(px.bar(tempo_tecnico, x="Técnico", y="Tempo Médio (min)"), use_container_width=True)
                st.plotly_chart(px.bar(df_analise.groupby("prioridade")["tempo_minutos"].mean().round(1).reset_index(), x="prioridade", y="tempo_minutos"), use_container_width=True)
        
        with tab4:
            if not df.empty:
                df_equip = df.groupby("equipamento").size().reset_index(name="Total")
                st.dataframe(df_equip.sort_values("Total", ascending=False), use_container_width=True)
        
        with tab5:
            st.subheader("👥 Cadastro da Equipe de Manutenção")
            with st.form("cadastro_equipe"):
                nome = st.text_input("Nome Completo")
                funcao = st.selectbox("Função", ["Técnico", "Líder Técnico", "Elétrico", "Mecânico", "Auxiliar"])
                contato = st.text_input("Contato (Telefone/WhatsApp)")
                if st.form_submit_button("Cadastrar Membro"):
                    if nome:
                        novo = {"nome": nome, "funcao": funcao, "contato": contato, "ativo": 1}
                        st.session_state.equipe = pd.concat([st.session_state.equipe, pd.DataFrame([novo])], ignore_index=True)
                        salvar_equipe(st.session_state.equipe)
                        st.success(f"{nome} cadastrado!")
                        st.rerun()
            if not st.session_state.equipe.empty:
                for i, row in st.session_state.equipe.iterrows():
                    col1, col2 = st.columns([5, 1])
                    with col1:
                        st.write(f"**{row['nome']}** — {row['funcao']} | {row['contato']}")
                    with col2:
                        if st.button("🗑️ Excluir", key=f"del_eq_{i}"):
                            st.session_state.equipe = st.session_state.equipe.drop(i).reset_index(drop=True)
                            salvar_equipe(st.session_state.equipe)
                            st.rerun()
            else:
                st.info("Nenhum membro cadastrado.")
        
        with tab6:
            st.subheader("🏭 Cadastro de Setores / Áreas")
            busca_setor = st.text_input("🔍 Buscar setor", key="busca_setor")
            
            with st.form("cadastro_setor"):
                if st.session_state.edit_setor:
                    novo_setor = st.text_input("Nome do Setor", value=st.session_state.edit_setor)
                else:
                    novo_setor = st.text_input("Nome do Setor / Área")
                if st.form_submit_button("💾 Salvar" if st.session_state.edit_setor else "Adicionar Setor"):
                    if novo_setor.strip():
                        if st.session_state.edit_setor:
                            idx = st.session_state.setores.index(st.session_state.edit_setor)
                            st.session_state.setores[idx] = novo_setor.strip()
                            st.session_state.edit_setor = None
                        else:
                            if novo_setor.strip() not in st.session_state.setores:
                                st.session_state.setores.append(novo_setor.strip())
                        salvar_setores(st.session_state.setores)
                        st.rerun()
            
            setores_filtrados = [s for s in st.session_state.setores if busca_setor.lower() in s.lower()] if busca_setor else st.session_state.setores
            for i, setor in enumerate(setores_filtrados):
                col1, col2, col3 = st.columns([6, 1, 1])
                with col1: st.write(f"• {setor}")
                with col2:
                    if st.button("✏️ Editar", key=f"edit_s_{i}"):
                        st.session_state.edit_setor = setor
                        st.rerun()
                with col3:
                    if st.button("🗑️ Excluir", key=f"del_s_{i}"):
                        st.session_state.setores.remove(setor)
                        salvar_setores(st.session_state.setores)
                        st.rerun()
        
        with tab7:
            st.subheader("🔧 Cadastro de Equipamentos")
            busca_equip = st.text_input("🔍 Buscar equipamento", key="busca_equip")
            
            with st.form("cadastro_equipamento"):
                col1, col2 = st.columns(2)
                with col1:
                    nome = st.text_input("Nome do Equipamento *", value=st.session_state.edit_equip.get("nome", "") if st.session_state.edit_equip else "")
                    marca = st.text_input("Marca", value=st.session_state.edit_equip.get("marca", "") if st.session_state.edit_equip else "")
                    modelo = st.text_input("Modelo", value=st.session_state.edit_equip.get("modelo", "") if st.session_state.edit_equip else "")
                    patrimonio = st.text_input("Número Patrimônio *", value=st.session_state.edit_equip.get("numero_patrimonio", "") if st.session_state.edit_equip else "")
                with col2:
                    setor_default = st.session_state.edit_equip.get("setor") if st.session_state.edit_equip else (st.session_state.setores[0] if st.session_state.setores else "")
                    setor_idx = st.session_state.setores.index(setor_default) if setor_default in st.session_state.setores else 0
                    setor = st.selectbox("Setor", st.session_state.setores, index=setor_idx)
                    ano = st.number_input("Ano de Aquisição", min_value=1900, max_value=datetime.now().year,
                                        value=st.session_state.edit_equip.get("ano_aquisicao", datetime.now().year) if st.session_state.edit_equip else datetime.now().year)
                    sazonalidade = st.number_input("Sazonalidade Preventiva (meses)", min_value=1, max_value=60,
                                                 value=st.session_state.edit_equip.get("sazonalidade_meses", 6) if st.session_state.edit_equip else 6)
                
                if st.form_submit_button("💾 Salvar" if st.session_state.edit_equip else "Cadastrar Equipamento"):
                    if nome and patrimonio:
                        novo = {
                            "id": st.session_state.edit_equip.get("id", len(st.session_state.equipamentos) + 1) if st.session_state.edit_equip else len(st.session_state.equipamentos) + 1,
                            "nome": nome,
                            "marca": marca,
                            "modelo": modelo,
                            "ano_aquisicao": ano,
                            "numero_patrimonio": patrimonio,
                            "setor": setor,
                            "sazonalidade_meses": sazonalidade,
                            "ultima_preventiva": st.session_state.edit_equip.get("ultima_preventiva", datetime.now().date().isoformat()) if st.session_state.edit_equip else datetime.now().date().isoformat(),
                            "proxima_preventiva": (datetime.now() + timedelta(days=sazonalidade*30)).date().isoformat()
                        }
                        if st.session_state.edit_equip:
                            for idx, eq in enumerate(st.session_state.equipamentos):
                                if eq.get("id") == novo["id"]:
                                    st.session_state.equipamentos[idx] = novo
                                    break
                            st.session_state.edit_equip = None
                        else:
                            st.session_state.equipamentos.append(novo)
                        salvar_equipamentos(st.session_state.equipamentos)
                        st.rerun()
            
            equipamentos_filtrados = [eq for eq in st.session_state.equipamentos if busca_equip.lower() in nome_equipamento(eq).lower() or busca_equip.lower() in str(eq.get("numero_patrimonio", "")).lower()] if busca_equip else st.session_state.equipamentos
            
            for i, eq in enumerate(equipamentos_filtrados):
                nome_eq = nome_equipamento(eq)
                with st.expander(f"{nome_eq} - Pat: {eq.get('numero_patrimonio', 'N/A')}"):
                    st.write(eq)
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("✏️ Editar", key=f"edit_eq_{i}"):
                            st.session_state.edit_equip = eq.copy()
                            st.rerun()
                    with col2:
                        if st.button("🗑️ Excluir", key=f"del_eqp_{i}"):
                            original_idx = next((idx for idx, x in enumerate(st.session_state.equipamentos) if x.get("id") == eq.get("id")), None)
                            if original_idx is not None:
                                st.session_state.equipamentos.pop(original_idx)
                                salvar_equipamentos(st.session_state.equipamentos)
                                st.rerun()
        
        with tab8:
            st.subheader("🖼️ Galeria de Fotos")
            com_foto = [c for c in st.session_state.chamados if c.get("foto_path") and os.path.exists(str(c.get("foto_path")))]
            if com_foto:
                cols = st.columns(3)
                for i, cham in enumerate(com_foto):
                    with cols[i % 3]:
                        st.image(cham["foto_path"], use_container_width=True)
                        st.caption(f"OS {cham['id']} - {cham.get('setor')}")
            else:
                st.info("Nenhuma foto registrada ainda.")
        
        with tab9:
            st.subheader("📥 Importar Ordens de Serviço")
            uploaded_file = st.file_uploader("Selecione o arquivo MANUTENÇÃO CRN - 2026.xlsx", type=["xlsx"])
            if st.button("🔄 Importar Dados da Planilha"):
                if uploaded_file:
                    try:
                        df_import = pd.read_excel(uploaded_file, sheet_name="Planilha1")
                        st.success(f"✅ {len(df_import)} linhas importadas!")
                        st.dataframe(df_import.head())
                    except Exception as e:
                        st.error(f"Erro: {e}")
                else:
                    st.warning("Selecione o arquivo.")

st.caption("**Sistema v1.6** - By Leandro Coelho")