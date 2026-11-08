from fastapi import HTTPException, Request

LOCAL_HOSTS = {"127.0.0.1", "::1"}


def host_only(request: Request) -> None:
    if request.client is None or request.client.host not in LOCAL_HOSTS:
        raise HTTPException(status_code=403, detail="Только с компьютера ведущего")
