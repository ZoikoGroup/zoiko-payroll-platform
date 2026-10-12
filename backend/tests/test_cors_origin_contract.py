from app.config import settings


def test_lan_frontend_origin_is_allowed():
    origins = {origin.strip() for origin in settings.PAYROLL_CORS_ORIGINS.split(",") if origin.strip()}
    assert "http://192.168.31.148:5173" in origins
