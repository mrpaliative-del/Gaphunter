
# SolveEase GapHunter

A lightweight, scheduled discovery tool for relevant World Bank-funded
procurement opportunities, delivered through Telegram.

## What it does

- Reads the official World Bank Group Procurement Notice dataset.
- Uses bounded JSON pagination (up to 1,000 records per API request).
- Filters for selected service and consultancy keywords.
- Excludes records with missing, unparseable, or past deadlines.
- Requires an official World Bank-hosted notice URL.
- Sorts matching records by deadline.
- Sends a compact Telegram digest.
- Stores recently sent IDs in `state.json`.
- Runs daily through GitHub Actions.
- Supports manual dry-run validation.

## What it does not claim

- It does not cover every public procurement opportunity worldwide.
- It does not independently verify that a procurement notice remains open.
- It does not determine whether a specific applicant is eligible.
- It does not guarantee contract awards, income, or business success.
- It does not scrape private accounts or collect applicant personal data.

## Requirements

- A GitHub repository with Actions enabled.
- A Telegram bot created through @BotFather.
- The destination Telegram chat ID.
- No paid API key or Python package installation.

## Setup

1. Commit `main.py`, `state.json`, `.gitignore`,
   `README.md`, and `.github/workflows/gaphunter.yml`.
2. In GitHub, open Settings > Secrets and variables > Actions.
3. Add repository secret `TELEGRAM_BOT_TOKEN`.
4. Add repository secret `TELEGRAM_CHAT_ID`.
5. Open Actions > SolveEase GapHunter > Run workflow.
6. Leave `dry_run` enabled for the first test.
7. Inspect the logs and workflow summary.
8. If the source ingestion works, run it again with `dry_run` disabled
   to test actual Telegram delivery.

## Configuration

`MAX_PAGES`: pages fetched per run, default 5, maximum 25.

`MAX_RESULTS`: maximum new opportunities delivered per run,
default 8, maximum 15.

`DRY_RUN=true`: reads the API and prints selected records without
sending Telegram messages or updating state.

The API request uses the documented World Bank dataset and resource:
- Dataset: DS00979
- Resource: RS00909
- Endpoint:
  https://datacatalogapi.worldbank.org/dexapps/fone/api/apiservice

## Operations

Scheduled scans run daily at 08:17 UTC.

Manual dry runs are intended for source validation. A live manual run
must have `dry_run` disabled and both Telegram secrets configured.

Review the Actions logs after each initial deployment. A successful
workflow means the executed steps succeeded; it does not mean each
notice is suitable for every user.

If `state.json` becomes invalid, restore a valid copy rather than
deleting it blindly. Removing seen IDs can cause duplicate alerts.

## Data attribution

Source: World Bank Group, Procurement Notice dataset.
Dataset page:
https://financesone.worldbank.org/procurement%20notice/DS00979

The dataset is listed under Creative Commons Attribution 4.0
International. Retain source attribution when redistributing data
and consult the official terms for your use.

## Product validation

Track:
- successful source requests and records parsed
- relevant future-deadline notices found
- unique opportunities delivered
- repeat searches and returning users
- genuine paid-report purchases, if introduced later

Do not treat the number of API records as proof of customer demand.
