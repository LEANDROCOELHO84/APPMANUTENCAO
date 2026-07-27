import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from PIL import Image, ImageOps
import plotly.express as px
import hashlib
from streamlit_autorefresh import st_autorefresh

# ====================== LOGGING ======================
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

def setup_logger():
    logger = logging.getLogger("chamados_app")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(funcName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Arquivo rotativo (máx 2 MB, 5 backups)
    fh = RotatingFileHandler(
        LOG_DIR / "app_errors.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Também no console (útil no Streamlit Cloud logs)
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    return logger

logger = setup_logger()

def log_error(msg: str, exc: Exception | None = None):
    if exc:
        logger.exception("%s | %s", msg, exc)
    else:
        logger.error(msg)

# ====================== TEMA ======================
try:
    from theme import aplicar_tema, header, badge_prioridade, badge_status, CORES_PRIORIDADE, CORES_STATUS
except ImportError:
    st.warning("Arquivo theme.py não encontrado. Usando tema padrão.")
    def aplicar_tema(): pass
    def header(title, subtitle="", icon="🏭"):
        st.title(f"{icon} {title}")
        if subtitle:
            st.markdown(f"_{subtitle}_")
    def badge_prioridade(prio):
        return f"**{prio}**"
    def badge_status(status):
        return f"**{status}**"
    CORES_PRIORIDADE = {}
    CORES_STATUS = {}

# ====================== CONFIGURAÇÃO ======================
st.set_page_config(
    page_title="Gestão de Chamados Integrada",
    layout="wide",
    page_icon="🏭",
    initial_sidebar_state="collapsed",
)
aplicar_tema()

Path("fotos_chamados").mkdir(exist_ok=True)

# ====================== CONEXÃO HÍBRIDA (LOCAL + SQLITE CLOUD) ======================
def get_connection_string() -> str | None:
    """
    Retorna a URL do SQLite Cloud se configurada, senão None (modo local).

    Aceita:
      - SQLITECLOUD_URL no TOPO do secrets.toml  (recomendado)
      - SQLITECLOUD_URL dentro de [admin]        (erro comum de TOML)
      - variável de ambiente SQLITECLOUD_URL
    """
    # 1) Topo do secrets
    try:
        url = st.secrets.get("SQLITECLOUD_URL")
        if url and str(url).strip():
            return str(url).strip()
    except Exception:
        pass

    # 2) Dentro de [admin] (chave colocada sob a seção por engano no TOML)
    try:
        admin = st.secrets.get("admin", {})
        if admin is not None:
            url = admin.get("SQLITECLOUD_URL") if hasattr(admin, "get") else None
            if url and str(url).strip():
                logger.warning(
                    "SQLITECLOUD_URL lida de [admin]. Mova a chave para o TOPO do secrets.toml."
                )
                return str(url).strip()
    except Exception:
        pass

    try:
        url = st.secrets["admin"]["SQLITECLOUD_URL"]
        if url and str(url).strip():
            logger.warning(
                "SQLITECLOUD_URL lida de [admin]. Mova a chave para o TOPO do secrets.toml."
            )
            return str(url).strip()
    except Exception:
        pass

    # 3) Variável de ambiente
    url = os.getenv("SQLITECLOUD_URL")
    if url and url.strip():
        return url.strip()

    logger.info("SQLITECLOUD_URL não encontrada. Usando apenas banco local.")
    return None


LOCAL_DB_PATH = "banco_chamados.db"


def is_cloud() -> bool:
    return get_connection_string() is not None


def get_local_connection():
    import sqlite3
    return sqlite3.connect(LOCAL_DB_PATH, check_same_thread=False)


def get_cloud_connection():
    cloud_url = get_connection_string()
    if not cloud_url:
        return None
    try:
        import sqlitecloud
        conn = sqlitecloud.connect(cloud_url)
        return conn
    except ImportError as e:
        log_error("Pacote sqlitecloud não instalado. Rode: pip install sqlitecloud", e)
        return None
    except Exception as e:
        log_error(f"Falha ao conectar no SQLite Cloud | url={cloud_url[:60]}...", e)
        return None


def get_db_connection():
    """
    Conexão principal de leitura/escrita.
    Prioridade: Cloud (se configurado) → Local.
    """
    cloud = get_cloud_connection()
    if cloud is not None:
        return cloud
    return get_local_connection()


def _ensure_schema(conn):
    """Cria tabelas se não existirem em uma conexão qualquer."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chamados (
            id INTEGER PRIMARY KEY,
            solicitante TEXT,
            data_hora_abertura TEXT,
            setor TEXT,
            equipamento TEXT,
            prioridade TEXT,
            descricao TEXT,
            status TEXT,
            executante TEXT,
            data_hora_inicio TEXT,
            data_hora_conclusao TEXT,
            foto_path TEXT,
            solucao_descricao TEXT,
            foto_solucao_path TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS equipe (
            id INTEGER PRIMARY KEY,
            nome TEXT,
            funcao TEXT,
            contato TEXT,
            ativo INTEGER DEFAULT 1
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS setores (
            id INTEGER PRIMARY KEY,
            setor TEXT UNIQUE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS equipamentos (
            id INTEGER PRIMARY KEY,
            nome TEXT,
            marca TEXT,
            modelo TEXT,
            ano_aquisicao INTEGER,
            numero_patrimonio TEXT,
            setor TEXT,
            sazonalidade_meses INTEGER,
            ultima_preventiva TEXT,
            proxima_preventiva TEXT
        )
    """)
    conn.commit()


def sync_local_to_cloud() -> tuple[bool, str]:
    """
    Copia TODAS as tabelas do banco local → SQLite Cloud.
    Útil para popular o cloud com dados que já existem no PC.

    Não usa df.to_sql(..., if_exists="append"): o driver sqlitecloud faz o
    pandas tentar CREATE TABLE mesmo com append, gerando
    "table already exists". Fluxo: schema garantido + DELETE + INSERT.
    """
    if not is_cloud():
        return False, "SQLITECLOUD_URL não configurada nos Secrets."

    try:
        import sqlite3
        local = sqlite3.connect(LOCAL_DB_PATH, check_same_thread=False)
        _ensure_schema(local)

        cloud = get_cloud_connection()
        if cloud is None:
            local.close()
            return False, "Não foi possível conectar no SQLite Cloud."
        _ensure_schema(cloud)

        tabelas = ["chamados", "equipe", "setores", "equipamentos"]
        resumo = []

        def _safe_cell(v):
            """Normaliza célula para INSERT (None / string de data)."""
            if v is None:
                return None
            try:
                if pd.isna(v):
                    return None
            except (TypeError, ValueError):
                pass
            if hasattr(v, "strftime"):
                try:
                    return v.strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError, OverflowError):
                    return None
            return v

        for tabela in tabelas:
            df = pd.read_sql(f"SELECT * FROM {tabela}", local)
            cloud_cur = cloud.cursor()
            # Limpa a tabela no cloud (schema já existe via _ensure_schema)
            cloud_cur.execute(f"DELETE FROM {tabela}")
            cloud.commit()

            if not df.empty:
                df = df.where(pd.notnull(df), None)
                for col in df.columns:
                    if (
                        "data" in col.lower()
                        or "hora" in col.lower()
                        or "preventiva" in col.lower()
                    ):
                        df[col] = df[col].apply(_safe_cell)

                cols = list(df.columns)
                placeholders = ",".join(["?"] * len(cols))
                col_names = ",".join(cols)
                sql = f"INSERT INTO {tabela} ({col_names}) VALUES ({placeholders})"
                rows = [
                    tuple(_safe_cell(v) for v in row)
                    for row in df.itertuples(index=False, name=None)
                ]
                cloud_cur.executemany(sql, rows)
                cloud.commit()

            resumo.append(f"{tabela}: {len(df)} registros")

        local.close()
        cloud.close()
        msg = "Sincronização Local → Cloud OK | " + " | ".join(resumo)
        logger.info(msg)
        return True, msg
    except Exception as e:
        log_error("sync_local_to_cloud falhou", e)
        return False, f"Erro na sincronização: {e}"


def dual_write_execute(sql: str, params: tuple = ()):
    """
    Executa o mesmo SQL no local E no cloud (se configurado).
    Garante que os dois bancos fiquem alinhados.
    """
    erros = []

    # 1) Local (sempre)
    try:
        local = get_local_connection()
        _ensure_schema(local)
        local.execute(sql, params)
        local.commit()
        local.close()
    except Exception as e:
        log_error(f"dual_write LOCAL falhou: {sql[:80]}", e)
        erros.append(f"local: {e}")

    # 2) Cloud (se houver)
    if is_cloud():
        try:
            cloud = get_cloud_connection()
            if cloud is not None:
                _ensure_schema(cloud)
                cloud.execute(sql, params)
                cloud.commit()
                cloud.close()
        except Exception as e:
            log_error(f"dual_write CLOUD falhou: {sql[:80]}", e)
            erros.append(f"cloud: {e}")

    return len(erros) == 0, erros


# ====================== BANCO DE DADOS ======================
def init_db():
    """Cria tabelas no local e no cloud (se configurado)."""
    cloud_ok = False
    cloud_msg = "não configurado"
    try:
        # Local sempre
        local = get_local_connection()
        _ensure_schema(local)
        local.close()

        url = get_connection_string()
        if url:
            cloud = get_cloud_connection()
            if cloud is not None:
                try:
                    _ensure_schema(cloud)
                    # Teste simples de leitura
                    cur = cloud.cursor()
                    cur.execute("SELECT COUNT(*) FROM chamados")
                    cur.fetchone()
                    cloud.close()
                    cloud_ok = True
                    cloud_msg = "conectado OK"
                except Exception as e:
                    cloud_msg = f"conectado mas schema/query falhou: {e}"
                    log_error("init_db cloud schema/query", e)
                    try:
                        cloud.close()
                    except Exception:
                        pass
            else:
                cloud_msg = "URL encontrada mas conexão falhou (veja log)"
        else:
            cloud_msg = "SQLITECLOUD_URL ausente nos secrets"

        modo = "local+cloud" if cloud_ok else "local"
        logger.info("init_db OK | modo=%s | cloud=%s", modo, cloud_msg)

        # Guarda status para a UI
        if "db_status" not in st.session_state:
            st.session_state.db_status = {
                "modo": modo,
                "cloud_ok": cloud_ok,
                "cloud_msg": cloud_msg,
            }
        else:
            st.session_state.db_status = {
                "modo": modo,
                "cloud_ok": cloud_ok,
                "cloud_msg": cloud_msg,
            }
    except Exception as e:
        log_error("init_db falhou", e)
        st.error(f"Erro ao inicializar banco: {e}")


def _normalize_datetime_cols(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["data_hora_abertura", "data_hora_inicio", "data_hora_conclusao"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def carregar_dados() -> list[dict]:
    try:
        conn = get_db_connection()
        df = pd.read_sql("SELECT * FROM chamados", conn)
        conn.close()
        if df.empty:
            return []
        df = _normalize_datetime_cols(df)
        # Converte NaT / NaN para None para serialização limpa
        records = df.where(pd.notnull(df), None).to_dict(orient="records")
        return records
    except Exception as e:
        log_error("carregar_dados falhou", e)
        st.error(f"Erro ao carregar chamados: {e}")
        return []


def _fmt_data(v):
    """Normaliza datas para string ISO (trata None, NaN, NaT)."""
    if v is None or v == "":
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, datetime):
        try:
            return v.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError, OverflowError):
            return None
    try:
        ts = pd.to_datetime(v, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    s = str(v).strip()
    return s if s and s.lower() not in ("nat", "nan", "none") else None


def _upsert_chamado_em(conn, campos: dict) -> None:
    """Executa INSERT ou UPDATE de um chamado em uma conexão."""
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM chamados WHERE id = ?", (campos["id"],))
    existe = cur.fetchone() is not None

    if existe:
        cur.execute("""
            UPDATE chamados SET
                solicitante=?, data_hora_abertura=?, setor=?, equipamento=?,
                prioridade=?, descricao=?, status=?, executante=?,
                data_hora_inicio=?, data_hora_conclusao=?, foto_path=?,
                solucao_descricao=?, foto_solucao_path=?
            WHERE id=?
        """, (
            campos["solicitante"], campos["data_hora_abertura"], campos["setor"],
            campos["equipamento"], campos["prioridade"], campos["descricao"],
            campos["status"], campos["executante"], campos["data_hora_inicio"],
            campos["data_hora_conclusao"], campos["foto_path"],
            campos["solucao_descricao"], campos["foto_solucao_path"],
            campos["id"],
        ))
    else:
        cur.execute("""
            INSERT INTO chamados (
                id, solicitante, data_hora_abertura, setor, equipamento,
                prioridade, descricao, status, executante,
                data_hora_inicio, data_hora_conclusao, foto_path,
                solucao_descricao, foto_solucao_path
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            campos["id"], campos["solicitante"], campos["data_hora_abertura"],
            campos["setor"], campos["equipamento"], campos["prioridade"],
            campos["descricao"], campos["status"], campos["executante"],
            campos["data_hora_inicio"], campos["data_hora_conclusao"],
            campos["foto_path"], campos["solucao_descricao"],
            campos["foto_solucao_path"],
        ))
    conn.commit()


def salvar_chamado(chamado: dict) -> bool:
    """
    Upsert de um chamado no LOCAL e no CLOUD (dual-write).
    """
    try:
        campos = {
            "id": chamado.get("id"),
            "solicitante": chamado.get("solicitante"),
            "data_hora_abertura": _fmt_data(chamado.get("data_hora_abertura")),
            "setor": chamado.get("setor"),
            "equipamento": chamado.get("equipamento"),
            "prioridade": chamado.get("prioridade"),
            "descricao": chamado.get("descricao"),
            "status": chamado.get("status"),
            "executante": chamado.get("executante") or "",
            "data_hora_inicio": _fmt_data(chamado.get("data_hora_inicio")),
            "data_hora_conclusao": _fmt_data(chamado.get("data_hora_conclusao")),
            "foto_path": chamado.get("foto_path"),
            "solucao_descricao": chamado.get("solucao_descricao") or "",
            "foto_solucao_path": chamado.get("foto_solucao_path"),
        }

        # 1) Local (sempre)
        local = get_local_connection()
        _ensure_schema(local)
        _upsert_chamado_em(local, campos)
        local.close()

        # 2) Cloud (se configurado)
        if is_cloud():
            cloud = get_cloud_connection()
            if cloud is not None:
                _ensure_schema(cloud)
                _upsert_chamado_em(cloud, campos)
                cloud.close()

        logger.info(
            "salvar_chamado OK | id=%s status=%s | dual=%s",
            campos["id"], campos["status"], is_cloud(),
        )
        return True
    except Exception as e:
        log_error(f"salvar_chamado id={chamado.get('id')} falhou", e)
        st.error(f"Erro ao salvar chamado: {e}")
        return False


def salvar_dados(chamados_list: list[dict]) -> bool:
    """
    Salva lista completa de forma segura (um a um com upsert).
    Mantém compatibilidade com o código legado que passa a lista inteira.
    """
    ok = True
    for c in chamados_list:
        if not salvar_chamado(c):
            ok = False
    return ok


def proximo_id_chamado() -> int:
    """Pega o maior ID entre local e cloud para evitar conflito."""
    ids = []
    try:
        local = get_local_connection()
        cur = local.cursor()
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM chamados")
        ids.append(int(cur.fetchone()[0]))
        local.close()
    except Exception as e:
        log_error("proximo_id local falhou", e)
    if is_cloud():
        try:
            cloud = get_cloud_connection()
            if cloud is not None:
                cur = cloud.cursor()
                cur.execute("SELECT COALESCE(MAX(id), 0) FROM chamados")
                ids.append(int(cur.fetchone()[0]))
                cloud.close()
        except Exception as e:
            log_error("proximo_id cloud falhou", e)
    return (max(ids) + 1) if ids else 1


def carregar_equipe() -> pd.DataFrame:
    try:
        conn = get_db_connection()
        df = pd.read_sql("SELECT * FROM equipe", conn)
        conn.close()
        return df
    except Exception as e:
        log_error("carregar_equipe falhou", e)
        return pd.DataFrame(columns=["id", "nome", "funcao", "contato", "ativo"])


def _write_equipe_em(conn, df: pd.DataFrame):
    cur = conn.cursor()
    cur.execute("DELETE FROM equipe")
    for _, row in df.iterrows():
        cur.execute(
            "INSERT INTO equipe (id, nome, funcao, contato, ativo) VALUES (?,?,?,?,?)",
            (
                int(row["id"]) if pd.notnull(row.get("id")) else None,
                row.get("nome"),
                row.get("funcao"),
                row.get("contato"),
                int(row.get("ativo", 1)),
            ),
        )
    conn.commit()


def salvar_equipe(df: pd.DataFrame) -> bool:
    """Salva equipe no local e no cloud."""
    try:
        local = get_local_connection()
        _ensure_schema(local)
        _write_equipe_em(local, df)
        local.close()
        if is_cloud():
            cloud = get_cloud_connection()
            if cloud is not None:
                _ensure_schema(cloud)
                _write_equipe_em(cloud, df)
                cloud.close()
        logger.info("salvar_equipe OK | %d registros | dual=%s", len(df), is_cloud())
        return True
    except Exception as e:
        log_error("salvar_equipe falhou", e)
        st.error(f"Erro ao salvar equipe: {e}")
        return False


def adicionar_membro_equipe(nome: str, funcao: str, contato: str) -> bool:
    try:
        # ID a partir do local
        local = get_local_connection()
        _ensure_schema(local)
        cur = local.cursor()
        cur.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM equipe")
        novo_id = cur.fetchone()[0]
        local.close()

        sql = "INSERT INTO equipe (id, nome, funcao, contato, ativo) VALUES (?,?,?,?,1)"
        params = (novo_id, nome, funcao, contato)

        local = get_local_connection()
        local.execute(sql, params)
        local.commit()
        local.close()

        if is_cloud():
            cloud = get_cloud_connection()
            if cloud is not None:
                _ensure_schema(cloud)
                cloud.execute(sql, params)
                cloud.commit()
                cloud.close()

        logger.info("adicionar_membro_equipe OK | %s", nome)
        return True
    except Exception as e:
        log_error("adicionar_membro_equipe falhou", e)
        st.error(f"Erro ao cadastrar membro: {e}")
        return False


def excluir_membro_equipe(membro_id: int) -> bool:
    try:
        sql = "DELETE FROM equipe WHERE id = ?"
        params = (membro_id,)
        local = get_local_connection()
        local.execute(sql, params)
        local.commit()
        local.close()
        if is_cloud():
            cloud = get_cloud_connection()
            if cloud is not None:
                cloud.execute(sql, params)
                cloud.commit()
                cloud.close()
        return True
    except Exception as e:
        log_error("excluir_membro_equipe falhou", e)
        return False


def carregar_setores() -> list[str]:
    default_setores = [
        "Fracionamento 1", "Fracionamento 2", "Mistura 1", "Mistura 2",
        "Mistura 3", "Mistura 4", "Envase 1", "Envase 2", "RH 1",
        "Laboratório", "Outros",
    ]
    try:
        conn = get_db_connection()
        df = pd.read_sql("SELECT setor FROM setores ORDER BY setor", conn)
        conn.close()
        if df.empty:
            # popula defaults na primeira execução
            salvar_setores(default_setores)
            return default_setores
        return df["setor"].dropna().tolist()
    except Exception as e:
        log_error("carregar_setores falhou", e)
        return default_setores


def _write_setores_em(conn, lista: list[str]):
    cur = conn.cursor()
    cur.execute("DELETE FROM setores")
    for i, s in enumerate(lista, start=1):
        if s and str(s).strip():
            cur.execute(
                "INSERT INTO setores (id, setor) VALUES (?,?)",
                (i, str(s).strip()),
            )
    conn.commit()


def salvar_setores(lista: list[str]) -> bool:
    try:
        local = get_local_connection()
        _ensure_schema(local)
        _write_setores_em(local, lista)
        local.close()
        if is_cloud():
            cloud = get_cloud_connection()
            if cloud is not None:
                _ensure_schema(cloud)
                _write_setores_em(cloud, lista)
                cloud.close()
        logger.info("salvar_setores OK | %d itens | dual=%s", len(lista), is_cloud())
        return True
    except Exception as e:
        log_error("salvar_setores falhou", e)
        st.error(f"Erro ao salvar setores: {e}")
        return False


def carregar_equipamentos() -> list[dict]:
    try:
        conn = get_db_connection()
        df = pd.read_sql("SELECT * FROM equipamentos", conn)
        conn.close()
        if df.empty:
            return []
        return df.where(pd.notnull(df), None).to_dict(orient="records")
    except Exception as e:
        log_error("carregar_equipamentos falhou", e)
        return []


def _upsert_equipamento_em(conn, eq: dict):
    cur = conn.cursor()
    eq_id = eq.get("id")
    cur.execute("SELECT 1 FROM equipamentos WHERE id = ?", (eq_id,))
    existe = cur.fetchone() is not None
    vals = (
        eq.get("nome"),
        eq.get("marca"),
        eq.get("modelo"),
        eq.get("ano_aquisicao"),
        eq.get("numero_patrimonio"),
        eq.get("setor"),
        eq.get("sazonalidade_meses"),
        eq.get("ultima_preventiva"),
        eq.get("proxima_preventiva"),
    )
    if existe:
        cur.execute("""
            UPDATE equipamentos SET
                nome=?, marca=?, modelo=?, ano_aquisicao=?,
                numero_patrimonio=?, setor=?, sazonalidade_meses=?,
                ultima_preventiva=?, proxima_preventiva=?
            WHERE id=?
        """, (*vals, eq_id))
    else:
        cur.execute("""
            INSERT INTO equipamentos (
                id, nome, marca, modelo, ano_aquisicao, numero_patrimonio,
                setor, sazonalidade_meses, ultima_preventiva, proxima_preventiva
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (eq_id, *vals))
    conn.commit()


def salvar_equipamento(eq: dict) -> bool:
    """Upsert de equipamento no local e no cloud."""
    try:
        local = get_local_connection()
        _ensure_schema(local)
        _upsert_equipamento_em(local, eq)
        local.close()
        if is_cloud():
            cloud = get_cloud_connection()
            if cloud is not None:
                _ensure_schema(cloud)
                _upsert_equipamento_em(cloud, eq)
                cloud.close()
        logger.info("salvar_equipamento OK | id=%s | dual=%s", eq.get("id"), is_cloud())
        return True
    except Exception as e:
        log_error("salvar_equipamento falhou", e)
        st.error(f"Erro ao salvar equipamento: {e}")
        return False


def excluir_equipamento(eq_id: int) -> bool:
    try:
        sql = "DELETE FROM equipamentos WHERE id = ?"
        params = (eq_id,)
        local = get_local_connection()
        local.execute(sql, params)
        local.commit()
        local.close()
        if is_cloud():
            cloud = get_cloud_connection()
            if cloud is not None:
                cloud.execute(sql, params)
                cloud.commit()
                cloud.close()
        return True
    except Exception as e:
        log_error("excluir_equipamento falhou", e)
        return False


def proximo_id_equipamento() -> int:
    ids = []
    try:
        local = get_local_connection()
        cur = local.cursor()
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM equipamentos")
        ids.append(int(cur.fetchone()[0]))
        local.close()
    except Exception:
        pass
    if is_cloud():
        try:
            cloud = get_cloud_connection()
            if cloud is not None:
                cur = cloud.cursor()
                cur.execute("SELECT COALESCE(MAX(id), 0) FROM equipamentos")
                ids.append(int(cur.fetchone()[0]))
                cloud.close()
        except Exception:
            pass
    return (max(ids) + 1) if ids else 1


def nome_equipamento(eq: dict) -> str:
    return eq.get("nome") or eq.get("Equipamento") or "N/A"


def parse_datetime_safe(value, default: datetime | None = None) -> datetime:
    """
    Converte string / Timestamp / NaN / None em datetime de forma segura.
    Evita ValueError: cannot convert float NaN to integer.
    """
    if default is None:
        default = datetime.now()
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    if isinstance(value, datetime):
        # Garante timezone-naive para cálculos simples
        if getattr(value, "tzinfo", None) is not None:
            try:
                return value.replace(tzinfo=None)
            except Exception:
                return default
        return value
    if isinstance(value, str):
        s = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt
        except Exception:
            pass
    try:
        ts = pd.to_datetime(value, errors="coerce")
        if pd.isna(ts):
            return default
        dt = ts.to_pydatetime()
        if getattr(dt, "tzinfo", None) is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except Exception:
        return default


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
        log_error("comprimir_imagem falhou", e)
        st.error(f"Erro ao comprimir imagem: {e}")
        return None


def reload_data():
    st.session_state.chamados = carregar_dados()
    st.session_state.equipe = carregar_equipe()
    st.session_state.setores = carregar_setores()
    st.session_state.equipamentos = carregar_equipamentos()


# ====================== AUTH ADMIN (via secrets) ======================
def verificar_login_admin(usuario: str, senha: str) -> bool:
    """
    Usa secrets.toml:
      [admin]
      username = "Leandro Coelho"
      password_hash = "sha256..."
    Fallback: usuário/senha legados se secrets não existirem.
    """
    try:
        admin = st.secrets.get("admin", {})
        expected_user = admin.get("username", "Leandro Coelho")
        expected_hash = admin.get("password_hash")
        if expected_hash:
            dig = hashlib.sha256(senha.encode("utf-8")).hexdigest()
            return usuario.strip() == expected_user and dig == expected_hash
    except Exception:
        pass
    # Fallback legado
    return usuario.strip() == "Leandro Coelho" and senha == "123"


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

# ====================== CABEÇALHO ======================
header(
    "Gestão de Chamados e Manutenção",
    "Fluxo integrado de solicitações, execução e indicadores",
    icon="🏭",
)

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
    ["👤 Usuário Comum", "🛠️ Equipe de Manutenção", "👨‍💼 Administrador"],
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
                    }
                    if salvar_chamado(novo):
                        st.session_state.chamados.append(novo)
                        st.success(f"✅ Chamado Nº **{novo_id}** registrado com sucesso!")
                        st.balloons()
                        reload_data()
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
    header("Fila de Manutenção", "Chamados priorizados e alertas preventivos", icon="🛠️")
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
            ["Aberto", "Em Atendimento"],
            default=["Aberto", "Em Atendimento"],
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

    # Alertas Preventivos
    with st.container(border=True):
        st.subheader("⚠️ Alertas de Manutenção Preventiva")
        hoje = datetime.now().date()
        alertas = 0
        for eq in st.session_state.equipamentos:
            if eq.get("proxima_preventiva"):
                try:
                    prox = datetime.fromisoformat(str(eq["proxima_preventiva"])).date()
                    if prox <= hoje + timedelta(days=30):
                        st.warning(
                            f"**{nome_equipamento(eq)}** — Preventiva próxima ({prox.strftime('%d/%m/%Y')})"
                        )
                        alertas += 1
                except Exception:
                    pass
        if alertas == 0:
            st.success("✅ Nenhum alerta preventivo nos próximos 30 dias.")

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
                                reload_data()
                                st.rerun()
                else:
                    st.caption(f"👨‍🔧 Técnico: **{cham.get('executante')}**")
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
                            cham["data_hora_conclusao"] = datetime.now().isoformat()
                            if salvar_chamado(cham):
                                st.success("✅ Chamado concluído!")
                                reload_data()
                                st.rerun()
                        else:
                            st.error("Descreva a solução.")

# ====================== ADMINISTRADOR ======================
elif perfil == "👨‍💼 Administrador":
    if not st.session_state.admin_logado:
        header("Área do Administrador", "Autentique-se para acessar os painéis", icon="👨‍💼")
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
        header("Painel do Administrador", "Indicadores, cadastros e importações", icon="👨‍💼")
        col_a, col_b, col_c = st.columns([5, 2, 1])
        col_a.success("🔓 Sessão administrativa ativa.")
        with col_b:
            if is_cloud():
                if st.button("☁️ Sincronizar Local → Cloud", use_container_width=True, type="primary"):
                    with st.spinner("Sincronizando dados locais para o SQLite Cloud..."):
                        ok, msg = sync_local_to_cloud()
                    if ok:
                        st.success(msg)
                        reload_data()
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

        tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs([
            "📊 Dashboard Geral",
            "📈 Análise Gráfica",
            "📊 Análise de Tempo",
            "🛠️ Ocorrências por Equipamento",
            "👥 Cadastro de Equipe",
            "🏭 Cadastro de Setores",
            "🔧 Cadastro de Equipamentos",
            "🖼️ Galeria de Fotos",
            "📥 Importar Planilha",
        ])

        with tab1:
            if not df.empty:
                df = df.copy()
                df["data_hora_abertura"] = pd.to_datetime(df["data_hora_abertura"], errors="coerce")
                with st.container(border=True):
                    colf1, colf2, colf3, colf4 = st.columns(4)
                    with colf1:
                        filtro_setor = st.multiselect(
                            "Setor", sorted(df["setor"].dropna().unique()), key="f1"
                        )
                    with colf2:
                        filtro_prioridade = st.multiselect(
                            "Prioridade", df["prioridade"].dropna().unique(), key="f2"
                        )
                    with colf3:
                        filtro_status = st.multiselect(
                            "Status",
                            ["Aberto", "Em Atendimento", "Concluído"],
                            key="f3",
                        )
                    with colf4:
                        filtro_tecnico = st.multiselect(
                            "Técnico", df["executante"].dropna().unique(), key="f4"
                        )
                df_filtrado = df.copy()
                if filtro_setor:
                    df_filtrado = df_filtrado[df_filtrado["setor"].isin(filtro_setor)]
                if filtro_prioridade:
                    df_filtrado = df_filtrado[df_filtrado["prioridade"].isin(filtro_prioridade)]
                if filtro_status:
                    df_filtrado = df_filtrado[df_filtrado["status"].isin(filtro_status)]
                if filtro_tecnico:
                    df_filtrado = df_filtrado[df_filtrado["executante"].isin(filtro_tecnico)]

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Total", len(df_filtrado))
                m2.metric("Abertos", len(df_filtrado[df_filtrado["status"] == "Aberto"]))
                m3.metric(
                    "Em Atendimento",
                    len(df_filtrado[df_filtrado["status"] == "Em Atendimento"]),
                )
                m4.metric("Concluídos", len(df_filtrado[df_filtrado["status"] == "Concluído"]))
                st.dataframe(
                    df_filtrado.drop(columns=["foto_path", "foto_solucao_path"], errors="ignore"),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("Nenhum chamado registrado.")

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
                with col2:
                    setor_df = df["setor"].value_counts().reset_index()
                    setor_df.columns = ["setor", "count"]
                    fig = px.bar(
                        setor_df,
                        x="setor",
                        y="count",
                        title="Chamados por Setor",
                        color_discrete_sequence=["#2563EB"],
                    )
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Sem dados para gráficos.")

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
            if not df.empty:
                df_equip = df.groupby("equipamento").size().reset_index(name="Total")
                st.dataframe(
                    df_equip.sort_values("Total", ascending=False),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("Sem dados.")

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
                                st.success(f"{nome} cadastrado!")
                                reload_data()
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
                                    reload_data()
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
                                    st.success("Setor atualizado!")
                                except ValueError:
                                    lista.append(novo_setor.strip())
                                st.session_state.edit_setor = None
                            else:
                                if novo_setor.strip() not in lista:
                                    lista.append(novo_setor.strip())
                                    st.success(f"Setor '{novo_setor}' adicionado!")
                                else:
                                    st.warning("Setor já existe.")
                            if salvar_setores(lista):
                                reload_data()
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
                            reload_data()
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
                                .isoformat(),
                            }
                            if salvar_equipamento(novo):
                                st.session_state.edit_equip = None
                                st.success(
                                    "Equipamento atualizado!"
                                    if edit
                                    else "Equipamento cadastrado!"
                                )
                                reload_data()
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
                with st.expander(f"{nome_eq} - Pat: {eq.get('numero_patrimonio', 'N/A')}"):
                    st.write(eq)
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("✏️ Editar", key=f"edit_eq_{i}"):
                            st.session_state.edit_equip = eq.copy()
                            st.rerun()
                    with col2:
                        if st.button("🗑️ Excluir", key=f"del_eqp_{i}"):
                            if excluir_equipamento(int(eq.get("id"))):
                                reload_data()
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
