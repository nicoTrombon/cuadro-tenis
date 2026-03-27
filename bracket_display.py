"""
HTML/CSS bracket renderer.
Generates a scrollable, responsive single-elimination bracket.
"""
from __future__ import annotations
import math


UNIT = 38       # px height per player slot
COL_W = 195     # px width of each round column
COL_GAP = 28    # px gap between columns (used for connector lines)
HEADER_H = 44   # px height of round header row


def _round_name(round_num: int, total_rounds: int) -> str:
    """Map round number to Spanish display name."""
    delta = total_rounds - round_num
    if delta == 0:
        return "Final"
    if delta == 1:
        return "Semifinales"
    if delta == 2:
        return "Cuartos de Final"
    if delta == 3:
        return "Octavos de Final"
    # Earlier rounds: count from 1
    return f"{round_num}ª Ronda"


def _score_label(match: dict) -> tuple[str, str]:
    """Return (score_p1, score_p2) set-by-set strings, e.g. '6-4 7-5', '4-6 5-7'."""
    sets_p1, sets_p2 = [], []
    for s in range(1, 4):
        v1 = match.get(f"set{s}_p1")
        v2 = match.get(f"set{s}_p2")
        if v1 is None or v2 is None:
            break
        sets_p1.append(f"{v1}-{v2}")
        sets_p2.append(f"{v2}-{v1}")
    return " ".join(sets_p1), " ".join(sets_p2)


def render_bracket(matches_by_round: dict, players_dict: dict, total_rounds: int) -> str:
    """
    Render the full bracket as an HTML string ready for st.components.v1.html().

    matches_by_round : {round_number: [match_dict, ...]}
    players_dict     : {player_id: player_dict}
    total_rounds     : int
    """
    total_players = 2 ** total_rounds
    canvas_h = HEADER_H + total_players * UNIT + 20
    canvas_w = total_rounds * (COL_W + COL_GAP) + COL_W  # winner name column at end

    slots: list[str] = []   # individual positioned divs
    lines: list[str] = []   # SVG polyline elements (collected per gap section)

    for round_num in range(1, total_rounds + 1):
        col_x = (round_num - 1) * (COL_W + COL_GAP)

        # ── Round header ──────────────────────────────────────────────────────
        rname = _round_name(round_num, total_rounds)
        slots.append(
            f'<div class="rh" style="left:{col_x}px;top:0;width:{COL_W}px;">{rname}</div>'
        )

        round_matches = sorted(
            matches_by_round.get(round_num, []),
            key=lambda m: m["match_position"],
        )

        for match in round_matches:
            pos = match["match_position"]

            # Y positions (absolute, accounting for header)
            y1 = HEADER_H + pos * (2 ** round_num) * UNIT + (2 ** (round_num - 1) - 1) * UNIT
            y2 = y1 + UNIT

            p1 = players_dict.get(match.get("player1_id"))
            p2 = players_dict.get(match.get("player2_id"))
            winner_id = match.get("winner_id")

            def player_class(p, wid):
                if p is None:
                    return "tbd"
                if p["is_bye"]:
                    return "bye"
                if wid and p["id"] == wid:
                    return "win"
                if wid and p["id"] != wid:
                    return "lose"
                return ""

            p1_cls = player_class(p1, winner_id)
            p2_cls = player_class(p2, winner_id)

            p1_name = (p1["name"] if p1 else "Por definir") if not (p1 and p1["is_bye"]) else "BYE"
            p2_name = (p2["name"] if p2 else "Por definir") if not (p2 and p2["is_bye"]) else "BYE"

            sc1, sc2 = _score_label(match)

            score_html1 = f'<span class="score">{sc1}</span>' if sc1 else ""
            score_html2 = f'<span class="score">{sc2}</span>' if sc2 else ""

            slots.append(
                f'<div class="ps {p1_cls}" style="left:{col_x}px;top:{y1}px;width:{COL_W}px;">'
                f'<span class="pname">{p1_name}</span>{score_html1}</div>'
            )
            slots.append(
                f'<div class="ps {p2_cls}" style="left:{col_x}px;top:{y2}px;width:{COL_W}px;'
                f'border-top:none;">'
                f'<span class="pname">{p2_name}</span>{score_html2}</div>'
            )

            # ── Connector lines to next round ─────────────────────────────────
            if round_num < total_rounds:
                lx = col_x + COL_W          # start of gap
                mid1 = y1 + UNIT // 2       # centre of player 1 slot
                mid2 = y2 + UNIT // 2       # centre of player 2 slot
                cx = lx + COL_GAP // 2      # vertical line X
                next_y = (mid1 + mid2) / 2  # centre of next-round match

                lines.append(
                    f'<polyline points="{lx},{mid1} {cx},{mid1} {cx},{mid2} {lx},{mid2}" '
                    f'fill="none" stroke="#bbb" stroke-width="1.5"/>'
                )
                lines.append(
                    f'<line x1="{cx}" y1="{next_y}" x2="{lx+COL_GAP}" y2="{next_y}" '
                    f'stroke="#bbb" stroke-width="1.5"/>'
                )

    # ── Final winner box ──────────────────────────────────────────────────────
    final_matches = matches_by_round.get(total_rounds, [])
    if final_matches:
        fm = final_matches[0]
        winner_id = fm.get("winner_id")
        if winner_id and winner_id in players_dict:
            winner = players_dict[winner_id]
            wx = total_rounds * (COL_W + COL_GAP)
            wy = HEADER_H + (total_players // 2 - 1) * UNIT
            slots.append(
                f'<div class="champion" style="left:{wx}px;top:{wy}px;width:{COL_W}px;">'
                f'🏆 {winner["name"]}</div>'
            )

    css = f"""
    <style>
    body {{ margin:0; padding:0; font-family:'Segoe UI',Arial,sans-serif; }}
    .wrap {{
        overflow: auto;
        background: #f5f7fa;
        padding: 12px;
        border-radius: 10px;
        max-height: 680px;
    }}
    .bracket {{
        position: relative;
        width: {canvas_w}px;
        height: {canvas_h}px;
    }}
    .rh {{
        position: absolute;
        text-align: center;
        font-weight: 700;
        font-size: 12px;
        color: #1a5276;
        background: #d6eaf8;
        border-radius: 6px 6px 0 0;
        height: {HEADER_H - 4}px;
        line-height: {HEADER_H - 4}px;
        border: 1px solid #aed6f1;
    }}
    .ps {{
        position: absolute;
        height: {UNIT}px;
        line-height: {UNIT}px;
        padding: 0 7px;
        font-size: 12px;
        border: 1px solid #ccc;
        background: #fff;
        box-sizing: border-box;
        overflow: hidden;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }}
    .pname {{
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        flex: 1;
        min-width: 0;
    }}
    .score {{
        font-size: 10px;
        color: #666;
        margin-left: 4px;
        flex-shrink: 0;
        white-space: nowrap;
    }}
    .ps.win  {{ background:#eafaf1; font-weight:700; border-color:#58d68d; }}
    .ps.win .score {{ color:#1e8449; }}
    .ps.lose {{ color:#aaa; background:#fafafa; }}
    .ps.lose .score {{ color:#bbb; }}
    .ps.bye  {{ color:#ccc; font-style:italic; background:#fafafa; }}
    .ps.tbd  {{ color:#aaa; font-style:italic; }}
    .svg-lines {{
        position: absolute;
        left: 0;
        top: 0;
        width: {canvas_w}px;
        height: {canvas_h}px;
        pointer-events: none;
    }}
    .champion {{
        position: absolute;
        background: #fef9e7;
        border: 2px solid #f1c40f;
        border-radius: 6px;
        padding: 6px 10px;
        font-weight: 700;
        font-size: 13px;
        color: #7d6608;
        white-space: nowrap;
    }}
    </style>
    """

    svg_block = (
        f'<svg class="svg-lines">'
        + "".join(lines)
        + "</svg>"
    )

    html = (
        css
        + '<div class="wrap"><div class="bracket">'
        + svg_block
        + "".join(slots)
        + "</div></div>"
    )
    return html
