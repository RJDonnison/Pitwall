# F1 Fantasy project instructions

- `plan/current.md` is the product roadmap and is intentionally ignored by Git.
- Work on V1 only until explicitly asked to implement V2. V1 recommends teams in the CLI; it never logs in or changes an F1 account.
- Treat Fantasy prices as live data: fetch them anew for every recommendation; fail if prices or roster data cannot be verified.
- Account for both sprint and regular weekends, the full seven selections, the 2× Boost, the budget, and net transfers.
- Historical model inputs must precede the predicted weekend. Do not use current weekend results as predictions.
- The user requested a commit after each completed feature. Check status, diff and recent log before every commit, stage only intended files, and run relevant checks.
