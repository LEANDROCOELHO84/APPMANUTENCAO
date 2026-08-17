"""
Camada de dados e regras de negócio — Gestão de Chamados.
Separado da UI Streamlit para clareza e manutenção.
"""
import os
import hashlib
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from PIL import Image, ImageOps

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


def efeito_concluido(mensagem: str, celebrar: bool = True):
    """Feedback visual: toast + success + balloons (opcional)."""
    try:
        st.toast(mensagem, icon="✅")
    except Exception:
        pass
    st.success(mensagem)
    if celebrar:
        try:
            st.balloons()
        except Exception:
            pass


def agendar_efeito_concluido(mensagem: str, celebrar: bool = True):
    """Agenda o feedback para o próximo rerun (para balloons não sumirem)."""
    st.session_state["_efeito_pendente"] = {
        "mensagem": mensagem,
        "celebrar": celebrar,
    }


def _mostrar_efeito_pendente():
    pend = st.session_state.pop("_efeito_pendente", None)
    if not pend:
        return
    efeito_concluido(
        pend.get("mensagem", "✅ Concluído!"),
        celebrar=bool(pend.get("celebrar", True)),
    )

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


class _PersistentConnProxy:
    """
    Encapsula uma conexão (local ou cloud) mantida viva em cache entre
    reruns do Streamlit. Ignora .close() de propósito — todo o código
    existente chama .close() após usar a conexão, mas aqui isso só
    devolveria a conexão real ao pool; ela precisa continuar aberta para
    ser reaproveitada na próxima chamada, evitando reconectar (e refazer
    o handshake de rede/TLS, no caso do Cloud) a cada ação do usuário.
    """
    __slots__ = ("_conn",)

    def __init__(self, conn):
        self._conn = conn

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._conn, name)


@st.cache_resource(show_spinner=False)
def _local_conn_proxy_cached():
    import sqlite3
    raw = sqlite3.connect(LOCAL_DB_PATH, check_same_thread=False)
    return _PersistentConnProxy(raw)


def get_local_connection():
    """Conexão local reaproveitada entre reruns (evita reabrir o arquivo a cada ação)."""
    try:
        proxy = _local_conn_proxy_cached()
        proxy.execute("SELECT 1")
        return proxy
    except Exception:
        _local_conn_proxy_cached.clear()
        return _local_conn_proxy_cached()


@st.cache_resource(show_spinner=False)
def _cloud_conn_proxy_cached(cloud_url: str):
    import sqlitecloud
    raw = sqlitecloud.connect(cloud_url)
    return _PersistentConnProxy(raw)


def _invalidate_cloud_conn():
    """Descarta conexão Cloud cacheada (SSL morto / socket quebrado)."""
    try:
        _cloud_conn_proxy_cached.clear()
    except Exception:
        pass
    # Remove ids de schema das conexões antigas (proxy morto)
    _schema_ensured_conn_ids.clear()


def get_cloud_connection():
    """
    Conexão com o SQLite Cloud reaproveitada entre reruns (cache_resource).
    Abrir uma conexão nova a cada salvamento é o principal motivo de lentidão
    em apps Streamlit com banco remoto — o handshake de rede/TLS custa
    dezenas/centenas de ms por ação. Aqui a conexão é criada uma vez e
    testada (SELECT 1) antes de ser reutilizada; se estiver caída, é
    recriada automaticamente.
    """
    cloud_url = get_connection_string()
    if not cloud_url:
        return None
    try:
        proxy = _cloud_conn_proxy_cached(cloud_url)
        proxy.execute("SELECT 1")
        return proxy
    except ImportError as e:
        log_error("Pacote sqlitecloud não instalado. Rode: pip install sqlitecloud", e)
        return None
    except Exception:
        # Conexão cacheada pode ter caído (timeout/rede/SSL) — descarta e tenta reconectar 1x
        try:
            _invalidate_cloud_conn()
            proxy = _cloud_conn_proxy_cached(cloud_url)
            proxy.execute("SELECT 1")
            return proxy
        except Exception as e2:
            # SSL/rede intermitente: log curto (sem traceback completo a cada 30s)
            msg = str(e2)
            if any(
                x in msg.lower()
                for x in ("ssl", "socket", "decrypt", "wrong version", "incomplete")
            ):
                logger.warning(
                    "Cloud offline temporário (SSL/rede) | %s", msg[:180]
                )
            else:
                log_error(
                    f"Falha ao conectar no SQLite Cloud | url={cloud_url[:60]}...",
                    e2,
                )
            _invalidate_cloud_conn()
            return None


def get_db_connection():
    """
    Conexão principal de leitura/escrita.
    Prioridade: Cloud (se configurado e saudável) → Local.
    """
    cloud = get_cloud_connection()
    if cloud is not None:
        return cloud
    return get_local_connection()


_schema_ensured_conn_ids = set()


def _colunas_tabela(conn, tabela: str) -> set:
    """Retorna o conjunto de nomes de colunas de uma tabela (PRAGMA table_info)."""
    try:
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({tabela})")
        rows = cur.fetchall()
        # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
        return {str(r[1]) for r in rows if r and len(r) > 1}
    except Exception:
        return set()


def _ensure_schema(conn):
    """
    Cria tabelas (e roda a migração de colunas) se ainda não existirem.
    Como as conexões agora são reaproveitadas entre reruns (cache_resource),
    a verificação completa só precisa rodar UMA VEZ por conexão — repeti-la
    a cada salvamento era um dos principais motivos da lentidão (vários
    comandos extras via rede a cada clique, no caso do Cloud).
    """
    if id(conn) in _schema_ensured_conn_ids:
        return
    try:
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
                foto_solucao_path TEXT,
                comentario_conclusao TEXT,
                peca_solicitada TEXT,
                peca_observacao TEXT,
                data_solicitacao_peca TEXT
            )
        """)
        _migrar_colunas_chamados(conn)
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
                proxima_preventiva TEXT,
                silenciar_ate TEXT
            )
        """)
        _migrar_colunas_equipamentos(conn)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS manutencoes_historico (
                id INTEGER PRIMARY KEY,
                equipamento_id INTEGER,
                equipamento_nome TEXT,
                tipo TEXT,
                data_manutencao TEXT,
                executante TEXT,
                descricao TEXT,
                pecas_trocadas TEXT,
                custo_pecas REAL DEFAULT 0,
                horas_homem REAL DEFAULT 0,
                chamado_id INTEGER,
                observacao TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS compras_pecas (
                id INTEGER PRIMARY KEY,
                chamado_id INTEGER,
                equipamento TEXT,
                prioridade TEXT,
                item_nome TEXT,
                link_compra TEXT,
                observacao TEXT,
                solicitante TEXT,
                prazo_recebimento TEXT,
                status TEXT,
                aprovado TEXT,
                dias_para_chegada INTEGER,
                valor_item REAL,
                data_solicitacao TEXT,
                data_aprovacao TEXT,
                data_recebimento TEXT,
                comprador TEXT,
                observacao_compras TEXT
            )
        """)
        conn.commit()
        _schema_ensured_conn_ids.add(id(conn))
    except Exception as e:
        # Não marca como "ensured" se falhou — permite retry na próxima chamada
        log_error("_ensure_schema falhou", e)
        raise


def _migrar_colunas_chamados(conn):
    """
    Adiciona colunas novas em bancos já existentes (ALTER TABLE), sem quebrar
    instalações antigas. Verifica colunas existentes via PRAGMA antes do ALTER
    (mais confiável que try/except no driver sqlitecloud, que pode deixar a
    conexão em estado inválido após erro de 'duplicate column').
    """
    colunas_novas = {
        "comentario_conclusao": "TEXT",
        "peca_solicitada": "TEXT",
        "peca_observacao": "TEXT",
        "data_solicitacao_peca": "TEXT",
    }
    existentes = _colunas_tabela(conn, "chamados")
    if not existentes:
        # Tabela recém-criada pelo CREATE TABLE acima já tem todas as colunas
        return
    cur = conn.cursor()
    for col, tipo in colunas_novas.items():
        if col in existentes:
            continue
        try:
            cur.execute(f"ALTER TABLE chamados ADD COLUMN {col} {tipo}")
            conn.commit()
            existentes.add(col)
        except Exception as e:
            # Ainda assim ignora (ex.: corrida entre instâncias)
            msg = str(e).lower()
            if "duplicate column" in msg or "already exists" in msg:
                existentes.add(col)
            else:
                log_error(f"_migrar_colunas ALTER {col} falhou", e)


def _migrar_colunas_equipamentos(conn):
    """Adiciona colunas novas em equipamentos (ex.: silenciar_ate)."""
    colunas_novas = {
        "silenciar_ate": "TEXT",
    }
    existentes = _colunas_tabela(conn, "equipamentos")
    if not existentes:
        return
    cur = conn.cursor()
    for col, tipo in colunas_novas.items():
        if col in existentes:
            continue
        try:
            cur.execute(f"ALTER TABLE equipamentos ADD COLUMN {col} {tipo}")
            conn.commit()
            existentes.add(col)
        except Exception as e:
            msg = str(e).lower()
            if "duplicate column" in msg or "already exists" in msg:
                existentes.add(col)
            else:
                log_error(f"_migrar_colunas_equipamentos ALTER {col} falhou", e)


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

        tabelas = [
            "chamados",
            "equipe",
            "setores",
            "equipamentos",
            "manutencoes_historico",
            "compras_pecas",
        ]
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
def init_db(force: bool = False):
    """
    Cria tabelas no local e no cloud (se configurado).
    Por padrão roda só uma vez por sessão — o autorefresh a cada 30s
    não deve reabrir handshake Cloud nem lotar o log.
    """
    if not force and st.session_state.get("_db_init_done"):
        return
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
                    _invalidate_cloud_conn()
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

        st.session_state.db_status = {
            "modo": modo,
            "cloud_ok": cloud_ok,
            "cloud_msg": cloud_msg,
        }
        st.session_state._db_init_done = True
    except Exception as e:
        log_error("init_db falhou", e)
        st.error(f"Erro ao inicializar banco: {e}")


def _normalize_datetime_cols(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["data_hora_abertura", "data_hora_inicio", "data_hora_conclusao"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def _ler_sql_com_fallback(sql: str, prefer_cloud: bool = True):
    """
    Executa SELECT priorizando Cloud; se a conexão Cloud falhar (SSL/socket),
    invalida o cache e lê do banco local para o app não quebrar.
    """
    if prefer_cloud and is_cloud():
        try:
            conn = get_cloud_connection()
            if conn is not None:
                df = pd.read_sql(sql, conn)
                conn.close()
                return df
        except Exception as e:
            log_error(f"leitura Cloud falhou, fallback local | sql={sql[:60]}", e)
            _invalidate_cloud_conn()
    local = get_local_connection()
    df = pd.read_sql(sql, local)
    local.close()
    return df


def carregar_dados() -> list[dict]:
    try:
        df = _ler_sql_com_fallback("SELECT * FROM chamados")
        if df.empty:
            return []
        df = _normalize_datetime_cols(df)
        # Serializa datas como string ISO ou None (evita NaT no session_state)
        for col in ["data_hora_abertura", "data_hora_inicio", "data_hora_conclusao", "data_solicitacao_peca"]:
            if col in df.columns:
                df[col] = df[col].apply(_fmt_data)
        records = df.where(pd.notnull(df), None).to_dict(orient="records")
        # Segunda passada: garante que nenhum NaT/float nan vazou
        for rec in records:
            for k, v in list(rec.items()):
                try:
                    if v is not None and pd.isna(v):
                        rec[k] = None
                except (TypeError, ValueError):
                    pass
                if k.startswith("data_") or "hora" in k:
                    rec[k] = _fmt_data(v)
        return records
    except Exception as e:
        log_error("carregar_dados falhou", e)
        st.error(f"Erro ao carregar chamados: {e}")
        return []


def _fmt_data(v):
    """Normaliza datas para string ISO (trata None, NaN, NaT, Timestamp)."""
    if v is None or v == "":
        return None
    # NaT / NA (pandas) — nunca chamar strftime em NaT
    try:
        if v is pd.NaT:
            return None
    except Exception:
        pass
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    # String já limpa
    if isinstance(v, str):
        s = v.strip()
        if not s or s.lower() in ("nat", "nan", "none", "null"):
            return None
        try:
            ts = pd.to_datetime(s, errors="coerce")
            if pd.isna(ts):
                return s  # mantém string original se não for data
            return ts.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return s
    # datetime / Timestamp
    try:
        if hasattr(v, "strftime") and not pd.isna(v):
            # Timestamp com tz → naive
            if getattr(v, "tzinfo", None) is not None:
                try:
                    v = v.replace(tzinfo=None)
                except Exception:
                    pass
            return v.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, OverflowError, AttributeError):
        pass
    try:
        ts = pd.to_datetime(v, errors="coerce")
        if pd.isna(ts):
            return None
        if getattr(ts, "tzinfo", None) is not None:
            try:
                ts = ts.tz_localize(None) if ts.tzinfo else ts
            except Exception:
                try:
                    ts = ts.replace(tzinfo=None)
                except Exception:
                    pass
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    s = str(v).strip()
    return s if s and s.lower() not in ("nat", "nan", "none", "null") else None


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
                solucao_descricao=?, foto_solucao_path=?, comentario_conclusao=?,
                peca_solicitada=?, peca_observacao=?, data_solicitacao_peca=?
            WHERE id=?
        """, (
            campos["solicitante"], campos["data_hora_abertura"], campos["setor"],
            campos["equipamento"], campos["prioridade"], campos["descricao"],
            campos["status"], campos["executante"], campos["data_hora_inicio"],
            campos["data_hora_conclusao"], campos["foto_path"],
            campos["solucao_descricao"], campos["foto_solucao_path"],
            campos["comentario_conclusao"], campos["peca_solicitada"],
            campos["peca_observacao"], campos["data_solicitacao_peca"],
            campos["id"],
        ))
    else:
        cur.execute("""
            INSERT INTO chamados (
                id, solicitante, data_hora_abertura, setor, equipamento,
                prioridade, descricao, status, executante,
                data_hora_inicio, data_hora_conclusao, foto_path,
                solucao_descricao, foto_solucao_path, comentario_conclusao,
                peca_solicitada, peca_observacao, data_solicitacao_peca
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            campos["id"], campos["solicitante"], campos["data_hora_abertura"],
            campos["setor"], campos["equipamento"], campos["prioridade"],
            campos["descricao"], campos["status"], campos["executante"],
            campos["data_hora_inicio"], campos["data_hora_conclusao"],
            campos["foto_path"], campos["solucao_descricao"],
            campos["foto_solucao_path"], campos["comentario_conclusao"],
            campos["peca_solicitada"], campos["peca_observacao"],
            campos["data_solicitacao_peca"],
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
            "comentario_conclusao": chamado.get("comentario_conclusao") or "",
            "peca_solicitada": chamado.get("peca_solicitada") or "",
            "peca_observacao": chamado.get("peca_observacao") or "",
            "data_solicitacao_peca": _fmt_data(chamado.get("data_solicitacao_peca")),
        }

        # 1) Local (sempre) — fonte da verdade offline
        local = get_local_connection()
        _ensure_schema(local)
        _upsert_chamado_em(local, campos)
        local.close()

        # 2) Cloud (se configurado) — falha de rede/SSL não impede o salvamento local
        dual_ok = False
        if is_cloud():
            try:
                cloud = get_cloud_connection()
                if cloud is not None:
                    _ensure_schema(cloud)
                    _upsert_chamado_em(cloud, campos)
                    cloud.close()
                    dual_ok = True
            except Exception as e_cloud:
                log_error(
                    f"salvar_chamado CLOUD id={campos['id']} falhou (local OK)",
                    e_cloud,
                )
                _invalidate_cloud_conn()

        logger.info(
            "salvar_chamado OK | id=%s status=%s | dual=%s",
            campos["id"], campos["status"], dual_ok,
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
        df = _ler_sql_com_fallback("SELECT * FROM equipe")
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
        df = _ler_sql_com_fallback("SELECT setor FROM setores ORDER BY setor")
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
        df = _ler_sql_com_fallback("SELECT * FROM equipamentos")
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
        eq.get("silenciar_ate"),
    )
    if existe:
        cur.execute("""
            UPDATE equipamentos SET
                nome=?, marca=?, modelo=?, ano_aquisicao=?,
                numero_patrimonio=?, setor=?, sazonalidade_meses=?,
                ultima_preventiva=?, proxima_preventiva=?, silenciar_ate=?
            WHERE id=?
        """, (*vals, eq_id))
    else:
        cur.execute("""
            INSERT INTO equipamentos (
                id, nome, marca, modelo, ano_aquisicao, numero_patrimonio,
                setor, sazonalidade_meses, ultima_preventiva, proxima_preventiva,
                silenciar_ate
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
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


def proximo_id_manutencao() -> int:
    ids = []
    try:
        local = get_local_connection()
        cur = local.cursor()
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM manutencoes_historico")
        ids.append(int(cur.fetchone()[0]))
        local.close()
    except Exception:
        pass
    if is_cloud():
        try:
            cloud = get_cloud_connection()
            if cloud is not None:
                cur = cloud.cursor()
                cur.execute("SELECT COALESCE(MAX(id), 0) FROM manutencoes_historico")
                ids.append(int(cur.fetchone()[0]))
                cloud.close()
        except Exception:
            pass
    return (max(ids) + 1) if ids else 1


def _upsert_manutencao_em(conn, reg: dict) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO manutencoes_historico (
            id, equipamento_id, equipamento_nome, tipo, data_manutencao,
            executante, descricao, pecas_trocadas, custo_pecas, horas_homem,
            chamado_id, observacao
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            reg["id"],
            reg.get("equipamento_id"),
            reg.get("equipamento_nome"),
            reg.get("tipo"),
            reg.get("data_manutencao"),
            reg.get("executante") or "",
            reg.get("descricao") or "",
            reg.get("pecas_trocadas") or "",
            float(reg.get("custo_pecas") or 0),
            float(reg.get("horas_homem") or 0),
            reg.get("chamado_id"),
            reg.get("observacao") or "",
        ),
    )
    conn.commit()


def salvar_manutencao(reg: dict) -> bool:
    """Persiste registro de manutenção no local e no cloud."""
    try:
        if not reg.get("id"):
            reg["id"] = proximo_id_manutencao()
        local = get_local_connection()
        _ensure_schema(local)
        _upsert_manutencao_em(local, reg)
        local.close()
        if is_cloud():
            try:
                cloud = get_cloud_connection()
                if cloud is not None:
                    _ensure_schema(cloud)
                    _upsert_manutencao_em(cloud, reg)
                    cloud.close()
            except Exception as e_cloud:
                log_error(f"salvar_manutencao CLOUD id={reg.get('id')} falhou", e_cloud)
                _invalidate_cloud_conn()
        logger.info(
            "salvar_manutencao OK | id=%s tipo=%s eq=%s",
            reg.get("id"),
            reg.get("tipo"),
            reg.get("equipamento_nome"),
        )
        return True
    except Exception as e:
        log_error("salvar_manutencao falhou", e)
        st.error(f"Erro ao salvar manutenção: {e}")
        return False


def carregar_historico_manutencao(equipamento_id: int | None = None) -> list[dict]:
    try:
        if equipamento_id is not None:
            sql = (
                "SELECT * FROM manutencoes_historico "
                f"WHERE equipamento_id = {int(equipamento_id)} "
                "ORDER BY data_manutencao DESC"
            )
        else:
            sql = "SELECT * FROM manutencoes_historico ORDER BY data_manutencao DESC"
        df = _ler_sql_com_fallback(sql)
        if df.empty:
            return []
        return df.where(pd.notnull(df), None).to_dict(orient="records")
    except Exception as e:
        log_error("carregar_historico_manutencao falhou", e)
        return []


# ====================== COMPRAS DE PEÇAS ======================
def proximo_id_compra() -> int:
    ids = []
    try:
        local = get_local_connection()
        cur = local.cursor()
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM compras_pecas")
        ids.append(int(cur.fetchone()[0]))
        local.close()
    except Exception:
        pass
    if is_cloud():
        try:
            cloud = get_cloud_connection()
            if cloud is not None:
                cur = cloud.cursor()
                cur.execute("SELECT COALESCE(MAX(id), 0) FROM compras_pecas")
                ids.append(int(cur.fetchone()[0]))
                cloud.close()
        except Exception:
            pass
    return (max(ids) + 1) if ids else 1


def _upsert_compra_em(conn, reg: dict) -> None:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM compras_pecas WHERE id = ?", (reg["id"],))
    existe = cur.fetchone() is not None
    vals = (
        reg.get("chamado_id"),
        reg.get("equipamento") or "",
        reg.get("prioridade") or "",
        reg.get("item_nome") or "",
        reg.get("link_compra") or "",
        reg.get("observacao") or "",
        reg.get("solicitante") or "",
        reg.get("prazo_recebimento"),
        reg.get("status") or "Pendente",
        reg.get("aprovado") or "",
        reg.get("dias_para_chegada"),
        float(reg.get("valor_item") or 0),
        reg.get("data_solicitacao"),
        reg.get("data_aprovacao"),
        reg.get("data_recebimento"),
        reg.get("comprador") or "",
        reg.get("observacao_compras") or "",
    )
    if existe:
        cur.execute(
            """
            UPDATE compras_pecas SET
                chamado_id=?, equipamento=?, prioridade=?, item_nome=?,
                link_compra=?, observacao=?, solicitante=?, prazo_recebimento=?,
                status=?, aprovado=?, dias_para_chegada=?, valor_item=?,
                data_solicitacao=?, data_aprovacao=?, data_recebimento=?,
                comprador=?, observacao_compras=?
            WHERE id=?
            """,
            (*vals, reg["id"]),
        )
    else:
        cur.execute(
            """
            INSERT INTO compras_pecas (
                id, chamado_id, equipamento, prioridade, item_nome,
                link_compra, observacao, solicitante, prazo_recebimento,
                status, aprovado, dias_para_chegada, valor_item,
                data_solicitacao, data_aprovacao, data_recebimento,
                comprador, observacao_compras
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (reg["id"], *vals),
        )
    conn.commit()


def salvar_compra(reg: dict) -> bool:
    try:
        if not reg.get("id"):
            reg["id"] = proximo_id_compra()
        local = get_local_connection()
        _ensure_schema(local)
        _upsert_compra_em(local, reg)
        local.close()
        if is_cloud():
            try:
                cloud = get_cloud_connection()
                if cloud is not None:
                    _ensure_schema(cloud)
                    _upsert_compra_em(cloud, reg)
                    cloud.close()
            except Exception as e_cloud:
                log_error(f"salvar_compra CLOUD id={reg.get('id')} falhou", e_cloud)
                _invalidate_cloud_conn()
        logger.info(
            "salvar_compra OK | id=%s item=%s status=%s",
            reg.get("id"),
            reg.get("item_nome"),
            reg.get("status"),
        )
        return True
    except Exception as e:
        log_error("salvar_compra falhou", e)
        st.error(f"Erro ao salvar solicitação de compra: {e}")
        return False


def carregar_compras(status: str | None = None) -> list[dict]:
    try:
        if status:
            sql = (
                "SELECT * FROM compras_pecas WHERE status = "
                f"'{str(status).replace(chr(39), '')}' "
                "ORDER BY data_solicitacao DESC"
            )
        else:
            sql = "SELECT * FROM compras_pecas ORDER BY data_solicitacao DESC"
        df = _ler_sql_com_fallback(sql)
        if df.empty:
            return []
        return df.where(pd.notnull(df), None).to_dict(orient="records")
    except Exception as e:
        log_error("carregar_compras falhou", e)
        return []


def carregar_compras_por_chamado(chamado_id: int) -> list[dict]:
    try:
        sql = (
            "SELECT * FROM compras_pecas WHERE chamado_id = "
            f"{int(chamado_id)} ORDER BY data_solicitacao DESC"
        )
        df = _ler_sql_com_fallback(sql)
        if df.empty:
            return []
        return df.where(pd.notnull(df), None).to_dict(orient="records")
    except Exception as e:
        log_error("carregar_compras_por_chamado falhou", e)
        return []


def historico_compras_item(item_nome: str, equipamento: str | None = None) -> list[dict]:
    """Compras anteriores do mesmo item (opcionalmente no mesmo equipamento)."""
    try:
        todas = carregar_compras()
        nome = (item_nome or "").strip().lower()
        if not nome:
            return []
        hist = []
        for c in todas:
            if (c.get("item_nome") or "").strip().lower() != nome:
                continue
            if c.get("status") not in ("Aprovada", "Recebida", "Comprada"):
                # inclui também rejeitadas para contexto? só compradas/recebidas
                if c.get("aprovado") != "Sim":
                    continue
            hist.append(c)
        if equipamento:
            eq = equipamento.strip().lower()
            hist_eq = [
                h for h in hist
                if (h.get("equipamento") or "").strip().lower() == eq
            ]
            # prioriza mesmo equipamento, depois outros
            outros = [h for h in hist if h not in hist_eq]
            hist = hist_eq + outros
        return hist
    except Exception as e:
        log_error("historico_compras_item falhou", e)
        return []


def criar_solicitacao_compra_do_chamado(
    cham: dict,
    item_nome: str,
    link_compra: str = "",
    observacao: str = "",
    prazo_recebimento: str | None = None,
    solicitante: str = "",
) -> dict | None:
    """Gera solicitação de compra vinculada ao chamado (status Pendente)."""
    reg = {
        "id": proximo_id_compra(),
        "chamado_id": cham.get("id"),
        "equipamento": cham.get("equipamento") or "",
        "prioridade": cham.get("prioridade") or "",
        "item_nome": item_nome.strip(),
        "link_compra": (link_compra or "").strip(),
        "observacao": (observacao or "").strip(),
        "solicitante": (solicitante or cham.get("executante") or "").strip(),
        "prazo_recebimento": prazo_recebimento,
        "status": "Pendente",
        "aprovado": "",
        "dias_para_chegada": None,
        "valor_item": 0,
        "data_solicitacao": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_aprovacao": None,
        "data_recebimento": None,
        "comprador": "",
        "observacao_compras": "",
    }
    if salvar_compra(reg):
        return reg
    return None


def _notificar_chamado_compra(chamado_id: int, texto: str) -> None:
    """Anexa notificação no comentário do chamado e grava."""
    try:
        chamados = st.session_state.get("chamados") or carregar_dados()
        for c in chamados:
            if c.get("id") == chamado_id:
                base = (c.get("comentario_conclusao") or "").strip()
                stamp = datetime.now().strftime("%d/%m/%Y %H:%M")
                novo = f"{base}\n[{stamp} COMPRAS] {texto}".strip()
                c["comentario_conclusao"] = novo
                # também reforça observação da peça
                obs = (c.get("peca_observacao") or "").strip()
                c["peca_observacao"] = f"{obs}\n[{stamp}] {texto}".strip()
                salvar_chamado(c)
                break
        st.session_state.chamados = carregar_dados()
    except Exception as e:
        log_error("_notificar_chamado_compra falhou", e)


def concluir_preventiva(
    eq: dict,
    executante: str = "",
    descricao: str = "",
    pecas: str = "",
    custo_pecas: float = 0.0,
    horas_homem: float = 0.0,
    observacao: str = "",
) -> bool:
    """
    Marca preventiva como feita: atualiza ultima/proxima_preventiva,
    limpa silenciar_ate e grava no histórico.
    """
    try:
        hoje = datetime.now().date()
        meses = int(eq.get("sazonalidade_meses") or 6)
        prox = (hoje + timedelta(days=meses * 30)).isoformat()
        eq["ultima_preventiva"] = hoje.isoformat()
        eq["proxima_preventiva"] = prox
        eq["silenciar_ate"] = None
        if not salvar_equipamento(eq):
            return False
        reg = {
            "id": proximo_id_manutencao(),
            "equipamento_id": eq.get("id"),
            "equipamento_nome": nome_equipamento(eq),
            "tipo": "Preventiva",
            "data_manutencao": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "executante": executante,
            "descricao": descricao or "Manutenção preventiva concluída",
            "pecas_trocadas": pecas,
            "custo_pecas": custo_pecas,
            "horas_homem": horas_homem,
            "chamado_id": None,
            "observacao": observacao,
        }
        return salvar_manutencao(reg)
    except Exception as e:
        log_error("concluir_preventiva falhou", e)
        st.error(f"Erro ao concluir preventiva: {e}")
        return False


def adiar_alerta_preventiva(eq: dict, dias: int = 7) -> bool:
    """Silencia o alerta preventivo até hoje + N dias."""
    try:
        ate = (datetime.now().date() + timedelta(days=int(dias))).isoformat()
        eq["silenciar_ate"] = ate
        return salvar_equipamento(eq)
    except Exception as e:
        log_error("adiar_alerta_preventiva falhou", e)
        st.error(f"Erro ao adiar alerta: {e}")
        return False


def custo_e_horas_por_equipamento(
    historico: list[dict] | None = None,
    chamados: list[dict] | None = None,
) -> pd.DataFrame:
    """
    Consolida custo de peças e horas-homem por equipamento
    (histórico de manutenções + chamados concluídos).
    """
    rows: dict[str, dict] = {}

    def _acc(nome: str, custo: float, horas: float, n: int = 1):
        if not nome or nome == "N/A":
            return
        if nome not in rows:
            rows[nome] = {
                "Equipamento": nome,
                "Custo Peças (R$)": 0.0,
                "Horas-Homem": 0.0,
                "Qtd Manutenções": 0,
            }
        rows[nome]["Custo Peças (R$)"] += float(custo or 0)
        rows[nome]["Horas-Homem"] += float(horas or 0)
        rows[nome]["Qtd Manutenções"] += n

    if historico is None:
        historico = carregar_historico_manutencao()
    for h in historico:
        _acc(
            h.get("equipamento_nome") or "N/A",
            h.get("custo_pecas") or 0,
            h.get("horas_homem") or 0,
        )

    if chamados is None:
        chamados = st.session_state.get("chamados") or []
    for c in chamados:
        if c.get("status") != "Concluído":
            continue
        nome = c.get("equipamento") or "N/A"
        horas = 0.0
        try:
            ini_raw = c.get("data_hora_inicio")
            fim_raw = c.get("data_hora_conclusao")
            if ini_raw and fim_raw:
                ini = pd.to_datetime(ini_raw, errors="coerce")
                fim = pd.to_datetime(fim_raw, errors="coerce")
                if pd.notna(ini) and pd.notna(fim) and fim >= ini:
                    horas = (fim - ini).total_seconds() / 3600.0
        except Exception:
            horas = 0.0
        # Chamados concluídos contribuem com horas; custo de peça fica no histórico
        _acc(nome, 0.0, horas, n=1)

    if not rows:
        return pd.DataFrame(
            columns=["Equipamento", "Custo Peças (R$)", "Horas-Homem", "Qtd Manutenções"]
        )
    df = pd.DataFrame(list(rows.values()))
    df["Custo Peças (R$)"] = df["Custo Peças (R$)"].round(2)
    df["Horas-Homem"] = df["Horas-Homem"].round(2)
    return df.sort_values("Custo Peças (R$)", ascending=False)


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


