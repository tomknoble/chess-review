# Chess Review

A free, do-it-yourself version of Chess.com's Game Review. Put your games in `games/`,
and it analyses them with Stockfish and builds an interactive page with:

- the board, with the engine's best move drawn as an arrow
- every move marked as best / good / inaccuracy / mistake / blunder
- an evaluation graph (click it to jump to that moment)
- a plain-language reason for each mistake (hanging piece, missed tactic, threw away a win, ...)
- **puzzle mode**: your biggest mistakes turned into "find the better move" puzzles
- an **Overview** page with your record, accuracy in wins vs losses, how often you
  fail to convert winning positions, and which kinds of mistakes you make most

## Setup (one time, about 5 minutes, no installs)

1. Create a **public** repository on GitHub (Pages is free for public repos) and upload everything in this folder.
2. Edit `config.json` and put your Chess.com username (it decides which side is "you").
3. In the repo: **Settings -> Pages -> Build and deployment -> Source: GitHub Actions**.
4. Open the **Actions** tab and run **Review my games** once (or just push a change). 
   When it finishes (a few minutes), your report is at `https://YOUR-NAME.github.io/REPO-NAME/`.

## Every time you want a new review

1. On Chess.com: **Games -> Archive**, tick the games, press **Download** (you get a `.pgn` file).
   For a single game: open it, **Share -> PGN -> Copy**.
2. On GitHub: open the `games/` folder -> **Add file -> Upload files** (or create a new
   `.pgn` file and paste the text) -> **Commit**.
3. The workflow runs by itself. Refresh your report page after a few minutes.
   Games analysed before are remembered, so only the new ones take time.

Duplicate games across files are ignored, so you can upload the same month again and again.

## Run it on your own computer instead

```
pip install -r requirements.txt
# install Stockfish:  Windows: stockfishchess.org/download   macOS: brew install stockfish   Linux: sudo apt install stockfish
python review.py                      # add  --engine "C:\path\to\stockfish.exe"  if it is not found
```
Then open `site/index.html` in your browser. Use `--depth 18` for deeper (slower) analysis.

## Notes

- Moves are labelled from the change in win probability (the same idea Lichess uses): a drop of
  5 / 10 / 15 percentage points is an inaccuracy / mistake / blunder.
- The "why" text is generated from the engine's analysis. It is a pointer, not a coach, so
  look at the engine line too.
- Your games are public on Chess.com anyway, but remember that a public repo is public.
