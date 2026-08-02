# Contributing

Branch protection is not available on our repository under the current plan, so these
rules are enforced by us rather than by GitHub. Please follow them for every change.

> **Never commit or push directly to `main`.**
> **Never approve your own pull request.**

This process applies to every repository change — code, notebooks, tests, framework
files and technical documentation.

## Workflow

1. Pick an issue from the project board and assign yourself.
2. Create a branch from `main` for that task.
3. Do the work, committing in small, meaningful steps.
4. Test or verify your changes.
5. Open a pull request into `main`, linking the issue and explaining what changed and why.
6. Get approval from at least one other team member.
7. Resolve all review comments and conversations.
8. Squash and merge, then delete the branch.

## Branch names

    <type>/<issue-number>-<short-description>

Types:

- `feat` — new work or functionality
- `docs` — documentation or writing
- `fix` — correcting a defect or error
- `chore` — tooling, configuration or project setup

Examples:

    chore/1-repository-structure
    docs/4-claim-definition
    feat/7-load-corpus

## Commits

Keep commits small and describe what changed:

    docs: add first draft of claim definition
    chore(repo): add folder structure and README

Do not mix unrelated changes into one commit.

## Pull requests

- Link the issue it closes, for example: `Closes #1`.
- Explain what you changed and why. If you made a judgement call, say what you
  considered and rejected.
- Keep it small enough to review properly. If it is very large, consider splitting it.
- Review the reasoning, not just the syntax — disagreeing with an approach is a valid
  and useful review comment.
- Discuss disagreements in the pull request rather than in direct messages, so the
  reasoning is recorded.

## Do not commit

- Anything in `.env`, or containing passwords, API keys, tokens or other secrets
- Confidential client data or personal information, unless storage and access have been
  explicitly approved
- `.DS_Store`
- Notebook output cells — clear them before committing

## Done means

- The work has been tested or verified
- Reviewed and approved by another team member
- All review comments and conversations resolved
- Merged into `main` and the branch deleted
- The related issue is closed
