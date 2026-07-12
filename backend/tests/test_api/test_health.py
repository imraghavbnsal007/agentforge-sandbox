from httpx import AsyncClient


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # Backup diagnostics are always present; "available" is False where the
    # read-only /backups mount doesn't exist (tests, bare uvicorn).
    assert "available" in body["backups"]
