from nl2sql_agent.main import SlidingWindowRateLimiter


def test_sliding_window_rate_limiter_allows_within_budget():
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)
    assert limiter.check("client-a") is None
    assert limiter.check("client-a") is None


def test_sliding_window_rate_limiter_blocks_when_budget_exceeded():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    assert limiter.check("client-b") is None
    retry_after = limiter.check("client-b")
    assert retry_after is not None
    assert retry_after >= 1
