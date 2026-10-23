# GitHub setup (one-time)

Repo: `mshauri`. Protection for `main` is defined as code in
`.github/rules/branch-protection.json`.

## Rules applied to `main`

| Rule | Effect | Why |
|---|---|---|
| Pull request required | No direct pushes to `main` | One PR per build step |
| Approvals: 0 | You can merge your own PR | Solo dev. A required approval would block you. Raise to 1 when a collaborator joins. |
| Dismiss stale reviews on push | New commits invalidate old approvals | Safe once approvals are used |
| Resolve review threads | Open comments block merge | Nothing gets lost |
| Required checks: `checks`, `docker` | CI must pass before merge | Names match the job IDs in `ci.yml` |
| Up-to-date branch (strict) | PR must be rebased on latest `main` | Avoids merging against stale code |
| Linear history | Squash or rebase merges only | Clean history, easy rollback by SHA |
| Block force-push and deletion | `main` cannot be rewritten or removed | Protects the deploy source |
| No bypass actors | Applies to admins too | Pipeline guarantees hold for everyone |

## Apply it

Option A, CLI (recommended):
```bash
gh auth login                      # once
./scripts/branch-protection.sh   # idempotent: creates or updates
```

Option B, UI: Settings → Rules → Rulesets → New ruleset → Import a ruleset →
select `.github/rules/branch-protection.json`.

## Prerequisites and gotchas

1. **Push `main` and let CI run once first.** GitHub only offers status checks it has
   seen. Push a branch, open a PR, let `checks` and `docker` finish, then apply the rules.
2. **Private repo on a free plan:** rulesets and branch protection are not enforced on
   private repos without GitHub Pro/Team. Either upgrade or make the repo public.
3. **Rename safety:** if you rename a job in `ci.yml`, update `required_status_checks`
   in the JSON and re-run the script, or merges will block forever.
4. **Locked out by your own rules?** Settings → Rules → Rulesets → set enforcement to
   "Disabled", fix, then re-enable.

## Daily workflow
```bash
git switch -c step-1-models
# work, commit
git push -u origin step-1-models
gh pr create --fill
gh pr merge --squash --delete-branch   # after checks pass
git switch main && git pull
```
Also enable: Settings → General → "Automatically delete head branches".
