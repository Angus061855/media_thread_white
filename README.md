# media_thread_white

Threads scheduled publishing automation.

## Operations

- Publishing workflows are in `.github/workflows/`; their schedules use UTC.
- Keep existing schedules and manually disabled workflows unchanged during maintenance.
- Workflow success is not by itself proof that a post was published; inspect the publishing step when investigating delivery.
- Do not manually rerun publishing jobs solely to resolve inactivity warnings: doing so may duplicate posts.
- `refresh_token.yml` maintains the Threads credential. Check both the Threads response and GitHub secret-update response when refresh fails; never print credentials in logs or commit them.

## Scheduled workflow inactivity

GitHub may disable scheduled workflows in public repositories after 60 days without repository activity, even when scheduled runs continue. Review repository activity before that deadline; use GitHub's Enable workflow operation when needed. Preserve intentionally disabled workflows.

Reference: https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows

Maintenance reviewed: 2026-11-24. This documentation update does not change posting times, content, credentials, or workflow permissions.
