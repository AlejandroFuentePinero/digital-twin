# Sentinel is a static page built from one full read, not a live Gradio app

Until #61 Sentinel was a Gradio app: launched once, it read the log, cached it for the session, and rendered panels, charts and accordions. The #61 audit found its arithmetic right but its data path quiet under failure: a failed listing or day download became zeros with healthy marks, Refresh never re-read the log, and the log-writer panel always showed the local placeholder in production. The owner then judged the presentation on two working prototypes and signed off a calm, table-first page with a detail window per table, which Gradio's components cannot express without fighting them.

So Sentinel is now a page builder. `uv run python src/sentinel.py` reads the whole log, builds a page model (`build_page`: every figure as plain data), writes one static HTML file to `data/logs/sentinel.html` and opens it. Refresh is running it again. The read is all or nothing: `HFLogReader` raises `LogReadError` on any listing or download failure, and the page then shows "Log read failed" with the reason and no numbers. Unreadable lines and repeated records are counted on the page. The browser-side code only lays out the data; it computes nothing that `scripts/sentinel_recompute.py` could not reproduce.

## Considered options

- **Keep Gradio and restyle it.** Rejected: the signed-off layout (a sticky detail window beside a clickable table, sortable columns, one page of tabs without accordions) needs custom HTML and JavaScript that Gradio sanitises out of `gr.HTML`, and the session-long cache was the root of the stale-Refresh failure.
- **A small local server that rebuilds on a button.** Rejected as machinery nobody asked for: a rebuild is one command, and the control room's own pages work the same way.

## Consequences

- No live buttons. Refresh and Re-baseline are commands shown on the page (`uv run python src/sentinel.py`, `uv run python src/canary_runner.py --freeze-baseline`).
- The page file quotes visitors' questions, so it lives under the gitignored `data/logs/`.
- Sentinel is testable at one seam: `build_page` with the reader and the Hugging Face hub faked at the process boundary.
