# ClawSight — Team Review Conventions

## Security
- Never commit hardcoded secrets, API keys, or tokens
- Always use environment variables for sensitive configuration
- Validate and sanitize all user inputs
- Use parameterized queries — never construct SQL with string concatenation
- Use `secrets.token_urlsafe()` for token generation, not `random`

## Error Handling
- Always handle exceptions explicitly — no bare `except:` clauses
- Return meaningful error messages (but never expose stack traces in production)
- Log errors with sufficient context for debugging
- Use structured error responses with consistent HTTP status codes

## Performance
- Avoid database queries inside loops (N+1 pattern)
- Use connection pooling for database and HTTP connections
- Paginate large result sets — never load unbounded data
- Cache expensive computations where appropriate

## Testing
- Write tests for all critical business logic
- Cover error/edge cases, not just the happy path
- Use meaningful test names that describe the scenario
- Keep tests independent — no shared mutable state between tests

## Architecture
- Follow single responsibility principle — one module, one job
- Keep controller/route handlers thin — delegate to service layer
- Use dependency injection over global state
- Don't repeat yourself — extract shared logic into utilities

## Code Quality
- Use type hints for function signatures
- Write docstrings for public functions and classes
- Use constants or enums instead of magic numbers/strings
- Keep functions under 50 lines — extract complex logic into helpers