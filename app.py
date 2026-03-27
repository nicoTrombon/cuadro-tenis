"""
Cuadro de Tenis — Gestión de torneos de tenis
"""
import os
import math
import datetime
import io

import streamlit as st
import streamlit.components.v1 as components

from database import (
    init_db, create_tournament, get_tournament, get_all_tournaments,
    verify_admin_password, get_players, get_players_dict, get_matches,
    update_match_result, advance_winner, initialise_bracket,
    determine_winner, format_score, update_tournament_format,
    update_match_date, get_match,
    update_player, get_match_for_player, apply_bye_to_match,
)
from bracket_display import render_bracket
import s3_sync
from database import DB_PATH

# ── Secrets (Streamlit Cloud: Settings → Secrets; local: .streamlit/secrets.toml) ──
# Populates os.environ so s3_sync (boto3) keeps reading the same keys.
_DEFAULT_ADMIN_FALLBACK = "admin123"
_SECRET_KEYS = (
    "DEFAULT_ADMIN_PASSWORD",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_REGION",
    "S3_BUCKET",
    "S3_DB_KEY",
    "R2_ENDPOINT_URL",
    "S3_ENDPOINT_URL",
)


def _apply_streamlit_secrets_to_environ() -> None:
    try:
        sec = st.secrets
    except Exception:
        return
    for key in _SECRET_KEYS:
        if os.environ.get(key):
            continue
        try:
            val = sec[key]
        except Exception:
            continue
        if val is not None and str(val).strip() != "":
            os.environ[key] = str(val)


_apply_streamlit_secrets_to_environ()
DEFAULT_ADMIN_PASSWORD = os.environ.get("DEFAULT_ADMIN_PASSWORD") or _DEFAULT_ADMIN_FALLBACK

# ── App config ─────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Cuadro de Tenis",
    page_icon="🎾",
    layout="wide",
)

init_db()

# ── Session state defaults ─────────────────────────────────────────────────────
if "admin_tournament_id" not in st.session_state:
    st.session_state.admin_tournament_id = None
if "selected_tournament_id" not in st.session_state:
    st.session_state.selected_tournament_id = None


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def is_admin(tournament_id: int) -> bool:
    return st.session_state.admin_tournament_id == tournament_id


def round_name(round_num: int, total_rounds: int) -> str:
    delta = total_rounds - round_num
    if delta == 0:
        return "Final"
    if delta == 1:
        return "Semifinales"
    if delta == 2:
        return "Cuartos de Final"
    if delta == 3:
        return "Octavos de Final"
    return f"{round_num}ª Ronda"


def player_name(pid, players_dict):
    if pid is None:
        return "Por definir"
    p = players_dict.get(pid)
    if not p:
        return "Por definir"
    return "BYE" if p["is_bye"] else p["name"]


# ═══════════════════════════════════════════════════════════════════════════════
# Sidebar — tournament selector + admin login
# ═══════════════════════════════════════════════════════════════════════════════

def sidebar():
    st.sidebar.title("🎾 Cuadro de Tenis")

    tournaments = get_all_tournaments()

    if not tournaments:
        st.sidebar.info("No hay torneos. Crea uno en la pestaña **Nuevo Torneo**.")
        return

    options = {t["name"]: t["id"] for t in tournaments}
    selected_name = st.sidebar.selectbox(
        "Selecciona torneo",
        list(options.keys()),
        key="sidebar_tournament_select",
    )
    st.session_state.selected_tournament_id = options[selected_name]
    tid = st.session_state.selected_tournament_id

    st.sidebar.divider()
    if s3_sync.is_configured():
        st.sidebar.caption("☁️ Copia de seguridad S3 configurada.")
    else:
        st.sidebar.caption(
            "⚠️ Sin S3 configurado — los datos se pierden al redesplegar."
        )
    st.sidebar.divider()

    if is_admin(tid):
        st.sidebar.success("✅ Sesión de administrador activa")
        if st.sidebar.button("Cerrar sesión de admin"):
            st.session_state.admin_tournament_id = None
            st.rerun()

        # ── S3 backup ──────────────────────────────────────────────────────────
        if s3_sync.is_configured():
            st.sidebar.divider()
            st.sidebar.markdown("**☁️ Copia de seguridad**")
            st.sidebar.caption("Guarda los datos antes de desplegar una nueva versión.")
            if st.sidebar.button("💾 Guardar copia en S3"):
                ok, msg = s3_sync.upload(DB_PATH)
                if ok:
                    st.sidebar.success(msg)
                else:
                    st.sidebar.error(msg)
    else:
        with st.sidebar.expander("🔒 Acceso administrador"):
            pwd = st.text_input("Contraseña del torneo", type="password", key="admin_pwd_input")
            if st.button("Entrar como admin"):
                if verify_admin_password(tid, pwd):
                    st.session_state.admin_tournament_id = tid
                    st.success("Acceso concedido")
                    st.rerun()
                else:
                    st.error("Contraseña incorrecta")


# ═══════════════════════════════════════════════════════════════════════════════
# Tab: Cuadro (bracket view)
# ═══════════════════════════════════════════════════════════════════════════════

def tab_cuadro(tid: int):
    t = get_tournament(tid)

    # Format info
    fmt = "Super Tiebreak" if t["third_set_format"] == "super_tiebreak" else "Set completo"
    col1, col2, col3 = st.columns(3)
    col1.metric("Formato", f"Al mejor de {t['best_of']}")
    col2.metric("3er set", fmt)
    if t["third_set_format"] == "super_tiebreak":
        col3.metric("Puntos tiebreak", t["tiebreak_points"])

    st.header(f"Cuadro — {t['name']}")

    matches = get_matches(tid)
    if not matches:
        st.info("El cuadro aún no tiene partidos. El administrador debe inicializar el torneo.")
        return

    players_dict = get_players_dict(tid)
    total_rounds = t["total_rounds"]

    matches_by_round: dict[int, list] = {}
    for m in matches:
        matches_by_round.setdefault(m["round_number"], []).append(m)

    html = render_bracket(matches_by_round, players_dict, total_rounds)
    bracket_height = 44 + (2 ** total_rounds) * 38 + 40
    components.html(html, height=min(bracket_height, 700), scrolling=True)



# ═══════════════════════════════════════════════════════════════════════════════
# Tab: Partidos (match list)
# ═══════════════════════════════════════════════════════════════════════════════

def tab_partidos(tid: int):
    t = get_tournament(tid)
    st.header(f"Partidos — {t['name']}")

    matches = get_matches(tid)
    if not matches:
        st.info("No hay partidos registrados todavía.")
        return

    players_dict = get_players_dict(tid)
    total_rounds = t["total_rounds"]

    for rnd in range(1, total_rounds + 1):
        round_matches = [m for m in matches if m["round_number"] == rnd]
        if not round_matches:
            continue

        with st.expander(round_name(rnd, total_rounds), expanded=(rnd == 1)):
            for m in sorted(round_matches, key=lambda x: x["match_position"]):
                p1n = player_name(m["player1_id"], players_dict)
                p2n = player_name(m["player2_id"], players_dict)
                score = format_score(m)
                date_str = m["scheduled_date"] or ""
                status = m["status"]

                if status == "completed":
                    winner_n = player_name(m["winner_id"], players_dict)
                    st.markdown(
                        f"**{p1n}** vs {p2n} &nbsp;|&nbsp; 🏅 **{winner_n}** &nbsp; `{score}`"
                        + (f" &nbsp; 📅 {date_str}" if date_str else "")
                    )
                elif status == "walkover":
                    winner_n = player_name(m["winner_id"], players_dict)
                    st.markdown(f"~~{p1n} vs {p2n}~~ &nbsp;→ **{winner_n}** pasa (BYE/W.O.)")
                else:
                    st.markdown(
                        f"{p1n} vs {p2n}"
                        + (f" &nbsp; 📅 {date_str}" if date_str else " &nbsp; *(pendiente)*")
                    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tab: Admin
# ═══════════════════════════════════════════════════════════════════════════════

def tab_admin(tid: int):
    if not is_admin(tid):
        st.warning("Inicia sesión como administrador desde la barra lateral.")
        return

    t = get_tournament(tid)
    st.header(f"Panel de administración — {t['name']}")

    tab_res, tab_jugadores, tab_fmt = st.tabs(["📝 Resultados", "👥 Jugadores", "⚙️ Formato"])

    # ── Results sub-tab ────────────────────────────────────────────────────────
    with tab_res:
        matches = get_matches(tid)
        players_dict = get_players_dict(tid)
        total_rounds = t["total_rounds"]

        pending = [
            m for m in matches
            if m["status"] == "pending"
            and m.get("player1_id")
            and m.get("player2_id")
        ]
        completed = [m for m in matches if m["status"] == "completed"]

        if not pending:
            st.success("No hay partidos pendientes.")
        else:
            st.subheader("Partidos pendientes")

            def match_label(m):
                p1 = player_name(m["player1_id"], players_dict)
                p2 = player_name(m["player2_id"], players_dict)
                rnd = round_name(m["round_number"], total_rounds)
                date = m["scheduled_date"] or ""
                return f"{rnd} | {p1} vs {p2}" + (f" ({date})" if date else "")

            match_options = {match_label(m): m["id"] for m in sorted(pending, key=lambda x: (x["round_number"], x["match_position"]))}
            sel_label = st.selectbox("Selecciona partido", list(match_options.keys()))
            sel_match_id = match_options[sel_label]
            sel_match = get_match(sel_match_id)

            p1n = player_name(sel_match["player1_id"], players_dict)
            p2n = player_name(sel_match["player2_id"], players_dict)

            st.markdown(f"### {p1n}  vs  {p2n}")

            best_of = t["best_of"]
            tf = t["third_set_format"]
            tp = t["tiebreak_points"]

            with st.form("result_form"):
                st.markdown("**Introducir resultado** (deja vacío los sets no jugados)")

                # Date
                existing_date = sel_match.get("scheduled_date")
                fecha = st.date_input(
                    "Fecha del partido",
                    value=datetime.date.fromisoformat(existing_date) if existing_date else datetime.date.today(),
                )

                sets_data = []
                cols = st.columns(best_of)
                for s in range(1, best_of + 1):
                    with cols[s - 1]:
                        is_third = s == best_of
                        if is_third and tf == "super_tiebreak":
                            label = f"Set {s} (Super TB a {tp})"
                            max_v = max(tp + 10, 25)
                        else:
                            label = f"Set {s}"
                            max_v = 99
                        st.markdown(f"**{label}**")
                        v1 = st.number_input(
                            p1n[:20], min_value=0, max_value=max_v,
                            value=sel_match.get(f"set{s}_p1") or 0,
                            key=f"s{s}_p1",
                        )
                        v2 = st.number_input(
                            p2n[:20], min_value=0, max_value=max_v,
                            value=sel_match.get(f"set{s}_p2") or 0,
                            key=f"s{s}_p2",
                        )
                        sets_data.append((v1, v2))

                submitted = st.form_submit_button("💾 Guardar resultado")

            if submitted:
                # Build temporary match dict for winner determination
                tmp = {
                    "player1_id": sel_match["player1_id"],
                    "player2_id": sel_match["player2_id"],
                }
                for s, (v1, v2) in enumerate(sets_data, 1):
                    tmp[f"set{s}_p1"] = v1
                    tmp[f"set{s}_p2"] = v2

                winner_id, sp1, sp2 = determine_winner(tmp, t)
                if winner_id is None:
                    st.error(f"Resultado inválido: verifica los marcadores ({sp1} sets - {sp2} sets).")
                else:
                    s1p1, s1p2 = sets_data[0] if len(sets_data) > 0 else (None, None)
                    s2p1, s2p2 = sets_data[1] if len(sets_data) > 1 else (None, None)
                    s3p1, s3p2 = sets_data[2] if len(sets_data) > 2 else (None, None)

                    update_match_result(
                        sel_match_id,
                        s1p1, s1p2, s2p1, s2p2, s3p1, s3p2,
                        winner_id,
                        scheduled_date=fecha.isoformat(),
                    )
                    advance_winner(tid, sel_match_id, winner_id)
                    winner_n = player_name(winner_id, players_dict)
                    st.success(f"✅ Resultado guardado. Ganador: **{winner_n}**")
                    st.rerun()

        # Editar resultados ya guardados
        if completed:
            st.divider()
            with st.expander("✏️ Editar resultado existente"):
                comp_options = {
                    (lambda m: f"{round_name(m['round_number'], total_rounds)} | "
                               f"{player_name(m['player1_id'], players_dict)} vs "
                               f"{player_name(m['player2_id'], players_dict)}")(m): m["id"]
                    for m in sorted(completed, key=lambda x: (x["round_number"], x["match_position"]))
                }
                sel_comp_label = st.selectbox("Partido completado", list(comp_options.keys()), key="edit_comp")
                sel_comp_id = comp_options[sel_comp_label]
                sel_comp = get_match(sel_comp_id)
                p1n_e = player_name(sel_comp["player1_id"], players_dict)
                p2n_e = player_name(sel_comp["player2_id"], players_dict)

                with st.form("edit_result_form"):
                    existing_date_e = sel_comp.get("scheduled_date")
                    fecha_e = st.date_input(
                        "Fecha",
                        value=datetime.date.fromisoformat(existing_date_e) if existing_date_e else datetime.date.today(),
                        key="edit_date",
                    )
                    sets_data_e = []
                    cols_e = st.columns(best_of)
                    for s in range(1, best_of + 1):
                        with cols_e[s - 1]:
                            is_third = s == best_of
                            if is_third and tf == "super_tiebreak":
                                label = f"Set {s} (Super TB a {tp})"
                                max_v = max(tp + 10, 25)
                            else:
                                label = f"Set {s}"
                                max_v = 99
                            st.markdown(f"**{label}**")
                            v1_e = st.number_input(
                                p1n_e[:20], min_value=0, max_value=max_v,
                                value=sel_comp.get(f"set{s}_p1") or 0,
                                key=f"es{s}_p1",
                            )
                            v2_e = st.number_input(
                                p2n_e[:20], min_value=0, max_value=max_v,
                                value=sel_comp.get(f"set{s}_p2") or 0,
                                key=f"es{s}_p2",
                            )
                            sets_data_e.append((v1_e, v2_e))

                    edit_submitted = st.form_submit_button("💾 Actualizar resultado")

                if edit_submitted:
                    tmp_e = {
                        "player1_id": sel_comp["player1_id"],
                        "player2_id": sel_comp["player2_id"],
                    }
                    for s, (v1, v2) in enumerate(sets_data_e, 1):
                        tmp_e[f"set{s}_p1"] = v1
                        tmp_e[f"set{s}_p2"] = v2

                    winner_id_e, sp1_e, sp2_e = determine_winner(tmp_e, t)
                    if winner_id_e is None:
                        st.error("Resultado inválido.")
                    else:
                        s1p1_e, s1p2_e = sets_data_e[0] if len(sets_data_e) > 0 else (None, None)
                        s2p1_e, s2p2_e = sets_data_e[1] if len(sets_data_e) > 1 else (None, None)
                        s3p1_e, s3p2_e = sets_data_e[2] if len(sets_data_e) > 2 else (None, None)

                        update_match_result(
                            sel_comp_id,
                            s1p1_e, s1p2_e, s2p1_e, s2p2_e, s3p1_e, s3p2_e,
                            winner_id_e,
                            scheduled_date=fecha_e.isoformat(),
                        )
                        # Re-advance winner in case result changed
                        advance_winner(tid, sel_comp_id, winner_id_e)
                        winner_n_e = player_name(winner_id_e, players_dict)
                        st.success(f"✅ Resultado actualizado. Ganador: **{winner_n_e}**")
                        st.rerun()

    # ── Players sub-tab ────────────────────────────────────────────────────────
    with tab_jugadores:
        st.subheader("Editar jugadores")
        st.caption(
            "Puedes corregir nombres y marcar jugadores como BYE. "
            "Al marcar como BYE, el partido de 1ª Ronda se resolverá automáticamente."
        )

        all_players = get_players(tid)
        if not all_players:
            st.info("No hay jugadores en este torneo.")
        else:
            # Show players in pairs (each pair = one R1 match)
            for i in range(0, len(all_players), 2):
                p1 = all_players[i]
                p2 = all_players[i + 1] if i + 1 < len(all_players) else None
                match_num = i // 2 + 1

                with st.expander(
                    f"Partido R1 #{match_num}: {p1['name']} vs {p2['name'] if p2 else '—'}",
                    expanded=False,
                ):
                    for p in ([p1] + ([p2] if p2 else [])):
                        st.markdown(f"**Jugador #{p['id']}**")
                        col_name, col_bye, col_save = st.columns([3, 1, 1])
                        with col_name:
                            new_name = st.text_input(
                                "Nombre",
                                value=p["name"],
                                key=f"pname_{p['id']}",
                                label_visibility="collapsed",
                            )
                        with col_bye:
                            new_bye = st.checkbox(
                                "BYE",
                                value=bool(p["is_bye"]),
                                key=f"pbye_{p['id']}",
                            )
                        with col_save:
                            if st.button("Guardar", key=f"psave_{p['id']}"):
                                final_name = "BYE" if new_bye else new_name.strip() or p["name"]
                                update_player(p["id"], final_name, new_bye)
                                # If the BYE status changed, re-resolve the R1 match
                                match = get_match_for_player(tid, p["id"], round_number=1)
                                if match and match["status"] != "completed":
                                    apply_bye_to_match(tid, match["id"])
                                st.success(f"Guardado: **{final_name}**")
                                st.rerun()
                        st.divider()

    # ── Format sub-tab ─────────────────────────────────────────────────────────
    with tab_fmt:
        st.subheader("Configuración del formato")
        with st.form("format_form"):
            best_of_new = st.selectbox(
                "Mejor de",
                [3, 5],
                index=0 if t["best_of"] == 3 else 1,
                format_func=lambda x: f"{x} sets",
            )
            third_set_new = st.selectbox(
                "Tercer set",
                ["super_tiebreak", "full_set"],
                index=0 if t["third_set_format"] == "super_tiebreak" else 1,
                format_func=lambda x: "Super Tiebreak" if x == "super_tiebreak" else "Set completo",
            )
            tp_new = st.number_input(
                "Puntos del super tiebreak",
                min_value=6, max_value=20,
                value=t["tiebreak_points"],
            )
            if st.form_submit_button("Guardar formato"):
                update_tournament_format(tid, best_of_new, third_set_new, int(tp_new))
                st.success("Formato actualizado.")
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# Tab: Nuevo Torneo
# ═══════════════════════════════════════════════════════════════════════════════

def tab_nuevo_torneo():
    st.header("Crear nuevo torneo")

    # Step state
    if "nuevo_step" not in st.session_state:
        st.session_state.nuevo_step = 1
    if "ocr_names" not in st.session_state:
        st.session_state.ocr_names = []
    if "pending_tournament_config" not in st.session_state:
        st.session_state.pending_tournament_config = {}

    step = st.session_state.nuevo_step

    # ── Step 1: Upload draw ───────────────────────────────────────────────────
    if step == 1:
        st.subheader("Paso 1: Subir imagen del cuadro")
        st.info(
            "Sube una imagen (JPG/PNG) o PDF con el cuadro del torneo. "
            "Se usará OCR para extraer los nombres de los jugadores automáticamente."
        )

        nombre = st.text_input("Nombre del torneo", placeholder="Absolut Masculí 2025")
        password = st.text_input(
            "Contraseña de administrador",
            type="password",
            value=DEFAULT_ADMIN_PASSWORD,
            help=f"Contraseña por defecto: {DEFAULT_ADMIN_PASSWORD}",
        )
        password2 = st.text_input("Confirmar contraseña", type="password")

        uploaded = st.file_uploader(
            "Cuadro del torneo",
            type=["jpg", "jpeg", "png", "pdf"],
            help="Imagen o PDF con el cuadro de draw",
        )

        col1, col2 = st.columns(2)
        with col1:
            best_of = st.selectbox("Formato", [3, 5], format_func=lambda x: f"Mejor de {x}")
        with col2:
            third_set = st.selectbox(
                "Tercer set",
                ["super_tiebreak", "full_set"],
                format_func=lambda x: "Super Tiebreak" if x == "super_tiebreak" else "Set completo",
            )
        tb_points = st.number_input("Puntos super tiebreak", 6, 20, value=10)

        if st.button("Extraer jugadores con OCR →", type="primary"):
            if not nombre.strip():
                st.error("Introduce un nombre para el torneo.")
                return
            if not password:
                st.error("La contraseña no puede estar vacía.")
                return
            if password != password2:
                st.error("Las contraseñas no coinciden.")
                return
            if uploaded is None:
                st.error("Sube una imagen o PDF del cuadro.")
                return

            with st.spinner("Ejecutando OCR... puede tardar unos segundos."):
                from ocr_utils import extract_players
                file_bytes = uploaded.read()
                names = extract_players(file_bytes, uploaded.name)

            if not names:
                st.warning(
                    "No se pudo extraer ningún nombre. "
                    "Puedes introducir los jugadores manualmente en el siguiente paso."
                )
                names = []

            st.session_state.ocr_names = names
            st.session_state.pending_tournament_config = {
                "nombre": nombre.strip(),
                "password": password,
                "best_of": best_of,
                "third_set": third_set,
                "tb_points": int(tb_points),
                "draw_filename": uploaded.name,
            }
            st.session_state.nuevo_step = 2
            st.rerun()

    # ── Step 2: Confirm / edit player list ────────────────────────────────────
    elif step == 2:
        cfg = st.session_state.pending_tournament_config
        st.subheader(f"Paso 2: Confirmar jugadores — {cfg['nombre']}")

        st.info(
            "Revisa y edita los nombres extraídos. "
            "Escribe **BYE** para las posiciones vacías. "
            "El número total de jugadores debe ser una potencia de 2 (16, 32, 64...)."
        )

        raw_names = st.session_state.ocr_names
        default_text = "\n".join(raw_names) if raw_names else ""

        players_text = st.text_area(
            "Jugadores (uno por línea, en orden del cuadro)",
            value=default_text,
            height=400,
            help="Ordena los jugadores tal como aparecen en el cuadro, de arriba a abajo.",
        )

        names_list = [n.strip() for n in players_text.splitlines() if n.strip()]
        n = len(names_list)
        is_power_of_2 = n > 0 and (n & (n - 1)) == 0

        st.markdown(f"**{n} jugadores detectados**")
        if not is_power_of_2 and n > 0:
            st.warning(
                f"{n} no es una potencia de 2. "
                f"El cuadro más cercano es para {2**math.ceil(math.log2(n))} jugadores. "
                "Añade BYEs al final hasta completar."
            )
        elif is_power_of_2:
            st.success(f"✅ Cuadro válido para {n} jugadores ({int(math.log2(n))} rondas)")

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("← Volver", use_container_width=True):
                st.session_state.nuevo_step = 1
                st.rerun()
        with col_b:
            crear_disabled = not is_power_of_2
            if st.button("Crear torneo →", type="primary", disabled=crear_disabled, use_container_width=True):
                total_rounds = int(math.log2(n))
                tid = create_tournament(
                    cfg["nombre"],
                    cfg["password"],
                    best_of=cfg["best_of"],
                    third_set_format=cfg["third_set"],
                    tiebreak_points=cfg["tb_points"],
                    total_rounds=total_rounds,
                    draw_image_path=cfg["draw_filename"],
                )
                initialise_bracket(tid, names_list)

                # Log in as admin for this tournament
                st.session_state.admin_tournament_id = tid
                st.session_state.selected_tournament_id = tid

                # Reset wizard
                st.session_state.nuevo_step = 1
                st.session_state.ocr_names = []
                st.session_state.pending_tournament_config = {}

                st.success(f"✅ Torneo **{cfg['nombre']}** creado con {n} jugadores.")
                st.balloons()
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    sidebar()

    tid = st.session_state.selected_tournament_id

    if tid is None:
        # No tournaments exist yet — show only the creation tab
        st.title("🎾 Cuadro de Tenis")
        st.markdown("Bienvenido. Crea tu primer torneo para comenzar.")
        tab_nuevo_torneo()
        return

    tab_cuadro_ui, tab_partidos_ui, tab_admin_ui, tab_nuevo_ui = st.tabs([
        "🏆 Cuadro",
        "📋 Partidos",
        "🔧 Admin",
        "➕ Nuevo Torneo",
    ])

    with tab_cuadro_ui:
        tab_cuadro(tid)

    with tab_partidos_ui:
        tab_partidos(tid)

    with tab_admin_ui:
        tab_admin(tid)

    with tab_nuevo_ui:
        tab_nuevo_torneo()


if __name__ == "__main__":
    main()
