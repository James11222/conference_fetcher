# conference_fetcher

Automates a weekly conference digest for the CADC recent meetings page.

## What it does

- Scrapes `https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/en/meetings/recent/`
- Reads filtering preferences from `preferences.md`
- Uses GitHub-hosted models to shortlist conference entries
- Avoids duplicate notifications by tracking previously emailed entries in `cache.md`
- Sends a weekly email summary on Monday mornings at 10:00 UTC through GitHub Actions

## Repository files

- `preferences.md`: write your conference preferences here
- `cache.md`: stores conferences that have already been emailed
- `conference_fetcher/`: Python pipeline code
- `.github/workflows/weekly_conference_digest.yml`: weekly automation

## GitHub Copilot / GitHub Models setup

Optional model variable:

- `GITHUB_MODEL` (defaults to `openai/gpt-4.1`)

Required workflow permissions and variables:

- `models: read` permission for the workflow `GITHUB_TOKEN`
- `GITHUB_MODEL` (optional repository variable)

Required secrets/variables for GitHub Actions:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- `SMTP_TO`

The workflow uses the built-in `GITHUB_TOKEN` for GitHub-hosted inference requests, so no separate Anthropic or custom GitHub token secret is required.

## Email configuration

Add these repository secrets:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- `SMTP_TO`

Optional repository variable:

- `SMTP_STARTTLS` (`true` by default; set to `false` for implicit SSL)

## Running locally

From the repository root:

```bash
python -m unittest discover -v
python -m conference_fetcher
```

Before running locally, set the same environment variables used by the workflow.

## Notes

- The pipeline only adds conferences to `cache.md` after an email is successfully sent.
- If there are no new matching conferences, the email contains a friendly "no new conferences" message.
- The scraper is written to extract the most important requested fields: title, dates, location, registration deadline, pre-registration deadline, and abstract submission deadline.
