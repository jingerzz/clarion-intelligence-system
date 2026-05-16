# TastyTrade Open API Reference

## Base URL

`https://api.tastyworks.com`

## API Version Header

All requests: `Accept-Version: 20240501`

Falls back to `20240430` if omitted. The Python SDK handles this automatically.

## Authentication

### OAuth2 Token Exchange

```
POST /oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=refresh_token
&client_secret=<client_secret>
&refresh_token=<refresh_token>
```

Response:
```json
{
  "access_token": "...",
  "token_type": "Bearer",
  "expires_in": 900,
  "scope": "..."
}
```

- Access tokens expire in **15 minutes**
- Refresh tokens **never expire**
- The Python SDK handles token refresh transparently

### Using the Token

```
Authorization: Bearer <access_token>
```

## Key Endpoints

### List Customer Accounts

```
GET /customers/me/accounts
```

Returns all accounts linked to the authenticated user.

### Account Balances

```
GET /accounts/{account_number}/balances
```

Key fields:
- `net-liquidating-value` — total portfolio value
- `cash-balance` — settled cash
- `equity-buying-power` — available for equity purchases
- `derivative-buying-power` — available for options/futures
- `margin-equity` — total equity including margin
- `maintenance-excess` — cushion above maintenance requirement

### Account Positions

```
GET /accounts/{account_number}/positions
```

Key fields per position:
- `symbol` — ticker or option symbol
- `instrument-type` — Equity, Equity Option, Future, etc.
- `quantity` — number of shares/contracts
- `quantity-direction` — Long or Short
- `close-price` — last trade price
- `average-open-price` — cost basis
- `mark` / `mark-price` — current mark
- `realized-day-gain` — realized P/L for the day
- `realized-today` — total realized P/L on position today

### Account Transactions

```
GET /accounts/{account_number}/transactions
```

Parameters: `start-date`, `end-date`, `per-page`, `page-offset`

Transaction types: Trade, Receive Deliver, Dividend, Money Movement, Fee

### Net Liquidating Value History

```
GET /accounts/{account_number}/net-liquidating-value-history
```

Parameters: `time-back` (e.g., `1m`, `3m`, `1y`)

## Error Handling

- 401: Token expired (SDK handles refresh)
- 403: Insufficient permissions
- 404: Account not found
- 429: Rate limited — back off and retry

## Rate Limits

TastyTrade doesn't publish exact limits but recommends:
- Max ~10 requests/second sustained
- Batch requests where possible
- The SDK includes built-in retry with exponential backoff

## Setup Checklist

1. Create OAuth application at https://my.tastytrade.com/app.html#/manage/api-access/oauth-applications
2. Check all required scopes
3. Add `http://localhost:8000` as callback URL
4. Save the client secret
5. Go to OAuth Applications > Manage > Create Grant
6. Save the generated refresh token
7. Store both in Zo Secrets (Settings > Advanced)
