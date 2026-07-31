# Contributing

## Workflow

1. Pick an issue from the project board and assign yourself
2. Create a branch off `main`
3. Do the work, commit as you go
4. Open a pull request
5. Get one teammate to review and approve
6. Merge, delete the branch

## Branch names

    <type>/<issue-number>-<short-description>

Types: `feat` (new work), `docs` (writing), `fix` (correcting something), `chore` (tooling, setup)

Examples:

    chore/1-repository-structure
    docs/4-claim-definition
    feat/7-load-corpus

## Commits

Keep them small and describe what changed:

    docs: add first draft of claim definition
    chore(repo): add folder structure and README

## Pull requests

- Link the issue it closes: `Closes #1`
- Explain what you did and why
- One approval from another team member before merging
- Squash and merge, then delete the branch

## Do not commit

- Anything in `.env` or with passwords or keys in it
- `.DS_Store`
- Notebook output cells - clear them first

## Done means

- Reviewed and approved by someone else
- Merged to `main`
- The issue is closed
