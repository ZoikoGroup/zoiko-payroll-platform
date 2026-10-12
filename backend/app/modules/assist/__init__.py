# Assist package. assist_router is deliberately NOT imported here (see
# payroll/policy/__init__.py for the full rationale): app.database imports
# this package's .models for table registration while payroll.models may
# still be partially initialized, and the eager router import drags in
# assist.service -> assist.tools, which imports names from payroll.models
# too early. assist_router is mounted explicitly by main.py.
