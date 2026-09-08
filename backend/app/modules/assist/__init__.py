def __getattr__(name):
    if name == "assist_router":
        from app.modules.assist.router import assist_router
        return assist_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["assist_router"]
