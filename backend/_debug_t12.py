import sys
sys.path.insert(0, ".")
from fastapi.testclient import TestClient
import app.main
from app.database import get_db, engine
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(bind=test_engine)
Base = __import__("app.database", fromlist=["Base"]).Base
Base.metadata.create_all(test_engine)

def override_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app = app.main.app
app.dependency_overrides[get_db] = override_db
client = TestClient(app)

# Need a real SA token - this is hard without auth setup. Instead check the policy decision path.
from app.core.authz.policy import evaluate, MATRIX, DC_WORKER
from app.core.authz.principal import Principal
p = Principal(user_id=1, role="super_admin", organization_id=None, payroll_employee_id=None, is_active=True)
print("MATRIX super_admin worker:", MATRIX.get("super_admin", {}).get(DC_WORKER))
print("super_admin in PLATFORM_ROLES:", p.role in __import__("app.core.authz.principal", fromlist=["PLATFORM_ROLES"]).PLATFORM_ROLES)
