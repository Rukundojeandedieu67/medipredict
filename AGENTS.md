# Repository rules

- Write complete, working code. Do not leave TODOs or stubs.
- Use product voice only. Never mention hackathons or competitions in code, UI, comments, or documentation. NISR may appear only as a named data source in provenance and on the data-sources screen. Keep `AI_DISCLOSURE.md` unchanged.
- Never invent statistics. Every external number must be traceable in `ml_engine/datasets/PROVENANCE.md`. Synthetic data must carry `is_synthetic=true` and be labeled synthetic wherever shown.
- After every task, run the relevant command (`train`, `pytest`, or `npm run build`) and fix errors. Report commands and their real output. Never claim something works without running it.
- List every import in its matching requirements file.
- Never compute labels from feature columns. Never use random train/test splits on time-series data.
- End each phase with a “Phase report” containing files changed, commands run with output, and known limitations. Then stop and wait.
