from httpx import AsyncClient


async def test_create_project(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/projects",
        json={"name": "My Project", "description": "A test project"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "My Project"
    assert body["repo_path"] == "sample_repo"
    assert body["id"] > 0


async def test_create_duplicate_project_conflicts(client: AsyncClient) -> None:
    payload = {"name": "Duped"}
    assert (await client.post("/api/v1/projects", json=payload)).status_code == 201
    response = await client.post("/api/v1/projects", json=payload)
    assert response.status_code == 409


async def test_list_projects(client: AsyncClient) -> None:
    await client.post("/api/v1/projects", json={"name": "P1"})
    await client.post("/api/v1/projects", json={"name": "P2"})
    response = await client.get("/api/v1/projects")
    assert response.status_code == 200
    assert [p["name"] for p in response.json()] == ["P1", "P2"]
