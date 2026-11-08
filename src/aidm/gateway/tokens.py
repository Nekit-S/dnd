def estimate_tokens(*texts: str) -> int:
    """Оценка с запасом: половина байт UTF-8, вверх."""
    return (sum(len(t.encode()) for t in texts) + 1) // 2
