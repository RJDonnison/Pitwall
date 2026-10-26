# F1 Fantasy project instructions

- `plan/current.md` is the product roadmap and is intentionally ignored by Git.
- V1 recommends teams in the CLI. V2 trains forecast weights with chronological validation. V3 plans account changes and scheduled submission only for the user's explicitly requested one-team setup; V4 F1 Predict is roadmap-only until explicitly requested for implementation.
- Treat Fantasy prices as live data: fetch them anew for every recommendation; fail if prices or roster data cannot be verified.
- Account for both sprint and regular weekends, the full seven selections, the 2× Boost, the budget, and net transfers.
- Historical model inputs must precede the predicted weekend. Do not use current weekend results as predictions.
- The user requested a commit after each completed feature. Check status, diff and recent log before every commit, stage only intended files, and run relevant checks.
