#!/usr/bin/env python3
"""
Chess game reviewer.

Reads every .pgn file in ./games, analyses each game with Stockfish, and writes a
self-contained interactive report to ./site/index.html (open it in any browser).

    python review.py                      # uses config.json for your username
    python review.py --depth 16           # deeper (slower) analysis
    python review.py --user mychessname   # override username

Needs: Python 3.9+, `pip install -r requirements.txt`, and Stockfish installed
(Ubuntu/Debian: sudo apt install stockfish | macOS: brew install stockfish |
Windows: download from stockfishchess.org and pass --engine path\\to\\stockfish.exe).
"""
import argparse, glob, hashlib, json, math, os, re, shutil, sys
import chess, chess.engine, chess.pgn, chess.svg

HERE = os.path.dirname(os.path.abspath(__file__))
VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
CAP = 1000  # centipawn cap used for mates / huge evals


def win_pct(cp):
    """Win probability (0-100) for the side whose centipawn score is `cp`."""
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def classify(loss, played_best):
    if played_best:
        return "best"
    if loss >= 15:
        return "blunder"
    if loss >= 10:
        return "mistake"
    if loss >= 5:
        return "inaccuracy"
    return "good"


def accuracy(loss):
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * loss) - 3.1669))


def find_engine(user_path):
    for p in [user_path, shutil.which("stockfish"), "/usr/games/stockfish", "/usr/local/bin/stockfish",
              "/opt/homebrew/bin/stockfish"]:
        if p and os.path.exists(p):
            return p
    sys.exit("Stockfish not found. Install it (see top of review.py) or pass --engine /path/to/stockfish")


def score_fields(board, info):
    """Return (cp white-POV capped, mate white-POV or None, pv list)."""
    if board.is_checkmate():
        return (-CAP if board.turn == chess.WHITE else CAP), 0, []
    if board.is_game_over():
        return 0, None, []
    s = info["score"].white()
    pv = info.get("pv", [])
    if s.is_mate():
        m = s.mate()
        return (CAP if m > 0 else -CAP), m, pv
    return max(-CAP, min(CAP, s.score())), None, pv


def capture_value(board, move):
    if board.is_en_passant(move):
        return 1
    p = board.piece_at(move.to_square)
    return VAL[p.piece_type] if p else 0


def material_lost_to(board_after, reply, already_won=0):
    """Net material (in pawns) the opponent wins with `reply` after our move,
    after crediting what our own move just captured (so even trades are not flagged)."""
    gain = capture_value(board_after, reply) - already_won
    if capture_value(board_after, reply) == 0:
        return 0
    capturer = board_after.piece_at(reply.from_square)
    us = not board_after.turn
    b2 = board_after.copy()
    b2.push(reply)
    risk = VAL[capturer.piece_type] if b2.is_attacked_by(us, reply.to_square) else 0
    return gain - risk


def explain(board, played, best, info0, info1, mover_cp0, mover_cp1, mate0, mate1, mover):
    """Plain-language reason for a flagged move. Returns (tag, text)."""
    sign = 1 if mover == chess.WHITE else -1
    best_san = board.san(best) if best else None
    won_by_move = capture_value(board, played)
    after = board.copy()
    after.push(played)
    mm0 = None if mate0 is None else sign * mate0   # + means we mate
    mm1 = None if mate1 is None else sign * mate1
    if mm1 is not None and mm1 < 0 and mm1 != 0:
        return "walked_mate", f"This allows a forced checkmate against you in {abs(mm1)}."
    if mm0 is not None and mm0 > 0 and not (mm1 is not None and mm1 > 0):
        return "missed_mate", f"You had a forced checkmate in {mm0} here ({best_san}) and missed it."
    reply = info1.get("pv", [None])[0] if info1.get("pv") else None
    if reply and not after.is_game_over():
        net = material_lost_to(after, reply, won_by_move)
        if net >= 2:
            return "hung", (f"This leaves material hanging: the opponent can reply {after.san(reply)} "
                            f"and win about {net} points of material.")
    if mover_cp0 >= 300 and mover_cp1 < 100:
        return "threw", (f"You were clearly winning and this gives most of it away. "
                         f"The safer move was {best_san}.")
    if best and (board.is_capture(best) or board.gives_check(best)):
        return "missed_tactic", f"A tactic was available: {best_san}."
    return "other", f"The engine preferred {best_san} here."


def analyse_game(game, engine, depth, user):
    h = game.headers
    moves = list(game.mainline_moves())
    board = game.board()
    start_fen = board.fen()

    # --- evaluate every position once
    boards, infos, fields = [], [], []
    b = game.board()
    for i in range(len(moves) + 1):
        boards.append(b.copy())
        info = {} if b.is_game_over() else engine.analyse(b, chess.engine.Limit(depth=depth))
        infos.append(info)
        fields.append(score_fields(b, info) if info or b.is_game_over() else (0, None, []))
        if i < len(moves):
            b.push(moves[i])

    my_color = None
    if user:
        if h.get("White", "").lower() == user.lower():
            my_color = chess.WHITE
        elif h.get("Black", "").lower() == user.lower():
            my_color = chess.BLACK

    plies = []
    for i, mv in enumerate(moves):
        bd = boards[i]
        mover = bd.turn
        sign = 1 if mover == chess.WHITE else -1
        cp0, mate0, pv0 = fields[i]
        cp1, mate1, pv1 = fields[i + 1]
        best = pv0[0] if pv0 else None
        w0, w1 = win_pct(sign * cp0), win_pct(sign * cp1)
        loss = max(0.0, w0 - w1)
        is_best = best is not None and mv == best
        cls = classify(loss, is_best)
        san = bd.san(mv)
        rec = {
            "s": san, "u": mv.uci(), "f": boards[i + 1].fen(),
            "c0": cp0, "m0": mate0, "c": cp1, "m": mate1,
            "k": cls, "l": round(loss, 1), "acc": round(accuracy(loss), 1),
            "col": "w" if mover == chess.WHITE else "b",
            "me": (my_color == mover) if my_color is not None else None,
        }
        if best is not None:
            rec["b"] = bd.san(best)
            rec["bu"] = best.uci()
            rec["ln"] = bd.variation_san(pv0[:5])
        if pv1 and not boards[i + 1].is_game_over():
            rec["rl"] = boards[i + 1].variation_san(pv1[:4])
        if cls in ("inaccuracy", "mistake", "blunder") and best is not None:
            tag, text = explain(bd, mv, best, infos[i], infos[i + 1], sign * cp0, sign * cp1, mate0, mate1, mover)
            rec["tg"], rec["w"] = tag, text
        plies.append(rec)

    result = h.get("Result", "*")
    outcome = None
    if my_color is not None:
        if result == "1/2-1/2":
            outcome = "D"
        elif result in ("1-0", "0-1"):
            outcome = "W" if (result == "1-0") == (my_color == chess.WHITE) else "L"

    def elo(tag):
        return h.get(tag, "?")
    my_is_white = my_color == chess.WHITE
    rec = {
        "white": h.get("White", "?"), "black": h.get("Black", "?"), "result": result,
        "date": h.get("Date", "?"), "tc": h.get("TimeControl", ""), "term": h.get("Termination", ""),
        "welo": elo("WhiteElo"), "belo": elo("BlackElo"),
        "mycolor": None if my_color is None else ("white" if my_is_white else "black"),
        "outcome": outcome,
        "opp": None if my_color is None else (h.get("Black") if my_is_white else h.get("White")),
        "start": start_fen, "plies": plies,
    }
    for side, name in (("w", "accw"), ("b", "accb")):
        mine = [p["acc"] for p in plies if p["col"] == side]
        rec[name] = round(sum(mine) / len(mine), 1) if mine else None
    return rec


def build_overview(games):
    ov = {"n": 0, "record": {"W": 0, "D": 0, "L": 0}, "by_color": {"white": {"W": 0, "D": 0, "L": 0},
          "black": {"W": 0, "D": 0, "L": 0}}, "acc": {}, "tags": {}, "thrown": [], "ahead": {"n": 0, "won": 0},
          "top": [], "per_game": {}}
    accs = {"W": [], "D": [], "L": []}
    top = []
    for gi, g in enumerate(games):
        o = g["outcome"]
        if o is None:
            continue
        ov["n"] += 1
        ov["record"][o] += 1
        ov["by_color"][g["mycolor"]][o] += 1
        me = "accw" if g["mycolor"] == "white" else "accb"
        if g[me] is not None:
            accs[o].append(g[me])
        peak, peak_ply = -9999, 0
        mine_moves = [(i, p) for i, p in enumerate(g["plies"]) if p["me"]]
        for i, p in mine_moves:
            sign = 1 if p["col"] == "w" else -1
            if sign * p["c0"] > peak:
                peak, peak_ply = sign * p["c0"], i + 1
            if "tg" in p:
                ov["tags"][p["tg"]] = ov["tags"].get(p["tg"], 0) + 1
            if p["k"] in ("mistake", "blunder"):
                top.append({"g": gi, "ply": i + 1, "loss": p["l"], "san": p["s"], "best": p.get("b"),
                            "opp": g["opp"], "date": g["date"], "tag": p.get("tg"), "k": p["k"]})
        if peak >= 300:
            ov["ahead"]["n"] += 1
            if o == "W":
                ov["ahead"]["won"] += 1
            else:
                ov["thrown"].append({"g": gi, "ply": peak_ply, "cp": peak, "opp": g["opp"], "o": o,
                                     "date": g["date"]})
    ov["acc"] = {k: (round(sum(v) / len(v), 1) if v else None) for k, v in accs.items()}
    top.sort(key=lambda x: -x["loss"])
    ov["top"] = top[:12]
    ov["thrown"].sort(key=lambda x: -x["cp"])
    return ov


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pgn", default=os.path.join(HERE, "games"), help="folder (or file) with PGN files")
    ap.add_argument("--out", default=os.path.join(HERE, "site"))
    ap.add_argument("--depth", type=int, default=None)
    ap.add_argument("--user", default=None)
    ap.add_argument("--engine", default=None)
    args = ap.parse_args()

    cfg = {}
    cfg_path = os.path.join(HERE, "config.json")
    if os.path.exists(cfg_path):
        cfg = json.load(open(cfg_path))
    user = args.user or cfg.get("username")
    depth = args.depth or cfg.get("depth", 14)
    skip_bots = cfg.get("skip_bot_games", True)

    files = [args.pgn] if os.path.isfile(args.pgn) else sorted(glob.glob(os.path.join(args.pgn, "*.pgn")))
    if not files:
        sys.exit(f"No .pgn files found in {args.pgn}")

    # read + de-duplicate games
    raw, seen = [], set()
    for fp in files:
        with open(fp, encoding="utf-8", errors="replace") as f:
            while True:
                g = chess.pgn.read_game(f)
                if g is None:
                    break
                h = g.headers
                key = (h.get("White"), h.get("Black"), h.get("Date"), h.get("EndTime"), h.get("UTCTime"),
                       h.get("Link"))
                if key in seen:
                    continue
                seen.add(key)
                if skip_bots and "bot" in h.get("Event", "").lower():
                    continue
                if len(list(g.mainline_moves())) < 6:
                    continue
                raw.append(g)
    def sort_key(g):
        # zero-pad the clock time so "9:38:40" sorts before "20:56:42"
        h = g.headers
        t = h.get("EndTime", h.get("UTCTime", "00:00:00")).split(" ")[0]
        return (h.get("Date", ""), ":".join(p.zfill(2) for p in t.split(":")))
    raw.sort(key=sort_key, reverse=cfg.get("newest_first", True))   # newest game first

    cache_dir = os.path.join(HERE, ".cache")
    os.makedirs(cache_dir, exist_ok=True)
    engine = None
    games = []
    try:
        for n, g in enumerate(raw, 1):
            blob = f"{g}|{depth}|{user}|v3"
            ck = os.path.join(cache_dir, hashlib.sha1(blob.encode()).hexdigest() + ".json")
            if os.path.exists(ck):
                games.append(json.load(open(ck)))
                print(f"[{n}/{len(raw)}] cached", flush=True)
                continue
            if engine is None:
                engine = chess.engine.SimpleEngine.popen_uci(find_engine(args.engine))
                engine.configure({"Threads": max(1, os.cpu_count() or 1), "Hash": 128})
            rec = analyse_game(g, engine, depth, user)
            json.dump(rec, open(ck, "w"))
            games.append(rec)
            print(f"[{n}/{len(raw)}] {rec['white']} vs {rec['black']} {rec['date']}", flush=True)
    finally:
        if engine:
            engine.quit()

    pieces = {k: re.sub(r' id="[^"]*"', "", v) for k, v in chess.svg.PIECES.items()}  # piece art (Cburnett, via python-chess)
    data = {"user": user, "depth": depth, "games": games, "overview": build_overview(games), "pieces": pieces}
    tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    html = tpl.replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":")))
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {os.path.join(args.out, 'index.html')}  ({len(games)} games)")


if __name__ == "__main__":
    main()
