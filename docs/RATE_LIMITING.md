# Rate Limiting Documentation

## Overview
This application uses rate limiting to protect API endpoints from abuse and ensure fair usage. Rate limits are enforced using the `slowapi` library with Redis as the backend store.

## Custom Error Handler
We have implemented a custom rate limit error handler that provides user-friendly error messages with context-specific information.

**Implementation**: `app/main.py:30-82`

## Rate Limit Configuration

### Authentication Endpoints

| Endpoint | Rate Limit | Description |
|----------|------------|-------------|
| `POST /api/v1/auth/login` | 5 per 15 minutes | Standard login attempts |
| `POST /api/v1/auth/register/send-otp` | 3 per 10 minutes | OTP verification emails |
| `POST /api/v1/auth/register/verify-otp` | 5 per 10 minutes | OTP verification attempts |
| `POST /api/v1/auth/forgot-password/send-code` | 3 per 10 minutes | Password reset code requests |
| `POST /api/v1/auth/resend-otp` | 3 per 10 minutes | Resend OTP requests |

## Custom Error Response Format

### Before (Default slowapi):
```json
{
  "error": "Rate limit exceeded: 5 per 15 minute"
}
```

### After (Custom Handler):
```json
{
  "error": "Rate limit exceeded",
  "message": "Too many login attempts. Please wait a few minutes before attempting to log in again.",
  "details": {
    "limit": "5 per 15 minute",
    "endpoint": "/api/v1/auth/login"
  }
}
```

## Response Headers

When a rate limit is hit, the following headers are included:

- `X-RateLimit-Limit`: Maximum number of requests allowed
- `X-RateLimit-Remaining`: Number of requests remaining
- `X-RateLimit-Reset`: Unix timestamp when the limit resets
- `Retry-After`: Seconds until the limit resets (when rate limited)

## Endpoint-Specific Messages

The custom handler provides context-aware messages based on the endpoint:

### Login Endpoint
```json
{
  "error": "Rate limit exceeded",
  "message": "Too many login attempts. Please wait a few minutes before attempting to log in again.",
  "details": {
    "limit": "5 per 15 minute",
    "endpoint": "/api/v1/auth/login"
  }
}
```

### Registration/OTP Endpoints
```json
{
  "error": "Rate limit exceeded",
  "message": "Too many registration attempts. Please wait before requesting another verification code.",
  "details": {
    "limit": "3 per 10 minute",
    "endpoint": "/api/v1/auth/register/send-otp"
  }
}
```

### Password Reset Endpoints
```json
{
  "error": "Rate limit exceeded",
  "message": "Too many password reset attempts. Please wait before requesting another password reset code.",
  "details": {
    "limit": "3 per 10 minute",
    "endpoint": "/api/v1/auth/forgot-password/send-code"
  }
}
```

### OTP Resend
```json
{
  "error": "Rate limit exceeded",
  "message": "Too many OTP resend attempts. Please wait before requesting to resend the OTP.",
  "details": {
    "limit": "3 per 10 minute",
    "endpoint": "/api/v1/auth/resend-otp"
  }
}
```

## Logging

Rate limit violations are automatically logged with the following information:
- Endpoint name
- Client IP address
- Rate limit details

Example log entry:
```
WARNING: Rate limit exceeded for login from IP 192.168.1.100: 5 per 15 minute
```

## How It Works

1. **Rate Tracking**: Uses Redis to track request counts per IP address
2. **Key Function**: `get_remote_address` - tracks by client IP
3. **Time Windows**: Sliding window algorithm (e.g., 15 minutes for login)
4. **Automatic Reset**: Counters automatically reset after the time window expires

## Testing Rate Limits

### Using curl:
```bash
# Test login rate limit (send 6 requests to trigger limit)
for i in {1..6}; do
  curl -X POST "http://localhost:8000/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"email":"test@example.com","password":"test"}' && echo ""
done
```

### Expected Response (6th request):
```json
{
  "error": "Rate limit exceeded",
  "message": "Too many login attempts. Please wait a few minutes before attempting to log in again.",
  "details": {
    "limit": "5 per 15 minute",
    "endpoint": "/api/v1/auth/login"
  }
}
```

## Modifying Rate Limits

To change rate limits for an endpoint, modify the decorator in the respective endpoint file:

**File**: `app/api/v1/endpoints/auth.py`

```python
# Example: Change login rate limit to 10 per 20 minutes
@router.post("/login", ...)
@limiter.limit("10/20minutes")  # Modify this line
def login(...):
    ...
```

**Format**: `"<count>/<time_unit>"`
- Time units: `second`, `minute`, `hour`, `day`
- Examples: `"5/minute"`, `"100/hour"`, `"1000/day"`

## Customizing Error Messages

To add custom messages for new endpoints, modify the `custom_rate_limit_exceeded_handler` function in `app/main.py`:

```python
# Add new endpoint pattern
elif "/your-endpoint" in path:
    endpoint_name = "your feature"
    retry_message = "Custom retry message for users."
```

## Dependencies

- **slowapi**: FastAPI rate limiting library
- **Redis**: Backend store for rate limit counters (configured in docker-compose.yml)

## Benefits

1. ✅ **User-Friendly**: Clear, actionable error messages
2. ✅ **Context-Aware**: Different messages for different endpoints
3. ✅ **Logging**: Automatic tracking of rate limit violations
4. ✅ **Headers**: Standard rate limit headers for client-side handling
5. ✅ **Flexible**: Easy to modify limits and messages per endpoint
