"""Pytest fixtures for Amrutam API test suite."""

from collections.abc import Generator

import pytest
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """TestClient fixture providing an isolated client for each test."""
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
