"""
modules/payroll/jurisdictions_router.py
-----------------------------------------
Country entitlement management (Compliance > Countries). Mounted under
payroll_router, so every path is /api/payroll/jurisdictions/...

  GET    /jurisdictions/entitled                    -> countries, limit, used, addable (payroll operator)
  POST   /jurisdictions/entitled                    -> add a country (org admin)
  POST   /jurisdictions/entitled/{code}/primary     -> make a country primary (org admin)
  DELETE /jurisdictions/entitled/{code}             -> remove a country with no employees (org admin)
  POST   /jurisdictions/entitled/replace-primary    -> one-country plans: change the only country (org admin)

The logic lives in billing/jurisdiction_entitlement.py; this module only
binds it to HTTP. Every write response is the same payload as the GET, so
the Countries panel can re-render from the response.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_org_admin, get_current_payroll_operator
from app.database import get_db
from app.modules.billing import jurisdiction_entitlement
from app.modules.billing.entitlements import require_writeable_workspace

router = APIRouter(prefix="/jurisdictions", tags=["Country Entitlement"])


class CountryRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    country_code: str = Field(..., alias="countryCode", min_length=2, max_length=60)


@router.get("/entitled", summary="This organization's entitled countries and plan limit")
def get_entitled_countries(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_payroll_operator),
):
    summary = jurisdiction_entitlement.entitlement_summary(db, current_user.organization_id)
    # The first read may have seeded the ledger for an org that predates it.
    db.commit()
    return summary


@router.post(
    "/entitled", summary="Add a country (org admin only)",
    dependencies=[Depends(require_writeable_workspace())],
)
def add_entitled_country(
    data: CountryRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_org_admin),
):
    return jurisdiction_entitlement.add_entitled_country(db, current_user, data.country_code)


@router.post(
    "/entitled/replace-primary", summary="Change the only country on a one-country plan (org admin only)",
    dependencies=[Depends(require_writeable_workspace())],
)
def replace_primary_country(
    data: CountryRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_org_admin),
):
    return jurisdiction_entitlement.replace_primary_country(db, current_user, data.country_code)


@router.post(
    "/entitled/{country_code}/primary", summary="Make a country the primary country (org admin only)",
    dependencies=[Depends(require_writeable_workspace())],
)
def set_primary_country(
    country_code: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_org_admin),
):
    return jurisdiction_entitlement.set_primary_country(db, current_user, country_code)


@router.delete(
    "/entitled/{country_code}", summary="Remove a country with no employees (org admin only)",
    dependencies=[Depends(require_writeable_workspace())],
)
def remove_entitled_country(
    country_code: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_org_admin),
):
    return jurisdiction_entitlement.remove_entitled_country(db, current_user, country_code)
