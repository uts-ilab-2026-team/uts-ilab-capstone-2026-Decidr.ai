# Push this project to a personal GitHub repository

Keep the repository private until the team, client and subject requirements permit public
release. Owning the GitHub repository does not change the project authorship recorded in the
README.

## Recommended reviewed-import workflow

1. Create a **private** GitHub repository and initialise it with a README so that `main` exists.
2. Open a terminal in this project folder.
3. Replace the two placeholders below with your GitHub username and repository name.
4. Create an import branch, inspect the staged files, then push the branch:

```bash
git init
git remote add origin https://github.com/<your-username>/<repository-name>.git
git fetch origin
git switch -c chore/github-ready-import origin/main
git add .
git status --short
git commit -m "chore: import reviewed Decidr prototype"
git push -u origin chore/github-ready-import
```

5. Open a pull request into `main`, request a teammate review, and merge only after the quality
   workflow passes.

## Before pushing

- Confirm that `data/`, generated reports, `.env`, credentials and client-confidential files are
  not listed by `git status`.
- Keep `uv.lock` committed so the environment is reproducible.
- Do not change frozen portfolio inputs or checksums unless the team follows the documented
  versioned-amendment process.
