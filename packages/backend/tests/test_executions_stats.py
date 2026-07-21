"""Test that execution_stats endpoint structure is correct."""


def test_stats_endpoint_exists():
    """Verify the stats function is importable and has correct signature."""
    from backend.api.executions import execution_stats
    import inspect
    sig = inspect.signature(execution_stats)
    assert "session" in sig.parameters
