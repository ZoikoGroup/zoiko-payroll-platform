"""
modules/payroll/jurisdiction_hooks.py
-------------------------------------
Shared extension points through which the platform (service.py, the shared
routers, retention_service) calls a jurisdiction's statutory service module
WITHOUT importing it. The static dependency direction is one way:

    shared platform  <-  jurisdiction statutory service  <-  statutory engine

A jurisdiction statutory module declares ``JURISDICTION_HOOKS`` — a mapping of
hook name -> the module attribute that implements it. The platform asks for a
hook by (country, name); the module named in ``_MODULES`` is imported on first
use and the attribute is looked up on every call (so a hook can never be
missing because nothing happened to import the module yet, and a test that
replaces the module attribute is honoured).

Fail-closed: ``call`` raises when a country that HAS a statutory module lacks
the hook — a governance check (activation refusal, approver check, delete
guard, run-approval preflight) is never silently skipped. ``call_optional``
returns its default only for countries WITHOUT a statutory module.
"""

import importlib
from typing import Callable, Dict, Tuple

# Countries whose statutory workflows live in a jurisdiction service module.
_MODULES: Dict[str, str] = {
    "HK": "app.modules.payroll.hong_kong_service",
    "SA": "app.modules.payroll.saudi_arabia_service",
    "NL": "app.modules.payroll.netherlands_service",
    "MX": "app.modules.payroll.mexico_service",
    "BR": "app.modules.payroll.brazil_service",
    "ZA": "app.modules.payroll.south_africa_service",
}


def countries() -> Tuple[str, ...]:
    return tuple(_MODULES)


def has_module(country: str) -> bool:
    return (country or "").upper() in _MODULES


def get(country: str, name: str) -> Callable:
    country = (country or "").upper()
    module_name = _MODULES.get(country)
    if module_name is None:
        raise RuntimeError(f"{country or '?'} has no jurisdiction statutory module (hook {name})")
    module = importlib.import_module(module_name)
    attribute = getattr(module, "JURISDICTION_HOOKS", {}).get(name)
    fn = getattr(module, attribute, None) if attribute else None
    if not callable(fn):
        raise RuntimeError(f"jurisdiction hook {country}:{name} is not registered — refusing to continue (fail-closed)")
    return fn


def declares(country: str, name: str) -> bool:
    """True when the country's module registers hook `name` — for OPTIONAL
    hooks that only some jurisdictions implement (e.g. Mexico's
    pack_approval_refusal). A declared hook is then resolved through get(),
    which still fails closed if the name points at nothing callable."""
    country = (country or "").upper()
    module_name = _MODULES.get(country)
    if module_name is None:
        return False
    return name in getattr(importlib.import_module(module_name), "JURISDICTION_HOOKS", {})


def call(country: str, name: str, *args, **kwargs):
    return get(country, name)(*args, **kwargs)


def call_optional(country: str, name: str, *args, default=None, **kwargs):
    if not has_module(country):
        return default
    return call(country, name, *args, **kwargs)
