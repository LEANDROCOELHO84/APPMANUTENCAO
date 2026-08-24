"""
Notificações — browser (Web Notification API) + canal externo opcional (ntfy/webhook).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

logger = logging.getLogger("chamados_app")


def _get_ntfy_topic() -> str | None:
    """Topic ntfy.sh ou URL completa de webhook nos secrets."""
    try:
        t = st.secrets.get("NTFY_TOPIC") or st.secrets.get("PUSH_WEBHOOK_URL")
        if t and str(t).strip():
            return str(t).strip()
    except Exception:
        pass
    try:
        admin = st.secrets.get("admin", {})
        if admin:
            t = admin.get("NTFY_TOPIC") or admin.get("PUSH_WEBHOOK_URL")
            if t and str(t).strip():
                return str(t).strip()
    except Exception:
        pass
    import os

    t = os.getenv("NTFY_TOPIC") or os.getenv("PUSH_WEBHOOK_URL")
    return t.strip() if t and t.strip() else None


def solicitar_permissao_browser():
    """Pede permissão de notificação do navegador (HTTPS ou localhost)."""
    components.html(
        """
        <script>
        (function() {
          if (!("Notification" in window)) return;
          if (Notification.permission === "default") {
            Notification.requestPermission();
          }
        })();
        </script>
        """,
        height=0,
        width=0,
    )


def notificar_browser(titulo: str, corpo: str, tag: str = "chamados"):
    """Dispara notificação do SO via Web Notification API."""
    t = json.dumps(str(titulo)[:120])
    b = json.dumps(str(corpo)[:280])
    tg = json.dumps(str(tag)[:64])
    components.html(
        f"""
        <script>
        (function() {{
          const title = {t};
          const body = {b};
          const tag = {tg};
          if (!("Notification" in window)) return;
          const show = () => {{
            try {{
              const n = new Notification(title, {{
                body: body,
                tag: tag,
                renotify: true,
              }});
              setTimeout(() => {{ try {{ n.close(); }} catch (e) {{}} }}, 12000);
            }} catch (e) {{ console.warn("notif", e); }}
          }};
          if (Notification.permission === "granted") {{
            show();
          }} else if (Notification.permission !== "denied") {{
            Notification.requestPermission().then(function(p) {{
              if (p === "granted") show();
            }});
          }}
        }})();
        </script>
        """,
        height=0,
        width=0,
    )


def notificar_externo(titulo: str, corpo: str) -> bool:
    """
    Envia para ntfy.sh ou webhook:
      secrets: NTFY_TOPIC = "meu-topico"
      ou PUSH_WEBHOOK_URL = "https://ntfy.sh/meu-topico"
    """
    dest = _get_ntfy_topic()
    if not dest:
        return False
    try:
        import urllib.request

        url = dest if dest.startswith("http") else f"https://ntfy.sh/{dest}"
        data = str(corpo).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Title": str(titulo)[:100],
                "Priority": "high",
                "Tags": "warning,wrench",
                "Content-Type": "text/plain; charset=utf-8",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return 200 <= int(getattr(resp, "status", 200) or 200) < 300
    except Exception as e:
        logger.warning("notificar_externo falhou | %s", str(e)[:140])
        return False


def notificar(
    titulo: str,
    corpo: str,
    *,
    tag: str = "chamados",
    browser: bool = True,
    externo: bool = True,
):
    """Browser + canal externo (se configurado)."""
    if browser and st.session_state.get("notif_browser_on", True):
        try:
            notificar_browser(titulo, corpo, tag=tag)
        except Exception as e:
            logger.warning("notificar_browser | %s", str(e)[:100])
    if externo and st.session_state.get("notif_externo_on", True):
        try:
            notificar_externo(titulo, corpo)
        except Exception:
            pass


def processar_alertas_chamados(chamados: list) -> None:
    """
    Compara com a sessão anterior e notifica:
    - novos chamados Abertos
    - passagem para Aguardando Peça
    """
    if not st.session_state.get("_notif_init_done"):
        seen = set()
        sm = {}
        for c in chamados or []:
            try:
                cid = int(c.get("id"))
            except (TypeError, ValueError):
                continue
            seen.add(cid)
            sm[cid] = str(c.get("status") or "")
        st.session_state.notif_seen_ids = seen
        st.session_state.notif_status_map = sm
        st.session_state._notif_init_done = True
        return

    seen = st.session_state.setdefault("notif_seen_ids", set())
    prev_status = st.session_state.setdefault("notif_status_map", {})

    novos_abertos = []
    mudou_peca = []
    atuais_ids = set()

    for c in chamados or []:
        try:
            cid = int(c.get("id"))
        except (TypeError, ValueError):
            continue
        atuais_ids.add(cid)
        st_now = str(c.get("status") or "")
        st_prev = prev_status.get(cid)

        if cid not in seen and st_now == "Aberto":
            novos_abertos.append(c)
        elif st_prev and st_prev != st_now and st_now == "Aguardando Peça":
            mudou_peca.append(c)

        prev_status[cid] = st_now

    seen |= atuais_ids
    st.session_state.notif_seen_ids = seen
    st.session_state.notif_status_map = prev_status

    if novos_abertos:
        n = len(novos_abertos)
        nomes = ", ".join(f"OS {c.get('id')}" for c in novos_abertos[:5])
        extra = f" (+{n - 5})" if n > 5 else ""
        notificar(
            f"🛎️ {n} novo(s) chamado(s)",
            f"{nomes}{extra} · aguardando técnico",
            tag="novos-chamados",
        )

    for c in mudou_peca:
        notificar(
            f"🛒 OS {c.get('id')} aguardando peça",
            f"{c.get('peca_solicitada') or 'Peça'} · {c.get('equipamento') or ''}",
            tag=f"peca-{c.get('id')}",
        )


def ui_preferencias_notificacao():
    """Controles discretos na sidebar (expander fechado por padrão)."""
    if "notif_browser_on" not in st.session_state:
        st.session_state.notif_browser_on = True
    if "notif_externo_on" not in st.session_state:
        st.session_state.notif_externo_on = bool(_get_ntfy_topic())

    with st.sidebar.expander("🔔 Notificações", expanded=False):
        browser_on = st.checkbox(
            "Navegador",
            value=bool(st.session_state.notif_browser_on),
            key="chk_notif_browser",
            help="Alerta do sistema com a página aberta (HTTPS/localhost).",
        )
        st.session_state.notif_browser_on = browser_on

        tem_ext = bool(_get_ntfy_topic())
        externo_on = st.checkbox(
            "Push externo",
            value=bool(st.session_state.notif_externo_on) and tem_ext,
            key="chk_notif_externo",
            disabled=not tem_ext,
            help="Configure NTFY_TOPIC nos secrets do Streamlit.",
        )
        st.session_state.notif_externo_on = externo_on if tem_ext else False

        if not tem_ext:
            st.caption("Opcional: secret NTFY_TOPIC")
        else:
            st.caption("Canal externo ativo")

        b1, b2 = st.columns(2)
        with b1:
            if st.button(
                "Permissão",
                key="btn_notif_perm",
                type="secondary",
                width="stretch",
            ):
                solicitar_permissao_browser()
                st.caption("Aceite no navegador")
        with b2:
            if st.button(
                "Testar",
                key="btn_notif_test",
                type="secondary",
                width="stretch",
            ):
                notificar(
                    "Teste — Gestão de Chamados",
                    f"OK · {datetime.now().strftime('%H:%M:%S')}",
                    tag="teste",
                )
                st.caption("Enviado")
