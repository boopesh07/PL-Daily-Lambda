# PL Daily Lambda

Lambda-ready utility to pull the latest daily profit/loss (`todaysChange`) and daily percentage profit/loss (`todaysChangePerc`) for every active U.S. stock ticker. The flow is:

1. Discover all active stock tickers via Polygon's `/v3/reference/tickers` endpoint.
2. Batch those tickers into calls to the full market snapshot endpoint `/v2/snapshot/locale/us/markets/stocks/tickers`.
3. Return a concise list of tickers with their corresponding daily P&L metrics.

## Setup

- Python 3.10+ recommended.
- Copy `.env.example` to `.env` and fill in `POLYGON_API_KEY`.
- Create (or reuse) the virtual environment:

  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt
  ```

## Running Locally

Run the coordinator script to fetch and print a sample of snapshot data:

```bash
python -m src.main
```

This prints the number of tickers processed along with example records.

## Lambda Deployment Notes

- Package the `src/` directory along with the installed dependencies (e.g. via a build step that runs `pip install -r requirements.txt -t build/`).
- Configure the Lambda function environment variable `POLYGON_API_KEY`.
- Use `src.lambda_handler.handler` as the handler entry point.
- Schedule execution via EventBridge to generate daily metrics.

## Configuration

Environment variables:

- `POLYGON_API_KEY` (required): Polygon API credential with access to reference and snapshot endpoints.
- `INCLUDE_OTC` (optional): Set to `true` to include OTC securities in snapshot requests.
- `TICKER_BATCH_SIZE` (optional): Defaults to `500`. Number of tickers per snapshot request.
- `SNAPSHOT_CONCURRENCY` (optional): Defaults to `5`. Maximum in-flight snapshot requests.
- `TICKER_LIMIT` (optional): Limit the number of tickers processed (useful for local testing).
- `HTTP_CONNECT_TIMEOUT` / `HTTP_READ_TIMEOUT` (optional): Override HTTP timeout settings in seconds.
- `REDIS_URL` / `REDIS_TOKEN` (optional but required to cache): Upstash REST endpoint and access token.
- `REDIS_KEY_PREFIX` (optional): Defaults to `stock:pl_daily`. Final key: `{prefix}:{SYMBOL}`.
- `REDIS_PIPELINE_SIZE` (optional): Defaults to `50`. Number of Redis commands per pipeline call.
- `REDIS_TTL_SECONDS` (optional): Defaults to `86400` (24 hours). Adjust to control expiration.
- `PL_TIMEZONE` (optional): Defaults to `America/New_York`. Used to stamp the `date` field in cached payloads.

All configuration values (except the API key) have sensible defaults and may be tuned via Lambda environment variables.

Each cached record contains the collection date formatted as `YYYY-MM-DD` in the configured timezone (default Eastern Time). The stored payload for every ticker includes:

- `ticker`
- `daily_pl` (Polygon `todaysChange`)
- `daily_pl_percent` (Polygon `todaysChangePerc`)
- `min_close` (Polygon `min.c`)
- `date`

## Lambda Build & Deploy

Two helper scripts automate packaging and deployment via the AWS CLI. Ensure the CLI is installed and authenticated (e.g. via `aws configure` or environment variables).

1. Populate deployment variables in `.env` (see `.env.example` for a template).
2. Build the Lambda artifact:

   ```bash
   scripts/build_lambda.sh
   ```

   This installs dependencies into `build/lambda/` and creates `build/pl_daily_snapshot.zip`.

3. Deploy/update the Lambda function and attach an EventBridge rule scheduled for 7:55 PM EST:

   ```bash
   scripts/deploy_lambda.sh
   ```

   The script will create the function if it does not exist (requires `LAMBDA_ROLE_ARN`) or update an existing one. It also sets/updates Lambda environment variables from `.env`, configures a rule named `pl-daily-pl-755pm` (override via `EVENTBRIDGE_RULE_NAME`), applies the `America/New_York` timezone, and links the rule to the function.

### Deployment Environment Variables

Key values consumed by the deployment scripts (add them to `.env` as needed):

- `AWS_REGION` (default `us-east-1`)
- `AWS_PROFILE` (optional)
- `LAMBDA_FUNCTION_NAME` (required)
- `LAMBDA_ROLE_ARN` (required when creating a new function)
- `LAMBDA_TIMEOUT` / `LAMBDA_MEMORY_SIZE` / `LAMBDA_RUNTIME` / `LAMBDA_HANDLER` (optional overrides)
- `EVENTBRIDGE_RULE_NAME` (default `pl-daily-pl-755pm`)
- `EVENTBRIDGE_TIMEZONE` (default `America/New_York`)
- `EVENTBRIDGE_CRON` (default `cron(55 19 * * ? *)`)
