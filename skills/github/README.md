# GitHub skill

- `github_read_file(repo, path)` — read any public repo file (60 req/hr, no key)
- `github_list_issues(repo)` — open issues, PRs excluded
- `github_create_issue(repo, title, body)` — needs `github_token` in
  secrets.local.yaml (or GITHUB_TOKEN env), same secrets file the app uses
