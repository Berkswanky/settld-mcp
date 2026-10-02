"""
Settld MCP server — custom tools for the Settld tenancy agent on AgenticOrg.

Rails covered (all MOCK / SANDBOX, scripted for demo scenarios):
  * Voice  (Gnani-style)          represent_counterparty, capture_commitment, chase_until_resolution
  * Logistics (Delhivery-style)   verify_location, create_physical_move, track_and_prove_delivery,
                                  recover_logistics_failure
  * Field service (Urban Co mock) find_professional, get_quote, book_visit, capture_completion,
                                  check_fix_status, request_rework
  * Mission / mandate / evidence  create_mission, get_mission, update_mission_state, set_mandate,
                                  enforce_mandate, add_claim, get_fact_status, add_commitment,
                                  list_open_commitments, purpose_evidence_gate, create_closure_receipt
  * Payments (sandbox simulation) simulate_payment
  * Demo helpers                  list_demo_properties, reset_demo

State is in memory: it resets when the server restarts. Fine for a demo.
"""

import os
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

IST = ZoneInfo("Asia/Kolkata")
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False)

mcp = FastMCP(
    "settld-tools",
    instructions=(
        "Tools for Settld, a renter-side tenancy agent. All rails are sandbox/mock. "
        "Rail success is evidence only; a mission closes only on verified real-world outcome. "
        "Call enforce_mandate before any consequential action and purpose_evidence_gate before any payment."
    ),
    host="0.0.0.0",
    port=int(os.environ.get("PORT", "8000")),
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

# --------------------------------------------------------------------------------------
# Demo data
# --------------------------------------------------------------------------------------

SOURCE_RANK = {"document": 1, "society": 2, "property_manager": 2, "owner": 3, "landlord": 3,
               "broker": 4, "listing": 5, "hearsay": 6}
SOCIETY_FACTS = {"bachelors_allowed", "pets_allowed", "non_veg_allowed", "move_in_timings"}
HEDGES = ["should be fine", "should be ok", "dekh lenge", "mostly", "i think", "probably",
          "maybe", "shayad", "ho jayega", "not sure"]

# Scripted answers: PROPERTIES[pid]["script"][role][topic] -> (statement, value)
PROPERTIES = {
    "P1": {
        "name": "Skyline Heights, Flat 1204", "address": "Skyline Heights, Andheri West, Mumbai 400053",
        "bhk": 2, "rent": 48000, "deposit": 96000, "available_from": "2026-10-01",
        "contacts": {"broker": "Sameer (broker)", "owner": "Mr. Kulkarni (owner)", "society": "Skyline Heights society office"},
        "script": {
            "broker":  {"bachelors_allowed": ("Haan, bachelors chalega, owner is fine with it.", True),
                        "rent_amount": ("Rent is 48,000 per month.", 48000)},
            "owner":   {"bachelors_allowed": ("Yes, bachelors are allowed. I have rented to working professionals before.", True),
                        "rent_amount": ("Rent is 48,000, deposit two months.", 48000),
                        "available_from": ("Flat is free from 1st October.", "2026-10-01")},
            "society": {"bachelors_allowed": ("Yes, our bylaws allow bachelor tenants with police verification. I will send the rule on WhatsApp.", True)},
        },
    },
    "P2": {
        "name": "ABC Residency, Flat 302", "address": "ABC Residency, Powai, Mumbai 400076",
        "bhk": 2, "rent": 46000, "deposit": 92000, "available_from": "2026-10-01",
        "contacts": {"broker": "Rakesh (broker)", "owner": "Mrs. Shah (owner)", "society": "ABC Residency property manager"},
        "script": {
            "broker":  {"bachelors_allowed": ("Bachelors should be fine, don't worry.", True),
                        "rent_amount": ("46,000 rent, very good deal.", 46000)},
            "owner":   {"bachelors_allowed": ("No, I prefer a family. Bachelors are not allowed.", False),
                        "rent_amount": ("46,000.", 46000)},
            "society": {"bachelors_allowed": ("Society rules do not permit bachelor tenants in this tower.", False)},
        },
    },
    "P3": {
        "name": "Green Park Villa, Flat 7", "address": "Green Park, Bandra East, Mumbai 400051",
        "bhk": 2, "rent": 53000, "deposit": 106000, "available_from": "2026-10-05",
        "contacts": {"broker": "Imran (broker)", "owner": "Mr. D'Souza (owner)", "society": "Green Park office"},
        "script": {
            "broker":  {"bachelors_allowed": ("Yes, bachelors allowed.", True),
                        "rent_amount": ("Owner was saying 50,000.", 50000)},
            "owner":   {"bachelors_allowed": ("Bachelors are fine, it is an independent building, no society restriction.", True),
                        "rent_amount": ("I will not go below 53,000.", 53000),
                        "available_from": ("Available from 5th October.", "2026-10-05")},
            "society": {"bachelors_allowed": ("This is an independent building, owner decides.", True)},
        },
    },
    "P4": {
        "name": "Lakeview Towers, 5B", "address": "Lakeview Towers, Vikhroli, Mumbai 400079",
        "bhk": 2, "rent": 45000, "deposit": 90000, "available_from": "2026-10-01",
        "contacts": {"broker": "Neha (broker)", "owner": "Mr. Iyer (owner)", "society": "Lakeview society office"},
        "script": {
            "broker":  {"bachelors_allowed": ("Dekh lenge, I will ask the owner.", None),
                        "rent_amount": ("45,000.", 45000)},
            "owner":   {},          # never answers -> no_answer
            "society": {},          # never answers -> no_answer
        },
    },
}

PROFESSIONALS = [
    {"professional_id": "PRO-RAVI", "name": "Ravi Plumbing Services", "category": "plumber", "rating": 4.7,
     "jobs_done": 812, "earliest_slot": "Today 16:00", "verified": True},
    {"professional_id": "PRO-QFIX", "name": "QuickFix Home Repairs", "category": "plumber", "rating": 4.4,
     "jobs_done": 341, "earliest_slot": "Today 14:00", "verified": True},
    {"professional_id": "PRO-AMIT", "name": "Amit Electricals", "category": "electrician", "rating": 4.8,
     "jobs_done": 1203, "earliest_slot": "Tomorrow 10:00", "verified": True},
]
QUOTES = {"PRO-RAVI": 2400, "PRO-QFIX": 5800, "PRO-AMIT": 1800}


ROLE_ALIASES = {
    "society": "society", "society_office": "society", "society office": "society", "rwa": "society",
    "society_secretary": "society", "secretary": "society", "society_manager": "society",
    "property_manager": "property_manager", "property manager": "property_manager", "manager": "property_manager",
    "owner": "owner", "landlord": "landlord", "property_owner": "owner", "house_owner": "owner",
    "broker": "broker", "agent": "broker", "real_estate_agent": "broker", "dealer": "broker",
    "vendor": "vendor", "professional": "vendor", "plumber": "vendor", "electrician": "vendor",
    "logistics": "logistics", "courier": "logistics", "document": "document", "listing": "listing",
}


def _role(r):
    """Normalise a counterparty/source role ("Society Office" -> "society")."""
    if not r:
        return r
    k = r.strip().lower().replace("-", "_")
    return ROLE_ALIASES.get(k) or ROLE_ALIASES.get(k.replace("_", " ")) or ROLE_ALIASES.get(k.split("_")[0], k)


def _fresh_state():
    return {"missions": {}, "mandates": {}, "claims": [], "commitments": {}, "calls": {},
            "attempts": {}, "moves": {}, "quotes": {}, "bookings": {}, "payments": {},
            "gates": {}, "decisions": {}}


S = _fresh_state()
SERVER_STARTED_AT = datetime.now(IST).isoformat(timespec="seconds")
SERVER_INSTANCE = uuid.uuid4().hex[:6].upper()


def _now():
    return datetime.now(IST)


def _id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _log(mission_id, event, detail):
    m = S["missions"].get(mission_id)
    if m is not None:
        m["timeline"].append({"at": _now().isoformat(timespec="seconds"), "event": event, "detail": detail})


# --------------------------------------------------------------------------------------
# Mission store
# --------------------------------------------------------------------------------------

@mcp.tool(annotations=WRITE)
def create_mission(mission_type: str, goal: str, hard_constraints: dict, closure_condition: str,
                   principals: list[str], soft_preferences: dict | None = None) -> dict:
    """Create a tenancy mission (CAPTURE state).
    mission_type: HOUSE_HUNT | MOVE_IN | RENT_AND_PAYMENTS | REPAIR | RENEWAL | EXIT | GENERAL_COORDINATION.
    hard_constraints example: {"bachelors_allowed": true, "rent_max": 50000, "bhk": 2, "move_in_by": "2026-10-01"}."""
    mid = _id("MSN")
    S["missions"][mid] = {"mission_id": mid, "mission_type": mission_type, "goal": goal,
                          "hard_constraints": hard_constraints, "soft_preferences": soft_preferences or {},
                          "closure_condition": closure_condition, "principals": principals,
                          "state": "CAPTURE", "replans": 0, "timeline": [], "created_at": _now().isoformat(timespec="seconds")}
    _log(mid, "created", goal)
    return {"mission_id": mid, "state": "CAPTURE",
            "mission_card": f"MISSION CREATED\nGoal: {goal}\nHard constraints: {hard_constraints}\nYour action needed: None right now"}


@mcp.tool(annotations=READ)
def get_mission(mission_id: str) -> dict:
    """Get a mission with its state, timeline, claims and open commitments."""
    m = S["missions"].get(mission_id)
    if not m:
        return {"error": "mission_not_found", "mission_id": mission_id}
    return {**m,
            "claims": [c for c in S["claims"] if c["mission_id"] == mission_id],
            "open_commitments": [c for c in S["commitments"].values() if c["mission_id"] == mission_id and c["status"] == "open"]}


VALID_STATES = ["CAPTURE", "VERIFY", "PLAN", "EXECUTE", "MONITOR", "VERIFY_OUTCOME", "CLOSED",
                "HUMAN_REQUIRED", "BLOCKED", "CANCELLED"]


@mcp.tool(annotations=WRITE)
def update_mission_state(mission_id: str, new_state: str, reason: str) -> dict:
    """Move a mission to a new lifecycle state. Replans (any move back to PLAN) are capped at 5; the 6th
    moves the mission to BLOCKED. CLOSED is only allowed after create_closure_receipt verified the outcome."""
    m = S["missions"].get(mission_id)
    if not m:
        return {"error": "mission_not_found"}
    if new_state not in VALID_STATES:
        return {"error": "invalid_state", "valid_states": VALID_STATES}
    if new_state == "CLOSED" and not m.get("receipt"):
        return {"error": "closure_not_verified", "message": "Call create_closure_receipt with verified evidence first."}
    if new_state == "PLAN" and m["state"] in ("VERIFY_OUTCOME", "MONITOR", "EXECUTE"):
        m["replans"] += 1
        if m["replans"] > 5:
            new_state, reason = "BLOCKED", f"Replan limit reached. Last reason: {reason}"
    old = m["state"]
    m["state"] = new_state
    _log(mission_id, "state_change", f"{old} -> {new_state}: {reason}")
    return {"mission_id": mission_id, "from": old, "to": new_state, "replans": m["replans"], "reason": reason}


# --------------------------------------------------------------------------------------
# Mandate guard
# --------------------------------------------------------------------------------------

DEFAULT_MANDATE = {
    "rent_ceiling": 50000, "deposit_ceiling": 100000, "token_amount_limit": 10000,
    "repair_autonomous_limit": 3000, "monthly_spend_cap": 10000, "single_payment_hard_limit": 25000,
    "allowed_counterparties": ["broker", "owner", "landlord", "society", "property_manager", "vendor", "logistics"],
    "standing_rent_mandate": {"payee": None, "amount": None},
    "quiet_hours": {"start": "20:00", "end": "09:00"},
    "approval_rule_contractual": "all_principals",
    "expires_on": (datetime.now(IST) + timedelta(days=90)).date().isoformat(),
    "revoked": False,
}

ALWAYS_HUMAN = {"sign_agreement", "change_agreement", "pay_security_deposit", "waive_right",
                "accept_deduction", "choose_property", "share_identity_document"}
NEVER_DO = {"impersonate_human", "reveal_ceiling", "pay_without_gate", "delete_evidence"}
CONTACT_ACTIONS = {"call", "message", "schedule_visit", "negotiate"}


@mcp.tool(annotations=WRITE)
def set_mandate(mission_id: str, overrides: dict | None = None) -> dict:
    """Set the renter's mandate for a mission. Unspecified fields use defaults (rent_ceiling 50000,
    repair_autonomous_limit 3000, monthly_spend_cap 10000, single payments > 25000 always need approval,
    quiet hours 20:00-09:00 IST). Use overrides={"revoked": true} to revoke authority instantly."""
    mandate = {**DEFAULT_MANDATE, **(overrides or {})}
    S["mandates"][mission_id] = mandate
    _log(mission_id, "mandate_set", str(overrides or "defaults"))
    return {"mission_id": mission_id, "mandate": mandate}


@mcp.tool(annotations=WRITE)
def enforce_mandate(mission_id: str, action_type: str, amount: float = 0, counterparty_role: str = "",
                    purpose: str = "", payee: str = "", at_time: str = "") -> dict:
    """Mandate Guard. Returns ALLOW, DENY or HUMAN_REQUIRED for a proposed action, with the rule that fired.
    Must be called before every consequential action. Checks run live (revocation is never cached).
    action_type examples: call, message, schedule_visit, negotiate, accept_rent, pay_token, pay_repair,
    pay_rent, pay_security_deposit, sign_agreement, share_identity_document, accept_deduction, choose_property.
    at_time: optional ISO time (IST) to test quiet hours; defaults to now."""
    md = S["mandates"].get(mission_id) or {**DEFAULT_MANDATE}
    counterparty_role = _role(counterparty_role)
    when = datetime.fromisoformat(at_time).astimezone(IST) if at_time else _now()

    def decide(decision, rule, note=""):
        did = _id("DEC")
        rec = {"decision_id": did, "mission_id": mission_id, "action_type": action_type, "amount": amount,
               "decision": decision, "rule": rule, "note": note, "at": _now().isoformat(timespec="seconds")}
        S["decisions"][did] = rec
        _log(mission_id, "mandate_decision", f"{action_type} {amount or ''} -> {decision} ({rule})")
        return rec

    if md.get("revoked"):
        return decide("DENY", "R1_mandate_revoked", "Renter revoked authority. Stop all actions.")
    if when.date().isoformat() > md["expires_on"]:
        return decide("DENY", "R1_mandate_expired", "Ask renter to renew the mandate.")
    if action_type in NEVER_DO:
        return decide("DENY", "R2_never_do_list")
    if action_type in ALWAYS_HUMAN:
        return decide("HUMAN_REQUIRED", "R3_always_ask", "This action always needs the renter (all principals if contractual).")
    if counterparty_role and counterparty_role not in md["allowed_counterparties"]:
        return decide("HUMAN_REQUIRED", "R4_counterparty_not_allowed")

    # Quiet hours apply to contacting people.
    if action_type in CONTACT_ACTIONS:
        h = when.hour + when.minute / 60
        if h >= 20 or h < 9:
            nxt = (when + timedelta(days=1 if h >= 20 else 0)).replace(hour=9, minute=0, second=0, microsecond=0)
            return decide("DENY", "R7_quiet_hours", f"Reschedule to {nxt.isoformat(timespec='minutes')}")

    if action_type in ("accept_rent", "negotiate") and amount and amount > md["rent_ceiling"]:
        return decide("HUMAN_REQUIRED", "R5_rent_above_ceiling", f"{amount} > ceiling {md['rent_ceiling']}")

    if action_type.startswith("pay_"):
        srm = md.get("standing_rent_mandate") or {}
        if action_type == "pay_rent" and srm.get("payee") and payee == srm["payee"] and amount <= (srm.get("amount") or 0):
            return decide("ALLOW", "R5a_standing_rent_mandate", "Covered by renter-approved standing rent mandate.")
        if amount > md["single_payment_hard_limit"]:
            return decide("HUMAN_REQUIRED", "R5_single_payment_hard_limit", f"{amount} > {md['single_payment_hard_limit']}")
        limit = {"pay_token": md["token_amount_limit"], "pay_repair": md["repair_autonomous_limit"]}.get(action_type)
        if limit is None:
            return decide("HUMAN_REQUIRED", "R8_no_autonomous_limit_for_purpose")
        if amount > limit:
            return decide("HUMAN_REQUIRED", "R5_amount_above_limit", f"{amount} > {limit}")
        spent = sum(p["amount"] for p in S["payments"].values() if p["mission_id"] == mission_id
                    and p["status"] == "SUCCESS" and p["autonomous"])
        if spent + amount > md["monthly_spend_cap"]:
            return decide("HUMAN_REQUIRED", "R5_monthly_cap", f"spent {spent} + {amount} > {md['monthly_spend_cap']}")
        return decide("ALLOW", "R9_within_mandate", "Payment still needs purpose_evidence_gate before release.")

    return decide("ALLOW", "R9_within_mandate")


# --------------------------------------------------------------------------------------
# Claims ledger (Verifier)
# --------------------------------------------------------------------------------------

def _classify(source_role, statement, value):
    rank = SOURCE_RANK.get(source_role, 6)
    hedged = any(h in statement.lower() for h in HEDGES)
    if value is None or hedged:
        return "unknown", rank, "Hedged or no clear answer. Seek a higher-ranked source."
    if rank >= 4:
        return "unknown", rank, "Source rank too low for a hard constraint. Confirm with owner or society."
    if value is False:
        return "failed", rank, "Clear 'no' from an authoritative source."
    return "verified", rank, "Clear answer from an authoritative source."


def _fact_status(mission_id, subject_id, fact):
    cs = [c for c in S["claims"] if c["mission_id"] == mission_id and c["subject_id"] == subject_id and c["fact"] == fact]
    if not cs:
        return {"fact": fact, "status": "unknown", "reason": "No claims yet.", "claims": []}
    authoritative = [c for c in cs if c["source_rank"] <= 3 and c["status"] in ("verified", "failed")]
    best_rank = min((c["source_rank"] for c in authoritative), default=None)
    top = [c for c in authoritative if c["source_rank"] == best_rank]
    values = {str(c["value"]) for c in top}
    lower_disagree = {str(c["value"]) for c in cs if c["value"] is not None} - values
    if not authoritative:
        status, reason = "unknown", "Only hedged or low-rank claims. Unknown is not Yes."
    elif len(values) > 1:
        status, reason = "contested", "Sources of the same rank disagree. Escalate to a higher authority."
    elif fact in SOCIETY_FACTS and best_rank == 3:
        # Society rules need the society (rank 1-2) when a society exists.
        others = {str(c["value"]) for c in cs if c["value"] is not None and c["source_rank"] != 3}
        if others - values:
            status = "contested"
            reason = "Owner and broker disagree on a society rule. Escalate to the society office for a decision."
        else:
            status = "verified_with_risk"
            reason = "Only the owner confirmed a society rule. Confirm with the society unless the building is independent."
    else:
        status = top[0]["status"]
        reason = f"Decided by {top[0]['source_role']} (rank {best_rank})."
        if lower_disagree:
            reason += f" Lower-ranked sources said otherwise ({', '.join(lower_disagree)}); kept on record."
    return {"fact": fact, "subject_id": subject_id, "status": status, "reason": reason, "claims": cs}


@mcp.tool(annotations=WRITE)
def add_claim(mission_id: str, subject_id: str, fact: str, value: bool | int | float | str | None,
              source_role: str, statement: str, channel: str = "call", evidence_ref: str = "") -> dict:
    """Record a claim in the evidence ledger and classify it (verified / unknown / failed) using source rank
    (document 1, society 2, owner 3, broker 4, listing 5) and hedge detection ("should be fine", "dekh lenge"
    = unknown). Returns the claim plus the combined status of that fact across all sources (may be contested)."""
    source_role = _role(source_role)
    status, rank, why = _classify(source_role, statement, value)
    claim = {"claim_id": _id("CLM"), "mission_id": mission_id, "subject_id": subject_id, "fact": fact,
             "value": value, "source_role": source_role, "source_rank": rank, "statement": statement,
             "channel": channel, "evidence_ref": evidence_ref, "status": status, "why": why,
             "stated_at": _now().isoformat(timespec="seconds")}
    S["claims"].append(claim)
    _log(mission_id, "claim", f"{subject_id}.{fact}={value} from {source_role} -> {status}")
    return {"claim": claim, "fact_status": _fact_status(mission_id, subject_id, fact)}


@mcp.tool(annotations=READ)
def get_fact_status(mission_id: str, subject_id: str, fact: str) -> dict:
    """Combined status of a fact for a property/job: verified, unknown, contested or failed, with all claims
    (who said what, when) for the 'Why?' explanation."""
    return _fact_status(mission_id, subject_id, fact)


# --------------------------------------------------------------------------------------
# Voice (Gnani-style)
# --------------------------------------------------------------------------------------

@mcp.tool(annotations=READ)
def list_demo_properties() -> dict:
    """List demo property leads (P1-P4) with listed rent and contacts. Listing data is rank 5: leads only."""
    return {"properties": [{"property_id": k, "name": v["name"], "address": v["address"], "bhk": v["bhk"],
                            "listed_rent": v["rent"], "listed_deposit": v["deposit"], "contacts": v["contacts"]}
                           for k, v in PROPERTIES.items()]}


@mcp.tool(annotations=WRITE)
def represent_counterparty(mission_id: str, property_id: str, counterparty_role: str, question_topic: str,
                           language: str = "hinglish") -> dict:
    """Place an AI voice call (sandbox) to a counterparty on the renter's behalf and ask one question.
    The agent always discloses it is an AI calling for the renter.
    counterparty_role: broker | owner | society. question_topic: bachelors_allowed | rent_amount | available_from.
    Returns disposition (answered / no_answer), transcript, the stated value, and a call_id for evidence.
    Call enforce_mandate(action_type='call') first."""
    p = PROPERTIES.get(property_id)
    if not p:
        return {"error": "unknown_property", "valid": list(PROPERTIES)}
    counterparty_role = _role(counterparty_role)
    if counterparty_role == "property_manager":
        counterparty_role = "society"
    key = (mission_id, property_id, counterparty_role)
    S["attempts"][key] = S["attempts"].get(key, 0) + 1
    call_id = _id("CALL")
    who = p["contacts"].get(counterparty_role, counterparty_role)
    opening = f"Settld: Namaste, I'm Settld, an AI assistant calling on behalf of the renter about {p['name']}."
    answer = p["script"].get(counterparty_role, {}).get(question_topic)
    if answer is None:
        rec = {"call_id": call_id, "mission_id": mission_id, "property_id": property_id, "counterparty": who,
               "role": counterparty_role, "attempt": S["attempts"][key], "disposition": "no_answer",
               "transcript": [opening + " [No answer — call went unanswered]"], "stated_value": None,
               "statement": "", "ai_disclosed": True, "at": _now().isoformat(timespec="seconds")}
    else:
        statement, value = answer
        rec = {"call_id": call_id, "mission_id": mission_id, "property_id": property_id, "counterparty": who,
               "role": counterparty_role, "attempt": S["attempts"][key], "disposition": "answered",
               "transcript": [opening, f"Settld: Could you confirm {question_topic.replace('_', ' ')}?",
                              f"{who}: {statement}",
                              "Settld: Thank you. Could you also share this on WhatsApp in writing?"],
               "stated_value": value, "statement": statement, "ai_disclosed": True,
               "recording_ref": f"rec://{call_id}", "at": _now().isoformat(timespec="seconds")}
    S["calls"][call_id] = rec
    _log(mission_id, "call", f"{who} ({counterparty_role}) {question_topic}: {rec['disposition']}")
    return rec


@mcp.tool(annotations=WRITE)
def capture_commitment(call_id: str) -> dict:
    """Extract commitments (who promised what, by when) from a call transcript. Vague promises
    ("dekh lenge", "kal tak") are marked unresolved, never as firm promises."""
    c = S["calls"].get(call_id)
    if not c:
        return {"error": "call_not_found"}
    out = []
    st = c.get("statement", "").lower()
    if "send" in st or "whatsapp" in st:
        due = (_now() + timedelta(hours=4)).isoformat(timespec="minutes")
        out.append({"who": c["counterparty"], "what": "Share written confirmation on WhatsApp", "by_when": due, "firm": True})
    if any(h in st for h in ("dekh lenge", "i will ask", "kal tak")):
        out.append({"who": c["counterparty"], "what": "Get back with an answer", "by_when": None, "firm": False,
                    "note": "Unresolved — ask for a specific date and time."})
    if c["disposition"] == "no_answer":
        out.append({"who": c["counterparty"], "what": "Call not answered", "by_when": None, "firm": False,
                    "note": "Retry per chase policy."})
    return {"call_id": call_id, "commitments": out}


@mcp.tool(annotations=WRITE)
def add_commitment(mission_id: str, who: str, what: str, by_when: str = "", firm: bool = True) -> dict:
    """Register a commitment for the Chaser to track."""
    cid = _id("CMT")
    S["commitments"][cid] = {"commitment_id": cid, "mission_id": mission_id, "who": who, "what": what,
                             "by_when": by_when or None, "firm": firm, "status": "open", "attempts": 0}
    _log(mission_id, "commitment", f"{who}: {what} by {by_when or 'unspecified'}")
    return S["commitments"][cid]


@mcp.tool(annotations=READ)
def list_open_commitments(mission_id: str) -> dict:
    """List open commitments for a mission."""
    return {"open": [c for c in S["commitments"].values() if c["mission_id"] == mission_id and c["status"] == "open"]}


@mcp.tool(annotations=WRITE)
def chase_until_resolution(commitment_id: str, outcome: str = "pending") -> dict:
    """Chase policy for an open commitment. outcome: pending | fulfilled | missed.
    Policy: 3 attempts per channel, 2 hours apart, 09:00-20:00 IST only; channel order call -> whatsapp ->
    alternate_contact -> escalate_to_renter. Returns the next action and when."""
    c = S["commitments"].get(commitment_id)
    if not c:
        return {"error": "commitment_not_found"}
    if outcome == "fulfilled":
        c["status"] = "fulfilled"
        _log(c["mission_id"], "commitment_fulfilled", c["what"])
        return {"commitment_id": commitment_id, "status": "fulfilled", "next_action": "verify_outcome"}
    c["attempts"] += 1
    channels = ["call", "whatsapp", "alternate_contact"]
    idx = (c["attempts"] - 1) // 3
    if idx >= len(channels):
        c["status"] = "escalated"
        _log(c["mission_id"], "escalate", f"All channels exhausted for: {c['what']}")
        return {"commitment_id": commitment_id, "status": "escalated", "next_action": "escalate_to_renter",
                "message": "All channels exhausted. Raise an Exception Card with what was tried."}
    nxt = _now() + timedelta(hours=2)
    if nxt.hour >= 20 or nxt.hour < 9:
        nxt = (nxt + timedelta(days=1 if nxt.hour >= 20 else 0)).replace(hour=9, minute=0, second=0, microsecond=0)
    return {"commitment_id": commitment_id, "status": "open", "attempt": c["attempts"],
            "next_channel": channels[idx], "next_attempt_at": nxt.isoformat(timespec="minutes"),
            "tip": "Use the Agent Scheduler connector to schedule the follow-up at next_attempt_at."}


# --------------------------------------------------------------------------------------
# Logistics (Delhivery-style)
# --------------------------------------------------------------------------------------

@mcp.tool(annotations=READ)
def verify_location(address: str) -> dict:
    """Validate and standardise an address (sandbox). Delivery history is never proof of tenancy eligibility."""
    if len(address.strip()) < 10 or "unknown" in address.lower():
        return {"valid": False, "reason": "Address incomplete or not found. Ask for a corrected address."}
    pin = next((w for w in address.replace(",", " ").split() if w.isdigit() and len(w) == 6), None)
    return {"valid": True, "standardised": address.strip().title(), "pincode": pin or "unknown",
            "coordinates": {"lat": 19.1 + (hash(address) % 100) / 1000, "lng": 72.85 + (hash(address) % 50) / 1000},
            "serviceable": True}


@mcp.tool(annotations=WRITE)
def create_physical_move(mission_id: str, pickup_address: str, drop_address: str, items: list[str],
                         date: str, slot: str, idempotency_key: str) -> dict:
    """Book a pickup/shipment for belongings or parts (sandbox). Idempotent: the same idempotency_key returns
    the existing booking instead of double-booking."""
    for m in S["moves"].values():
        if m["idempotency_key"] == idempotency_key:
            return {**m, "note": "Existing booking returned (idempotent)."}
    wb = _id("WB")
    S["moves"][wb] = {"waybill": wb, "mission_id": mission_id, "pickup": pickup_address, "drop": drop_address,
                      "items": items, "date": date, "slot": slot, "idempotency_key": idempotency_key,
                      "status": "PICKUP_SCHEDULED", "track_calls": 0, "rescheduled": False, "scans": []}
    _log(mission_id, "logistics_booked", f"{wb} {date} {slot}")
    return S["moves"][wb]


@mcp.tool(annotations=READ)
def track_and_prove_delivery(waybill: str) -> dict:
    """Track a shipment. Demo script: first pickup attempt fails (NDR: customer not available) unless
    rescheduled; after reschedule it moves to IN_TRANSIT then DELIVERED with POD. 'Delivered' is evidence
    only — the renter must still confirm items arrived intact before the mission can close."""
    m = S["moves"].get(waybill)
    if not m:
        return {"error": "waybill_not_found"}
    m["track_calls"] += 1
    if not m["rescheduled"]:
        m["status"] = "NDR"
        m["ndr"] = {"code": "CUSTOMER_NOT_AVAILABLE", "allowed_actions": ["RE-ATTEMPT", "PICKUP_RESCHEDULE"]}
    else:
        m["status"] = "IN_TRANSIT" if m["track_calls"] % 2 == 1 else "DELIVERED"
        if m["status"] == "DELIVERED":
            m["pod"] = {"signed_by": "Security desk", "photo_ref": f"pod://{waybill}", "at": _now().isoformat(timespec="minutes")}
    m["scans"].append({"status": m["status"], "at": _now().isoformat(timespec="minutes")})
    return {**m, "closure_note": "Rail status is evidence only. Ask renter to confirm receipt."}


@mcp.tool(annotations=WRITE)
def recover_logistics_failure(waybill: str, action: str, new_date: str = "", new_slot: str = "") -> dict:
    """Recover a failed pickup/delivery. action: RE-ATTEMPT | PICKUP_RESCHEDULE (only supported NDR actions)."""
    m = S["moves"].get(waybill)
    if not m:
        return {"error": "waybill_not_found"}
    if m["status"] != "NDR":
        return {"error": "no_failure_to_recover", "status": m["status"]}
    if action not in ("RE-ATTEMPT", "PICKUP_RESCHEDULE"):
        return {"error": "unsupported_action", "allowed": ["RE-ATTEMPT", "PICKUP_RESCHEDULE"]}
    m["rescheduled"] = True
    m["status"] = "PICKUP_RESCHEDULED"
    m["track_calls"] = 0
    if new_date:
        m["date"] = new_date
    if new_slot:
        m["slot"] = new_slot
    _log(m["mission_id"], "logistics_recovered", f"{waybill} {action}")
    return m


# --------------------------------------------------------------------------------------
# Field service (Urban Company mock)
# --------------------------------------------------------------------------------------

@mcp.tool(annotations=READ)
def find_professional(category: str, location: str = "Mumbai") -> dict:
    """Find verified home-service professionals. category: plumber | electrician."""
    pros = [p for p in PROFESSIONALS if p["category"] == category.lower()]
    return {"category": category, "location": location, "professionals": pros}


@mcp.tool(annotations=WRITE)
def get_quote(mission_id: str, professional_id: str, problem: str) -> dict:
    """Get an itemised quote (sandbox). Demo: Ravi Plumbing quotes 2,400; QuickFix quotes 5,800."""
    if professional_id not in QUOTES:
        return {"error": "unknown_professional"}
    qid = _id("QTE")
    total = QUOTES[professional_id]
    S["quotes"][qid] = {"quote_id": qid, "mission_id": mission_id, "professional_id": professional_id,
                        "problem": problem, "total": total, "currency": "INR",
                        "items": [{"item": "Visit and diagnosis", "amount": 300},
                                  {"item": "Repair labour and parts", "amount": total - 300}],
                        "valid_hours": 24}
    _log(mission_id, "quote", f"{professional_id}: {total}")
    return S["quotes"][qid]


@mcp.tool(annotations=WRITE)
def book_visit(quote_id: str, slot: str, idempotency_key: str) -> dict:
    """Book a professional against a quote. Call enforce_mandate first. Idempotent on idempotency_key."""
    for b in S["bookings"].values():
        if b["idempotency_key"] == idempotency_key:
            return {**b, "note": "Existing booking returned (idempotent)."}
    q = S["quotes"].get(quote_id)
    if not q:
        return {"error": "quote_not_found"}
    bid = _id("BKG")
    S["bookings"][bid] = {"booking_id": bid, "quote_id": quote_id, "mission_id": q["mission_id"],
                          "professional_id": q["professional_id"], "slot": slot, "amount": q["total"],
                          "status": "BOOKED", "visits": 0, "reworks": 0, "idempotency_key": idempotency_key,
                          "server_instance": SERVER_INSTANCE}
    _log(q["mission_id"], "booked", f"{bid} {slot}")
    return S["bookings"][bid]


@mcp.tool(annotations=WRITE)
def capture_completion(booking_id: str) -> dict:
    """Professional marks the job complete with before/after photos. This is NOT the outcome check —
    call check_fix_status (renter confirmation / 24h re-check) before any payment."""
    b = S["bookings"].get(booking_id)
    if not b:
        return {"error": "booking_not_found"}
    b["visits"] += 1
    b["status"] = "MARKED_COMPLETE_BY_PROFESSIONAL"
    _log(b["mission_id"], "completion_claimed", booking_id)
    return {"booking_id": booking_id, "status": b["status"], "professional_notes": "Replaced washer and sealed joint.",
            "photos": [f"photo://{booking_id}/before", f"photo://{booking_id}/after"], "warranty_days": 30}


@mcp.tool(annotations=READ)
def check_fix_status(booking_id: str) -> dict:
    """Independent outcome check (renter photo + 24h re-check, simulated). Demo: after the first visit the
    leak persists; after one rework it is fixed."""
    b = S["bookings"].get(booking_id)
    if not b:
        return {"error": "booking_not_found"}
    fixed = b["reworks"] >= 1
    b["status"] = "VERIFIED_FIXED" if fixed else "NOT_FIXED"
    _log(b["mission_id"], "outcome_check", f"{booking_id}: {b['status']}")
    return {"booking_id": booking_id, "fixed": fixed, "status": b["status"],
            "evidence": {"renter_photo": f"photo://{booking_id}/renter-check-{b['visits']}",
                         "checked_after_hours": 24},
            "next": "purpose_evidence_gate then pay" if fixed else "request_rework (do not pay)",
            "server_instance": SERVER_INSTANCE}


@mcp.tool(annotations=WRITE)
def request_rework(booking_id: str, failure_evidence: str) -> dict:
    """Request rework at no extra cost after a failed outcome check. After 2 failed reworks, switch vendor."""
    b = S["bookings"].get(booking_id)
    if not b:
        return {"error": "booking_not_found"}
    if b["reworks"] >= 2:
        return {"booking_id": booking_id, "status": "SWITCH_VENDOR", "message": "Two reworks failed. Book another professional and request refund."}
    b["reworks"] += 1
    b["status"] = "REWORK_BOOKED"
    _log(b["mission_id"], "rework", f"{booking_id} #{b['reworks']}: {failure_evidence}")
    return {"booking_id": booking_id, "status": b["status"], "rework_number": b["reworks"], "extra_cost": 0}


# --------------------------------------------------------------------------------------
# Payments (sandbox simulation) + purpose/evidence gate
# --------------------------------------------------------------------------------------

@mcp.tool(annotations=WRITE)
def purpose_evidence_gate(mission_id: str, purpose: str, payee: str, amount: float, evidence_ref: str) -> dict:
    """Release check before any payment: the purpose's real-world condition must be verified.
    purpose: repair (needs check_fix_status fixed, evidence_ref=booking_id) | token (needs all hard constraints
    verified for the property, evidence_ref=property_id) | rent (evidence_ref=agreement or mandate ref).
    Paying merely because the amount is under the cap is never enough."""
    ok, why = False, ""
    diag = {}
    if purpose == "repair":
        b = S["bookings"].get(evidence_ref.strip())
        if not b:
            why = (f"Booking {evidence_ref} not found on this server (known bookings: {list(S['bookings']) or 'none'}). "
                   "Hold payment.")
        elif b["status"] != "VERIFIED_FIXED":
            why = f"Fix not verified: booking status is {b['status']}. Run check_fix_status first. Hold payment."
        elif float(b["amount"]) != float(amount):
            why = f"Amount mismatch: quote was {b['amount']}, request is {amount}. Hold payment."
        else:
            ok, why = True, "Fix verified and amount matches quote."
        diag = {"booking_found": bool(b), "booking_status": b["status"] if b else None,
                "quoted_amount": b["amount"] if b else None}
    elif purpose == "token":
        m = S["missions"].get(mission_id, {})
        facts = [k for k in m.get("hard_constraints", {}) if k == "bachelors_allowed"] or ["bachelors_allowed"]
        statuses = {f: _fact_status(mission_id, evidence_ref, f)["status"] for f in facts}
        ok = all(s == "verified" for s in statuses.values())
        why = f"Hard constraints: {statuses}." + ("" if ok else " Not all verified. Hold payment.")
    elif purpose == "rent":
        ok, why = bool(evidence_ref), "Rent backed by agreement/standing mandate." if evidence_ref else "No agreement reference."
    else:
        why = "Unknown purpose. Hold payment and ask renter."
    gid = _id("GATE")
    S["gates"][gid] = {"gate_id": gid, "mission_id": mission_id, "purpose": purpose, "payee": payee,
                       "amount": amount, "condition_met": ok, "why": why, "diagnostics": diag,
                       "server_instance": SERVER_INSTANCE, "server_started_at": SERVER_STARTED_AT}
    _log(mission_id, "evidence_gate", f"{purpose} {amount} -> {'PASS' if ok else 'HOLD'}")
    return S["gates"][gid]


@mcp.tool(annotations=WRITE)
def simulate_payment(mission_id: str, payee: str, amount: float, purpose: str, mandate_decision_id: str,
                     gate_id: str, idempotency_key: str, approved_by_human: str = "") -> dict:
    """SANDBOX payment (Pine Labs stand-in). Requires an ALLOW decision from enforce_mandate (or a human approval
    name when the decision was HUMAN_REQUIRED) AND a passing purpose_evidence_gate. Idempotent: the same key never
    pays twice. Returns a verifiable receipt."""
    for p in S["payments"].values():
        if p["idempotency_key"] == idempotency_key:
            return {**p, "note": "Existing payment returned (idempotent, no double pay)."}
    d = S["decisions"].get(mandate_decision_id)
    g = S["gates"].get(gate_id)
    if not d:
        return {"status": "BLOCKED", "reason": "No mandate decision found."}
    if d["decision"] == "DENY":
        return {"status": "BLOCKED", "reason": f"Mandate denied ({d['rule']})."}
    if d["decision"] == "HUMAN_REQUIRED" and not approved_by_human:
        return {"status": "BLOCKED", "reason": "Human approval required. Raise an Exception Card."}
    if not g or not g["condition_met"]:
        return {"status": "BLOCKED", "reason": "Purpose evidence gate not passed."}
    pid = _id("PAY")
    S["payments"][pid] = {"payment_id": pid, "mission_id": mission_id, "payee": payee, "amount": amount,
                          "purpose": purpose, "status": "SUCCESS", "mode": "SANDBOX",
                          "autonomous": d["decision"] == "ALLOW", "approved_by": approved_by_human or "mandate",
                          "idempotency_key": idempotency_key, "receipt_ref": f"rcpt://{pid}",
                          "at": _now().isoformat(timespec="seconds")}
    _log(mission_id, "payment", f"{purpose} {amount} to {payee} SUCCESS (sandbox)")
    return S["payments"][pid]


# --------------------------------------------------------------------------------------
# Closure + demo helpers
# --------------------------------------------------------------------------------------

@mcp.tool(annotations=WRITE)
def create_closure_receipt(mission_id: str, outcome_summary: str, verified_evidence_refs: list[str],
                           renter_confirmed: bool) -> dict:
    """Generate the Closure Receipt. Refuses unless renter_confirmed is true and at least one verified evidence
    reference is given. After this, call update_mission_state(new_state='CLOSED')."""
    m = S["missions"].get(mission_id)
    if not m:
        return {"error": "mission_not_found"}
    if not renter_confirmed or not verified_evidence_refs:
        return {"error": "outcome_not_verified", "message": "Need renter confirmation and verified evidence."}
    calls = [c for c in S["calls"].values() if c["mission_id"] == mission_id]
    pays = [p for p in S["payments"].values() if p["mission_id"] == mission_id]
    receipt = {"receipt_id": _id("RCPT"), "mission_id": mission_id, "mission_type": m["mission_type"],
               "outcome": outcome_summary, "evidence": verified_evidence_refs,
               "calls_handled_by_settld": len(calls), "payments": [{"amount": p["amount"], "to": p["payee"],
               "purpose": p["purpose"], "receipt": p["receipt_ref"]} for p in pays],
               "renter_follow_ups": 0, "closed_at": _now().isoformat(timespec="seconds")}
    m["receipt"] = receipt
    _log(mission_id, "receipt", outcome_summary)
    return receipt


@mcp.tool(annotations=WRITE)
def reset_demo() -> dict:
    """Clear all missions, claims, calls, bookings and payments (demo reset)."""
    global S
    S = _fresh_state()
    return {"reset": True}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
