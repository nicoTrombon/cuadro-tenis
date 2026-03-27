import sqlite3
import bcrypt
import os
import math

DB_PATH = os.path.join(os.path.dirname(__file__), "tennis.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS tournaments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        admin_password_hash TEXT NOT NULL,
        best_of INTEGER DEFAULT 3,
        third_set_format TEXT DEFAULT 'super_tiebreak',
        tiebreak_points INTEGER DEFAULT 10,
        total_rounds INTEGER NOT NULL,
        draw_image_path TEXT,
        status TEXT DEFAULT 'active'
    );

    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tournament_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        is_bye INTEGER DEFAULT 0,
        seed INTEGER,
        FOREIGN KEY (tournament_id) REFERENCES tournaments(id)
    );

    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tournament_id INTEGER NOT NULL,
        round_number INTEGER NOT NULL,
        match_position INTEGER NOT NULL,
        player1_id INTEGER,
        player2_id INTEGER,
        winner_id INTEGER,
        scheduled_date DATE,
        set1_p1 INTEGER,
        set1_p2 INTEGER,
        set2_p1 INTEGER,
        set2_p2 INTEGER,
        set3_p1 INTEGER,
        set3_p2 INTEGER,
        status TEXT DEFAULT 'pending',
        FOREIGN KEY (tournament_id) REFERENCES tournaments(id),
        FOREIGN KEY (player1_id) REFERENCES players(id),
        FOREIGN KEY (player2_id) REFERENCES players(id),
        FOREIGN KEY (winner_id) REFERENCES players(id)
    );
    """)
    conn.commit()
    conn.close()


# ── Tournaments ──────────────────────────────────────────────────────────────

def create_tournament(name, password, best_of=3, third_set_format="super_tiebreak",
                      tiebreak_points=10, total_rounds=6, draw_image_path=None):
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """INSERT INTO tournaments
           (name, admin_password_hash, best_of, third_set_format, tiebreak_points,
            total_rounds, draw_image_path)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (name, pw_hash, best_of, third_set_format, tiebreak_points,
         total_rounds, draw_image_path)
    )
    tid = c.lastrowid
    conn.commit()
    conn.close()
    return tid


def get_tournament(tournament_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM tournaments WHERE id=?", (tournament_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_tournaments():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM tournaments ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def verify_admin_password(tournament_id, password):
    t = get_tournament(tournament_id)
    if not t:
        return False
    return bcrypt.checkpw(password.encode(), t["admin_password_hash"].encode())


def update_tournament_format(tournament_id, best_of, third_set_format, tiebreak_points):
    conn = get_connection()
    conn.execute(
        "UPDATE tournaments SET best_of=?, third_set_format=?, tiebreak_points=? WHERE id=?",
        (best_of, third_set_format, tiebreak_points, tournament_id)
    )
    conn.commit()
    conn.close()


# ── Players ───────────────────────────────────────────────────────────────────

def add_player(tournament_id, name, is_bye=False, seed=None):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO players (tournament_id, name, is_bye, seed) VALUES (?, ?, ?, ?)",
        (tournament_id, name, 1 if is_bye else 0, seed)
    )
    pid = c.lastrowid
    conn.commit()
    conn.close()
    return pid


def get_players(tournament_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM players WHERE tournament_id=? ORDER BY id", (tournament_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_players_dict(tournament_id):
    """Returns {player_id: player_dict}"""
    return {p["id"]: p for p in get_players(tournament_id)}


# ── Matches ───────────────────────────────────────────────────────────────────

def create_match(tournament_id, round_number, match_position,
                 player1_id=None, player2_id=None, scheduled_date=None):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """INSERT INTO matches
           (tournament_id, round_number, match_position, player1_id, player2_id, scheduled_date)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (tournament_id, round_number, match_position, player1_id, player2_id, scheduled_date)
    )
    mid = c.lastrowid
    conn.commit()
    conn.close()
    return mid


def get_matches(tournament_id, round_number=None):
    conn = get_connection()
    if round_number is not None:
        rows = conn.execute(
            "SELECT * FROM matches WHERE tournament_id=? AND round_number=? ORDER BY match_position",
            (tournament_id, round_number)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM matches WHERE tournament_id=? ORDER BY round_number, match_position",
            (tournament_id,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_match(match_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_match_result(match_id, set1_p1, set1_p2, set2_p1, set2_p2,
                        set3_p1, set3_p2, winner_id, scheduled_date=None):
    conn = get_connection()
    conn.execute(
        """UPDATE matches SET
           set1_p1=?, set1_p2=?, set2_p1=?, set2_p2=?,
           set3_p1=?, set3_p2=?, winner_id=?, status='completed',
           scheduled_date=COALESCE(?, scheduled_date)
           WHERE id=?""",
        (set1_p1, set1_p2, set2_p1, set2_p2, set3_p1, set3_p2,
         winner_id, scheduled_date, match_id)
    )
    conn.commit()
    conn.close()


def update_match_date(match_id, scheduled_date):
    conn = get_connection()
    conn.execute("UPDATE matches SET scheduled_date=? WHERE id=?", (scheduled_date, match_id))
    conn.commit()
    conn.close()


def advance_winner(tournament_id, match_id, winner_id):
    """Place winner into the appropriate slot of the next-round match."""
    match = get_match(match_id)
    if not match:
        return
    round_num = match["round_number"]
    pos = match["match_position"]
    tournament = get_tournament(tournament_id)
    if round_num >= tournament["total_rounds"]:
        return  # Final – no next round

    next_round = round_num + 1
    next_pos = pos // 2
    slot = "player1_id" if pos % 2 == 0 else "player2_id"

    conn = get_connection()
    # Find or create the next-round match
    row = conn.execute(
        "SELECT id FROM matches WHERE tournament_id=? AND round_number=? AND match_position=?",
        (tournament_id, next_round, next_pos)
    ).fetchone()

    if row:
        conn.execute(
            f"UPDATE matches SET {slot}=? WHERE id=?",
            (winner_id, row["id"])
        )
    else:
        conn.execute(
            f"INSERT INTO matches (tournament_id, round_number, match_position, {slot}) VALUES (?,?,?,?)",
            (tournament_id, next_round, next_pos, winner_id)
        )
    conn.commit()
    conn.close()


# ── Tournament initialisation ─────────────────────────────────────────────────

def initialise_bracket(tournament_id, player_names):
    """
    Create all round-1 matches from an ordered player list.
    Handles BYEs and auto-advances walkovers.
    player_names: list of strings, 'BYE' for byes.
    """
    n = len(player_names)
    total_rounds = int(math.log2(n))

    # Insert players
    player_ids = []
    for name in player_names:
        is_bye = name.strip().upper() == "BYE"
        pid = add_player(tournament_id, name if not is_bye else "BYE", is_bye=is_bye)
        player_ids.append(pid)

    # Create round-1 matches
    for i in range(n // 2):
        p1_id = player_ids[2 * i]
        p2_id = player_ids[2 * i + 1]
        mid = create_match(tournament_id, 1, i, p1_id, p2_id)

        # Auto-resolve BYEs
        p1 = get_players_dict(tournament_id)[p1_id]
        p2 = get_players_dict(tournament_id)[p2_id]
        if p1["is_bye"] or p2["is_bye"]:
            winner_id = p2_id if p1["is_bye"] else p1_id
            conn = get_connection()
            conn.execute(
                "UPDATE matches SET winner_id=?, status='walkover' WHERE id=?",
                (winner_id, mid)
            )
            conn.commit()
            conn.close()
            advance_winner(tournament_id, mid, winner_id)

    # Update total_rounds in case it differs
    conn = get_connection()
    conn.execute("UPDATE tournaments SET total_rounds=? WHERE id=?", (total_rounds, tournament_id))
    conn.commit()
    conn.close()


# ── Score helpers ─────────────────────────────────────────────────────────────

def determine_winner(match, tournament):
    """
    Given match dict and tournament dict, return (winner_id, sets_p1, sets_p2).
    Returns (None, 0, 0) if result is invalid.
    """
    sets_p1, sets_p2 = 0, 0
    best_of = tournament["best_of"]
    sets_needed = (best_of + 1) // 2

    for s in range(1, best_of + 1):
        s1 = match.get(f"set{s}_p1")
        s2 = match.get(f"set{s}_p2")
        if s1 is None or s2 is None:
            break
        if s1 > s2:
            sets_p1 += 1
        elif s2 > s1:
            sets_p2 += 1
        if sets_p1 == sets_needed or sets_p2 == sets_needed:
            break

    if sets_p1 == sets_needed:
        return match["player1_id"], sets_p1, sets_p2
    elif sets_p2 == sets_needed:
        return match["player2_id"], sets_p1, sets_p2
    return None, sets_p1, sets_p2


def format_score(match):
    """Return a human-readable score string like '6-4 3-6 10-7'."""
    parts = []
    for s in range(1, 4):
        s1 = match.get(f"set{s}_p1")
        s2 = match.get(f"set{s}_p2")
        if s1 is not None and s2 is not None:
            parts.append(f"{s1}-{s2}")
    return " ".join(parts)
