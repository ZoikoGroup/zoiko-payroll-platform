"""
modules/assist/knowledge.py
---------------------------
Governed knowledge base for Zoiko Payroll Assist.

Only PUBLISHED items within their effective date window and approved scope
are retrieval-eligible (KB-GOV-002). Retrieval is hybrid-style: lexical
(term frequency over title/body/summary) + metadata filters (jurisdiction,
language, tenant). Source authority tier is applied as a ranking weight.
Tenant (organization) items are isolated; global platform items are shared.
"""

import logging
import re
from datetime import date, datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.modules.assist.models import (
    AssistKbItem,
    AssistKbSource,
    AssistRetrievalCandidate,
    AssistRetrievalRun,
    AuthorityTier,
    KnowledgeSourceState,
    KnowledgeState,
)

logger = logging.getLogger("zoiko_payroll.assist.knowledge")

# Common English function words. Without this filter, a message like
# "explain the quantum telemetry of lunar regolith sampling rigs" would
# still score a nonzero match on almost any KB article purely from "the"
# appearing as ordinary prose — length>2 alone isn't a relevance filter.
_STOP_WORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "has",
    "was", "were", "with", "this", "that", "from", "have", "will", "would",
    "about", "what", "when", "where", "which", "who", "why", "how", "does",
    "did", "into", "your", "our", "their", "its", "his", "her", "them",
    "than", "then", "there", "these", "those", "been", "being", "such",
    "get", "got", "out", "now", "any", "some", "one", "two",
    # Generic instructional/framing verbs — they genuinely appear across
    # unrelated KB bodies as ordinary connective language ("Assist can
    # explain configuration...") without being real topical signal.
    "explain", "tell", "meaning", "describe", "show", "find",
}
_TERM_RE = re.compile(r"[a-z0-9]+")


def _query_terms(query: str) -> list[str]:
    return [t for t in _TERM_RE.findall(query.lower()) if len(t) > 2 and t not in _STOP_WORDS]

# Searchable term synonyms mapped to seed knowledge content types. Used to
# boost lexical scoring for common payroll questions.
_CONTENT_KEYWORDS = {
    "approval": ["approve", "approval", "sign-off", "review", "status"],
    "leave": ["leave", "annual", "sick", "balance", "allocation", "request"],
    "payslip": ["payslip", "pay slip", "salary slip", "earnings"],
    "policy": ["policy", "rule", "overtime", "allowance"],
    "payment": ["payment", "bank", "release", "transfer", "settle"],
    "tax": ["tax", "tds", "income tax", "slab"],
    "filing": ["filing", "statutory", "compliance", "return"],
    "exception": ["exception", "blocker", "readiness", "error", "validation"],
    "security": ["permission", "role", "access", "security", "privacy"],
}


# Coarse, deterministic jurisdiction-mention detector (country names only —
# no NLP/NER, consistent with the rest of this module). Used to distinguish
# "no KB article matched" from "this jurisdiction isn't one we have approved
# guidance for", which need different fallback copy (KB-GOV, unsupported
# jurisdiction handling). A short common name (e.g. "Chad", "Georgia") can
# collide with an unrelated word — acceptable here since it only ever
# narrows an already-generic KB fallback to a more specific one, never
# blocks or exposes anything.
_COUNTRY_NAMES = [
    "Afghanistan", "Albania", "Algeria", "Andorra", "Angola", "Argentina",
    "Armenia", "Australia", "Austria", "Azerbaijan", "Bahamas", "Bahrain",
    "Bangladesh", "Barbados", "Belarus", "Belgium", "Belize", "Benin",
    "Bhutan", "Bolivia", "Bosnia", "Botswana", "Brazil", "Brunei",
    "Bulgaria", "Burkina Faso", "Burundi", "Cambodia", "Cameroon", "Canada",
    "Chad", "Chile", "China", "Colombia", "Comoros", "Congo", "Costa Rica",
    "Croatia", "Cuba", "Cyprus", "Czechia", "Czech Republic", "Denmark",
    "Djibouti", "Dominica", "Ecuador", "Egypt", "El Salvador", "Eritrea",
    "Estonia", "Eswatini", "Ethiopia", "Fiji", "Finland", "France", "Gabon",
    "Gambia", "Georgia", "Germany", "Ghana", "Greece", "Grenada",
    "Guatemala", "Guinea", "Guyana", "Haiti", "Honduras", "Hungary",
    "Iceland", "India", "Indonesia", "Iran", "Iraq", "Ireland", "Israel",
    "Italy", "Jamaica", "Japan", "Jordan", "Kazakhstan", "Kenya", "Kiribati",
    "Kosovo", "Kuwait", "Kyrgyzstan", "Laos", "Latvia", "Lebanon",
    "Lesotho", "Liberia", "Libya", "Liechtenstein", "Lithuania",
    "Luxembourg", "Madagascar", "Malawi", "Malaysia", "Maldives", "Mali",
    "Malta", "Mauritania", "Mauritius", "Mexico", "Moldova", "Monaco",
    "Mongolia", "Montenegro", "Morocco", "Mozambique", "Myanmar", "Namibia",
    "Nauru", "Nepal", "Netherlands", "New Zealand", "Nicaragua", "Niger",
    "Nigeria", "North Korea", "North Macedonia", "Norway", "Oman",
    "Pakistan", "Palau", "Panama", "Papua New Guinea", "Paraguay", "Peru",
    "Philippines", "Poland", "Portugal", "Qatar", "Romania", "Russia",
    "Rwanda", "Samoa", "San Marino", "Saudi Arabia", "Senegal", "Serbia",
    "Seychelles", "Sierra Leone", "Singapore", "Slovakia", "Slovenia",
    "Somalia", "South Africa", "South Korea", "South Sudan", "Spain",
    "Sri Lanka", "Sudan", "Suriname", "Sweden", "Switzerland", "Syria",
    "Taiwan", "Tajikistan", "Tanzania", "Thailand", "Timor-Leste", "Togo",
    "Tonga", "Trinidad and Tobago", "Tunisia", "Turkey", "Turkmenistan",
    "Tuvalu", "Uganda", "Ukraine", "United Arab Emirates", "United Kingdom",
    "United States", "Uruguay", "Uzbekistan", "Vanuatu", "Vatican City",
    "Venezuela", "Vietnam", "Yemen", "Zambia", "Zimbabwe",
]
_COUNTRY_NAME_RE = re.compile(
    r"\b(" + "|".join(re.escape(n) for n in _COUNTRY_NAMES) + r")\b", re.IGNORECASE
)


def find_mentioned_country(text: str) -> str | None:
    """Return the first country name mentioned in `text`, or None."""
    match = _COUNTRY_NAME_RE.search(text or "")
    return match.group(1) if match else None


def is_jurisdiction_supported(db: Session, org_id: int, country_name: str) -> bool:
    """Whether `country_name` is the org's configured compliance jurisdiction.

    Local import avoids a hard module-level dependency between the Assist
    package and the payroll package for an org-scoped check used only here
    (mirrors the lazy-import style already used for KB seeding). Reuses
    app.core.jurisdiction's canonical name<->code resolver rather than a
    second, separately-maintained country map — CompanyComplianceDetails
    stores a 2-letter code ("IN"/"US"/...), while a message names a full
    country ("India"), so a bare string comparison would never match.

    The org<->jurisdiction hierarchy tables (Country/Jurisdiction/
    OrganizationJurisdictionAssignment) this originally checked were removed
    by a later refactor in favor of this single jurisdiction_country field —
    see payroll/models.py's CompanyComplianceDetails.
    """
    from app.core.jurisdiction import get_jurisdiction_code
    from app.modules.payroll.models import CompanyComplianceDetails

    compliance = (
        db.query(CompanyComplianceDetails)
        .filter(CompanyComplianceDetails.organization_id == org_id)
        .first()
    )
    if not compliance or not compliance.jurisdiction_country:
        return False
    mentioned_code = get_jurisdiction_code(country_name)
    org_code = get_jurisdiction_code(compliance.jurisdiction_country)
    return bool(mentioned_code) and mentioned_code == org_code


def _is_retrieval_eligible(item: AssistKbItem, today: date) -> bool:
    if item.state != KnowledgeState.PUBLISHED.value:
        return False
    if item.effective_from and item.effective_from > today:
        return False
    if item.effective_to and item.effective_to < today:
        return False
    return True


def _score_item(item: AssistKbItem, query_terms: list[str]) -> int:
    """Deterministic lexical score. Title matches weigh most, then body."""
    score = 0
    haystack_title = item.title.lower()
    haystack_body = (item.body or "").lower()
    haystack_summary = (item.summary or "").lower()
    for term in query_terms:
        if term and term in haystack_title:
            score += 6
        elif term and term in haystack_summary:
            score += 4
        elif term and term in haystack_body:
            score += 2
    for keyword, synonyms in _CONTENT_KEYWORDS.items():
        if any(s in haystack_title for s in synonyms) and any(s in query_terms for s in synonyms):
            score += 3
    # The authority bonus is a tie-breaker among items that already matched
    # something — applying it unconditionally would give every query a
    # nonzero score on every authoritative item, even one with no real
    # relevance (e.g. "hi"), making irrelevant items look like real matches.
    if score > 0 and item.authority in (AuthorityTier.TIER_1_OPERATIONAL.value, AuthorityTier.TIER_2_APPROVED_PRIMARY.value):
        score += 2
    return score


def search_kb(
    db: Session,
    organization_id: int,
    query: str,
    jurisdiction_codes: list[str] | None = None,
    limit: int = 5,
    record_run: bool = True,
) -> list[tuple[int, AssistKbItem]]:
    """Retrieve retrieval-eligible knowledge for a tenant-scoped query.

    Global items (organization_id is NULL) are shared; tenant items are
    isolated to their organization. Jurisdiction filter: items with an empty
    jurisdiction list apply everywhere; otherwise at least one listed
    jurisdiction must match the request scope.

    Returns (score, item) pairs — the score is exposed so callers can reason
    about match strength (e.g. flagging a POTENTIAL conflict when two
    candidates score near-identically under different authority tiers).
    """
    today = date.today()
    jurisdiction_codes = [j.upper() for j in (jurisdiction_codes or [])]

    # A quarantined source's items are excluded even though the items
    # themselves are still PUBLISHED — the incident kill switch cascades
    # from the source without needing to touch every item it owns.
    base_query = (
        db.query(AssistKbItem)
        .outerjoin(AssistKbSource, AssistKbItem.source_id == AssistKbSource.id)
        .filter(
            AssistKbItem.state == KnowledgeState.PUBLISHED.value,
            or_(AssistKbItem.organization_id.is_(None), AssistKbItem.organization_id == organization_id),
            or_(AssistKbItem.source_id.is_(None), AssistKbSource.state != KnowledgeSourceState.QUARANTINED.value),
        )
    )
    items = base_query.all()

    eligible = [i for i in items if _is_retrieval_eligible(i, today)]

    query_terms = _query_terms(query)
    scored = []
    for item in eligible:
        if jurisdiction_codes:
            item_jurisdictions = [j.upper() for j in (item.jurisdiction_codes or [])]
            if item_jurisdictions and not set(item_jurisdictions) & set(jurisdiction_codes):
                continue
        score = _score_item(item, query_terms)
        if score > 0:
            scored.append((score, item))
        elif not query_terms:
            # Empty / low-information query: return newest published items so
            # suggestions have something to ground on.
            scored.append((1, item))

    scored.sort(key=lambda pair: (-pair[0], -pair[1].id))
    ranked = scored[:limit]

    if record_run:
        run = AssistRetrievalRun(
            organization_id=organization_id,
            query_hash=hash(query),
            scope={"jurisdiction_codes": jurisdiction_codes, "limit": limit},
            candidate_count=len(ranked),
        )
        db.add(run)
        db.flush()
        for idx, (score, item) in enumerate(ranked):
            db.add(
                AssistRetrievalCandidate(
                    retrieval_run_id=run.id,
                    kb_item_id=item.id,
                    score=score,
                    rank=idx + 1,
                    reason="keyword" if score > 1 else "recent",
                )
            )
        db.commit()

    return ranked


# ── Default seed content ────────────────────────────────────────────────

DEFAULT_SOURCES = [
    {
        "name": "Zoiko Payroll Product Knowledge",
        "source_type": "PRODUCT_DOCUMENTATION",
        "authority_tier": AuthorityTier.TIER_2_APPROVED_PRIMARY.value,
    },
    {
        "name": "Zoiko Payroll Operations Runbook",
        "source_type": "RUNBOOK",
        "authority_tier": AuthorityTier.TIER_3_APPROVED_SECONDARY.value,
    },
]

DEFAULT_KB_ITEMS = [
    {
        "title": "How payroll approval works",
        "content_type": "HOW_TO",
        "summary": "Payroll runs must be reviewed and approved by an authorized user. Assist can summarize readiness but cannot approve payroll.",
        "body": (
            "A payroll run moves through Draft, Review, Approved, Authorized, Paid and Closed. "
            "Approval requires a human with the correct role using the approval screen inside Zoiko Payroll. "
            "Zoiko Payroll Assist can summarize a run, its readiness and unresolved exceptions, but it can never approve or release payroll. "
            "Always verify material decisions against the payroll run record itself."
        ),
        "keywords": ["approval", "approve", "status", "sign-off"],
        "jurisdiction_codes": [],
    },
    {
        "title": "Can Assist approve or release payments?",
        "content_type": "FAQ",
        "summary": "No. Assist cannot approve payroll, release payments, submit filings or change protected data.",
        "body": (
            "Zoiko Payroll Assist is governed: it explains, finds, reviews, prepares and routes payroll work, "
            "but it cannot approve payroll runs, release payments or bank files, submit statutory filings, "
            "or change bank, tax, identity or permission data. Those actions always happen in the canonical "
            "Zoiko Payroll workflow under existing approval controls."
        ),
        "keywords": ["approve", "payment", "release", "filing"],
        "jurisdiction_codes": [],
    },
    {
        "title": "Checking payroll run readiness",
        "content_type": "HOW_TO",
        "summary": "Use the payroll run detail to review readiness blockers such as missing payslip items or unresolved leave requests.",
        "body": (
            "Before approval, review the payroll run's readiness: all expected payslip items present, "
            "no unresolved leave requests, policy and compliance setup complete, and the run status reflects "
            "the current stage. Assist can summarize readiness blockers from the payroll run record, but it "
            "does not recommend approval — that decision belongs to the authorized reviewer."
        ),
        "keywords": ["readiness", "exception", "blocker", "validation", "review"],
        "jurisdiction_codes": [],
    },
    {
        "title": "Understanding leave balances and requests",
        "content_type": "HOW_TO",
        "summary": "Leave allocations and requests live in the Attendance and Leave area; reviewers approve requests there.",
        "body": (
            "Employees accrue leave through allocations configured in the Leaves area. Leave requests must be "
            "reviewed by an authorized reviewer. Assist can show leave balances and the status of leave requests "
            "from authorized records. It cannot approve or reject leave requests on your behalf."
        ),
        "keywords": ["leave", "balance", "request", "allocation"],
        "jurisdiction_codes": [],
    },
    {
        "title": "Payslip access and self-service",
        "content_type": "HOW_TO",
        "summary": "Employees access their own payslips through the employee self-service area; Assist provides secure links, not document bodies.",
        "body": (
            "Employees can view and download their own payslips from the employee self-service portal. "
            "Zoiko Payroll Assist returns secure links and metadata rather than embedding full protected "
            "documents in the conversation by default."
        ),
        "keywords": ["payslip", "self-service", "employee"],
        "jurisdiction_codes": [],
    },
    {
        "title": "Compliance and statutory filings",
        "content_type": "JURISDICTION_GUIDE",
        "summary": "Statutory contributions, tax slabs and filings are configured in Compliances; Assist cannot submit filings.",
        "body": (
            "Statutory contribution rates, tax slabs and company compliance details are managed in the "
            "Compliances area per jurisdiction. Assist can explain configuration and summarize filing status, "
            "but it cannot submit statutory filings. Unsupported or stale jurisdiction guidance results in a "
            "safe fallback rather than substitution."
        ),
        "keywords": ["tax", "filing", "compliance", "statutory"],
        "jurisdiction_codes": [],
    },
    {
        "title": "Roles and permissions in Zoiko Payroll",
        "content_type": "FIELD_DEFINITION",
        "summary": "Roles are super admin, org admin, payroll admin and employee. Access is scoped to your own organization.",
        "body": (
            "Zoiko Payroll has four roles: super_admin (platform-wide), org_admin (full control of their "
            "organization), payroll_admin (day-to-day payroll operations) and employee (self-service only). "
            "All org-scoped access is confined to your own organization. Assist derives authority from your "
            "authenticated session — it never trusts role or tenant claims supplied in conversation text."
        ),
        "keywords": ["role", "permission", "security", "access"],
        "jurisdiction_codes": [],
    },
    {
        "title": "Comparing payroll periods",
        "content_type": "HOW_TO",
        "summary": "Compare gross, deductions, taxes and net between two payroll runs to understand period-over-period movement.",
        "body": (
            "To compare periods, select two payroll runs and review gross, deductions, taxes and net totals. "
            "Assist returns deterministic comparisons with source references and flags partial data rather than "
            "inventing drivers for differences."
        ),
        "keywords": ["compare", "period", "variance", "gross", "net"],
        "jurisdiction_codes": [],
    },
    {
        "title": "Assist privacy and data handling",
        "content_type": "FAQ",
        "summary": "Conversation content is minimized and never used for training by default; Assist records are not the system of record.",
        "body": (
            "Zoiko Payroll Assist stores minimum necessary conversation and evidence records. It is not trained "
            "on customer conversations by default. Evidence records, policy decisions and action receipts are "
            "structured records separate from the rendered transcript — the conversation is not the system of "
            "record. Authoritative payroll records always take precedence over conversation memory."
        ),
        "keywords": ["privacy", "security", "data", "retention"],
        "jurisdiction_codes": [],
    },
    {
        "title": "Approval lifecycle states",
        "content_type": "STATE_DEFINITION",
        "summary": "Prepared, reviewed, approved, processed, paid and reconciled remain distinct states; the assistant never infers completion from chat.",
        "body": (
            "The payroll lifecycle uses distinct states: prepared, reviewed, approved, processed, paid and "
            "reconciled. No component may infer successful approval, payment settlement, filing acceptance or "
            "reconciliation from conversation text. Payment states — prepared, released, submitted, accepted, "
            "settled and reconciled — remain distinct."
        ),
        "keywords": ["state", "approval", "payment", "lifecycle"],
        "jurisdiction_codes": [],
    },
]


def ensure_default_kb(db: Session) -> None:
    """Idempotently seed the governed knowledge base (global platform content)."""
    existing = db.query(AssistKbItem).filter(AssistKbItem.organization_id.is_(None)).count()
    if existing > 0:
        return

    source_map = {}
    for src in DEFAULT_SOURCES:
        row = (
            db.query(AssistKbSource)
            .filter(AssistKbSource.name == src["name"], AssistKbSource.organization_id.is_(None))
            .first()
        )
        if row is None:
            row = AssistKbSource(
                name=src["name"],
                source_type=src["source_type"],
                authority_tier=src["authority_tier"],
                state=KnowledgeSourceState.ACTIVE.value,
                owner="Platform",
            )
            db.add(row)
            db.flush()
        source_map[src["name"]] = row.id

    default_source_id = source_map.get(DEFAULT_SOURCES[0]["name"])

    for idx, item in enumerate(DEFAULT_KB_ITEMS):
        db.add(
            AssistKbItem(
                source_id=default_source_id,
                organization_id=None,
                content_type=item["content_type"],
                title=item["title"],
                body=item["body"],
                summary=item["summary"],
                language="en",
                jurisdiction_codes=item["jurisdiction_codes"],
                state=KnowledgeState.PUBLISHED.value,
                authority=AuthorityTier.TIER_2_APPROVED_PRIMARY.value,
                version=1,
                effective_from=None,
                effective_to=None,
                published_at=datetime.now(),
                created_by=None,
            )
        )
    db.commit()
    logger.info("Seeded %s default knowledge base items.", len(DEFAULT_KB_ITEMS))
