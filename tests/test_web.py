"""
Unit and integration tests for StockModel Web UI and API.
"""

from fastapi.testclient import TestClient
from stockmodel.web.app import app

client = TestClient(app)


def test_api_status():
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "cpu_count" in data
    assert "config" in data
    assert len(data["config"]["core_features"]) == 7


def test_api_rank():
    response = client.get("/api/rank?days=100&seed=42&allow_short=true")
    assert response.status_code == 200
    data = response.json()
    assert "as_of_date" in data
    assert "summary" in data
    assert "allocations" in data
    assert data["summary"]["long_positions"] > 0
    assert data["summary"]["short_positions"] > 0


def test_api_backtest():
    response = client.get("/api/backtest?days=120&seed=42")
    assert response.status_code == 200
    data = response.json()
    assert "metrics" in data
    assert "daily_curve" in data
    assert len(data["daily_curve"]) > 50
    assert "sharpe_ratio" in data["metrics"]


def test_api_check_gate():
    response = client.get("/api/check-gate?days=120&seed=42")
    assert response.status_code == 200
    data = response.json()
    assert "passed" in data
    assert "summary" in data
    assert "folds" in data


def test_api_ablation():
    response = client.get("/api/ablation?days=120&seed=42&source=synthetic")
    assert response.status_code == 200
    data = response.json()
    assert "features" in data
    assert len(data["features"]) == 7


def test_api_moomoo_status():
    response = client.get("/api/moomoo/status")
    assert response.status_code == 200
    data = response.json()
    assert "connected" in data
    assert "panel" in data
    assert "host" in data
    assert "port" in data


def test_api_rank_moomoo():
    response = client.get("/api/rank?days=120&source=moomoo&allow_short=true")
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "moomoo"
    assert "as_of_date" in data
    assert len(data["allocations"]) > 0


def test_api_backtest_moomoo():
    response = client.get("/api/backtest?days=120&source=moomoo")
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "moomoo"
    assert "metrics" in data
    assert "daily_curve" in data
    assert len(data["daily_curve"]) > 50


def test_api_index():
    response = client.get("/")
    assert response.status_code == 200


def test_api_single_stock_moomoo():
    response = client.get("/api/stock/AMZN?days=120&source=moomoo")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "AMZN"
    assert "quote" in data
    assert "close" in data["quote"]
    assert "verdict" in data
    assert "pred_score" in data["verdict"]
    assert "percentile" in data["verdict"]
    assert "earnings" in data
    assert "derivatives" in data
    assert "features" in data
    assert len(data["features"]) == 7
    assert "history" in data
    assert len(data["history"]) > 20


def test_api_single_stock_synthetic():
    response = client.get("/api/stock/NVDA?days=100&source=synthetic")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "NVDA"
    assert "verdict" in data
    assert "features" in data





