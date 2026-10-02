"""
Settld v2 — one Render service, five MCP connectors + faithful REST mocks.

  /gnani/mcp      REAL  Gnani (Vachana) speech-to-text and text-to-speech
  /telegram/mcp   REAL  Telegram Bot API: renter inbox (text, voice notes, button taps) and replies
  /delhivery/mcp  MOCK  Delhivery B2C API, same endpoint names and fields
  /pinelabs/mcp   MOCK  Pine Labs Online (Plural) API, same endpoint names and fields + sandbox checkout page
  /settld/mcp     3 capabilities no rail offers today + agent memory

REST mocks (callable with curl, same paths as the real APIs):
  /delhivery/c/api/pin-codes/json/        /delhivery/api/kinko/v1/invoice/charges/.json
  /delhivery/waybill/api/fetch/json/      /delhivery/api/cmu/create.json
  /delhivery/fm/request/new/              /delhivery/api/v1/packages/json/
  /delhivery/api/p/update                 /delhivery/api/p/edit
  /pinelabs/api/auth/v1/token             /pinelabs/api/pay/v1/paymentlink
  /pinelabs/api/pay/v1/paymentlink/{id}   /pinelabs/api/pay/v1/orders/{order_id}
  /pinelabs/api/pay/v1/refunds/{order_id} /pinelabs/checkout/{payment_link_id}   (renter-facing page)

Environment: GNANI_API_KEY, TELEGRAM_BOT_TOKEN, optional TELEGRAM_CHAT_ID, PUBLIC_BASE_URL,
GNANI_STT_LANG (hi-IN), GNANI_TTS_MODEL (timbre-v2.5), GNANI_TTS_VOICE (Kaveri), GNANI_TTS_LANG (hi-IN).
"""

import base64
import contextlib
import hashlib
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Mount, Route

IST = ZoneInfo("Asia/Kolkata")
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False)
SEC = TransportSecuritySettings(enable_dns_rebinding_protection=False)
BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://settld-mcp.onrender.com").rstrip("/")


def now():
    return datetime.now(IST)


def ts():
    return now().isoformat(timespec="seconds")


def log(tag, msg):
    print(f"[{tag}] {msg}", flush=True)


def new_mcp(name, instructions):
    return FastMCP(name, instructions=instructions, stateless_http=True, json_response=True,
                   streamable_http_path="/mcp", transport_security=SEC)


# ======================================================================================
# Simulation switches (failure modes). All ON by default; change with the sim_config tool.
# ======================================================================================
SIM_DEFAULTS = {
    "pickup_no_rider_first_slot": True,   # first pickup request for a date -> no rider available
    "create_timeout_first_try": True,     # first cmu/create for an order times out (but the shipment WAS created)
    "track_malformed_first_call": True,   # first tracking call per waybill returns a malformed body
    "delivery_ndr_once": True,            # first delivery attempt fails: consignee unavailable
    "payment_status_timeout_once": True,  # first payment-link status check times out
}
SIM = dict(SIM_DEFAULTS)


# ======================================================================================
# DELHIVERY mock (B2C API). Field names follow Delhivery's documented responses.
# ======================================================================================
PINCODES = {
    "400601": ("Thane", "MH", "THN/TWF", "Y"),
    "400602": ("Thane", "MH", "THN/TWF", "Y"),
    "400053": ("Mumbai", "MH", "BOM/AND", "Y"),
    "400058": ("Mumbai", "MH", "BOM/AND", "Y"),
    "400076": ("Mumbai", "MH", "BOM/PWI", "Y"),
    "400079": ("Mumbai", "MH", "BOM/VKH", "Y"),
    "411001": ("Pune", "MH", "PNQ/CMP", "Y"),
    "560001": ("Bengaluru", "KA", "BLR/MGR", "Y"),
    "110017": ("New Delhi", "DL", "DEL/MLV", "Y"),
    "401404": ("Palghar", "MH", "PLG/BOI", "N"),   # serviceable for delivery, NO pickup
}
DLV = {"shipments": {}, "orders": {}, "pickups": {}, "pickup_attempts": {}, "ndr": {}, "creates": {}}


def dlv_pincode(filter_codes):
    pin = str(filter_codes).strip()
    if pin not in PINCODES:
        return {"delivery_codes": []}
    district, state, sort_code, pickup = PINCODES[pin]
    return {"delivery_codes": [{"postal_code": {
        "district": district, "pin": int(pin), "max_amount": 0.0, "pre_paid": "Y", "cash": "Y",
        "pickup": pickup, "repl": "Y", "cod": "Y", "country_code": "IN", "sort_code": sort_code,
        "is_oda": "N", "state_code": state, "max_weight": 0.0}}]}


def dlv_charges(md, ss, d_pin, o_pin, cgm, pt="Pre-paid"):
    """GET /api/kinko/v1/invoice/charges/.json  md=E (Express) or S (Surface), cgm = grams."""
    if str(d_pin) not in PINCODES or str(o_pin) not in PINCODES:
        return {"error": "Non-serviceable pincode", "status": "FAILURE"}
    kg = max(0.5, float(cgm) / 1000)
    same_city = PINCODES[str(d_pin)][0] == PINCODES[str(o_pin)][0] or {PINCODES[str(d_pin)][0], PINCODES[str(o_pin)][0]} <= {"Mumbai", "Thane"}
    zone = "A" if same_city else "B"
    per_kg = (38 if md == "E" else 24) * (1 if zone == "A" else 1.6)
    freight = round(per_kg * kg, 2)
    fuel = round(freight * 0.12, 2)
    gross = round(freight + fuel + 30, 2)
    gst = round(gross * 0.18, 2)
    return [{"charge_DL": freight, "charge_FSC": fuel, "charge_DPH": 30.0, "gross_amount": gross,
             "tax_data": {"IGST": 0.0, "SGST": round(gst / 2, 2), "CGST": round(gst / 2, 2), "swacch_bharat_tax": 0.0},
             "total_amount": round(gross + gst, 2), "zone": zone, "charged_weight": float(cgm),
             "status": "SUCCESS", "md": md, "ss": ss, "pt": pt}]


def dlv_fetch_waybill(count=1):
    wbs = [str(random.randint(10**12, 10**13 - 1)) for _ in range(int(count))]
    return wbs[0] if int(count) == 1 else ",".join(wbs)


def dlv_create(data):
    """POST /api/cmu/create.json  (format=json&data={"shipments":[...],"pickup_location":{"name":...}})."""
    ships = data.get("shipments") or []
    if not ships:
        return 400, {"success": False, "rmk": "shipments missing", "packages": []}
    s = ships[0]
    order = str(s.get("order") or "")
    if not order:
        return 400, {"success": False, "rmk": "order id missing", "packages": []}
    pin = str(s.get("pin") or "")
    if order in DLV["orders"]:
        return 200, {"success": False, "package_count": 1, "upload_wbn": "UPL" + uuid.uuid4().hex[:15].upper(),
                     "packages": [{"status": "Fail", "client": "SETTLD", "remarks": ["Duplicate order id"],
                                   "waybill": "", "refnum": order, "serviceable": True}],
                     "rmk": "Duplicate order id"}
    if pin not in PINCODES:
        return 200, {"success": False, "package_count": 1, "packages": [{"status": "Fail", "remarks": ["Non serviceable pincode"],
                     "waybill": "", "refnum": order, "serviceable": False}], "rmk": "Non serviceable pincode"}
    wb = str(s.get("waybill") or dlv_fetch_waybill())
    DLV["shipments"][wb] = {"waybill": wb, "order": order, "name": s.get("name"), "add": s.get("add"), "pin": pin,
                            "phone": s.get("phone"), "products_desc": s.get("products_desc"),
                            "weight": s.get("weight"), "quantity": s.get("quantity"),
                            "pickup_location": (data.get("pickup_location") or {}).get("name"),
                            "stage": 0, "track_calls": 0, "ndr_done": False, "reattempt": False,
                            "cancelled": False, "created_at": ts(), "scans": []}
    DLV["orders"][order] = wb
    _scan(wb, "Manifested", "UD", "Shipment manifested, awaiting pickup")
    resp = {"cash_pickups_count": 0, "package_count": 1, "upload_wbn": "UPL" + uuid.uuid4().hex[:15].upper(),
            "replacement_count": 0, "pickups_count": 0,
            "packages": [{"status": "Success", "client": "SETTLD", "sort_code": PINCODES[pin][2], "remarks": [],
                          "waybill": wb, "cod_amount": 0.0, "payment": s.get("payment_mode", "Pre-paid"),
                          "serviceable": True, "refnum": order}],
            "cash_pickups": 0.0, "cod_count": 0, "success": True, "prepaid_count": 1, "pickups": 0, "cod_amount": 0.0}
    n = DLV["creates"].get(order, 0) + 1
    DLV["creates"][order] = n
    if SIM["create_timeout_first_try"] and n == 1:
        # The shipment is created on Delhivery's side, but the response never reaches the client.
        return 504, {"error": "Gateway Timeout", "message": "upstream request timeout", "request_id": uuid.uuid4().hex[:12]}
    return 200, resp


def _scan(wb, status, stype, instr, loc=None):
    s = DLV["shipments"][wb]
    s["status"] = {"Status": status, "StatusType": stype, "StatusDateTime": ts(),
                   "StatusLocation": loc or (PINCODES.get(s["pin"], ("Mumbai",))[0] + "_DC"), "Instructions": instr}
    s["scans"].append({"ScanDetail": {"Scan": status, "ScanType": stype, "ScanDateTime": ts(),
                                      "ScannedLocation": s["status"]["StatusLocation"], "Instructions": instr}})


def dlv_pickup(data):
    """POST /fm/request/new/  {pickup_location, pickup_time "HH:MM:SS", pickup_date "YYYY-MM-DD", expected_package_count}."""
    for k in ("pickup_location", "pickup_time", "pickup_date", "expected_package_count"):
        if not data.get(k):
            return 400, {"error": {"message": f"{k} is required"}}
    try:
        d = datetime.strptime(str(data["pickup_date"]), "%Y-%m-%d").date()
        t = datetime.strptime(str(data["pickup_time"])[:8], "%H:%M:%S").time()
    except ValueError:
        return 400, {"error": {"message": "pickup_date must be YYYY-MM-DD and pickup_time HH:MM:SS"}}
    if d < now().date():
        return 400, {"error": {"message": "pickup_date cannot be in the past"}}
    if not (10 <= t.hour < 18):
        return 400, {"error": {"message": "Pickup slots available between 10:00:00 and 18:00:00 only"}}
    key = str(d)
    DLV["pickup_attempts"][key] = DLV["pickup_attempts"].get(key, 0) + 1
    if SIM["pickup_no_rider_first_slot"] and DLV["pickup_attempts"][key] == 1:
        nxt = (datetime.combine(d, t) + timedelta(hours=3))
        if nxt.hour >= 18:
            nxt = datetime.combine(d + timedelta(days=1), datetime.min.time()).replace(hour=11)
        return 200, {"pr_exist": False, "success": False,
                     "error": {"code": "NO_RIDER_AVAILABLE",
                               "message": "No pickup executive available for the requested slot",
                               "next_available_slot": {"pickup_date": str(nxt.date()), "pickup_time": nxt.strftime("%H:%M:%S")}}}
    pid = random.randint(10**7, 10**8 - 1)
    DLV["pickups"][pid] = {**data, "pickup_id": pid, "status": "Scheduled"}
    for wb, s in DLV["shipments"].items():
        if s.get("pickup_location") == data["pickup_location"] and s["stage"] == 0 and not s["cancelled"]:
            s["stage"] = 1
    return 200, {"pickup_location_name": data["pickup_location"], "client_name": "SETTLD",
                 "pickup_time": data["pickup_time"], "pickup_id": pid, "incoming_center_name": "Mumbai_Andheri_DC",
                 "expected_package_count": int(data["expected_package_count"]), "pickup_date": str(d)}


def dlv_track(waybill=None, ref_ids=None):
    """GET /api/v1/packages/json/?waybill=...  or ?ref_ids=<order id>. Advances one stage per call."""
    wb = waybill
    if not wb and ref_ids:
        wb = DLV["orders"].get(str(ref_ids))
    s = DLV["shipments"].get(str(wb)) if wb else None
    if not s:
        return 200, {"ShipmentData": [], "Error": "No such waybill or order id"}
    s["track_calls"] += 1
    if SIM["track_malformed_first_call"] and s["track_calls"] == 1:
        return 200, '{"ShipmentData":[{"Shipment":{"AWB":"' + s["waybill"] + '","Status":{"Status":"In Tr'  # truncated
    if not s["cancelled"]:
        st = s["stage"]
        if st == 1:
            _scan(s["waybill"], "In Transit", "UD", "Picked up from origin"); s["stage"] = 2
        elif st == 2:
            _scan(s["waybill"], "Dispatched", "UD", "Out for delivery"); s["stage"] = 3
        elif st == 3:
            if SIM["delivery_ndr_once"] and not s["ndr_done"]:
                _scan(s["waybill"], "Pending", "UD", "Consignee unavailable - NDR raised, awaiting instruction")
                s["ndr_done"] = True; s["stage"] = 4
            else:
                _deliver(s)
        elif st == 4 and s["reattempt"]:
            _scan(s["waybill"], "Dispatched", "UD", "Out for delivery - reattempt"); s["stage"] = 5
        elif st == 5:
            _deliver(s)
    return 200, {"ShipmentData": [{"Shipment": {
        "AWB": s["waybill"], "ReferenceNo": s["order"], "Origin": "Thane", "Destination": PINCODES.get(s["pin"], ("?",))[0],
        "Consignee": {"Name": s["name"], "PinCode": int(s["pin"])}, "Status": s["status"], "Scans": s["scans"],
        "PickUpDate": s["scans"][1]["ScanDetail"]["ScanDateTime"] if len(s["scans"]) > 1 else None,
        "DeliveryDate": s["status"]["StatusDateTime"] if s["status"]["Status"] == "Delivered" else None,
        "ExpectedDeliveryDate": (now() + timedelta(days=1)).date().isoformat(), "ChargedWeight": s.get("weight")}}]}


def _deliver(s):
    _scan(s["waybill"], "Delivered", "DL", "Delivered to consignee", )
    s["status"]["POD"] = {"ReceivedBy": s["name"], "Image": f"{BASE_URL}/delhivery/pod/{s['waybill']}.jpg"}
    s["stage"] = 9


def dlv_ndr(data):
    """POST /api/p/update  {"data":[{"waybill":..., "act":"RE-ATTEMPT"|"DEFER_DLV"|"EDIT_DETAILS", "action_data":{...}}]}"""
    items = data.get("data") or []
    if not items:
        return 400, {"error": "data missing"}
    for it in items:
        wb = str(it.get("waybill"))
        act = it.get("act")
        s = DLV["shipments"].get(wb)
        if not s:
            return 400, {"error": f"waybill {wb} not found"}
        if act not in ("RE-ATTEMPT", "DEFER_DLV", "EDIT_DETAILS"):
            return 400, {"error": f"act {act} not allowed for NDR"}
        if s["stage"] != 4:
            return 400, {"error": f"waybill {wb} is not in NDR state", "current_status": s["status"]["Status"]}
        s["reattempt"] = True
        if act == "EDIT_DETAILS":
            s.update({k: v for k, v in (it.get("action_data") or {}).items() if k in ("name", "add", "phone")})
    rid = "UPL" + uuid.uuid4().hex[:18].upper()
    DLV["ndr"][rid] = items
    return 200, {"message": "Request submitted successfully!", "request_id": rid}


def dlv_cancel(data):
    """POST /api/p/edit  {"waybill": "...", "cancellation": "true"}"""
    s = DLV["shipments"].get(str(data.get("waybill")))
    if not s:
        return 400, {"status": False, "error": "waybill not found"}
    if s["stage"] >= 2:
        return 200, {"status": False, "waybill": s["waybill"], "remark": "Shipment already picked up; cannot be cancelled"}
    s["cancelled"] = True
    _scan(s["waybill"], "Cancelled", "CN", "Shipment cancelled by client")
    return 200, {"status": True, "waybill": s["waybill"], "remark": "Shipment has been cancelled."}


delhivery = new_mcp("delhivery-mock", "Delhivery B2C API mock. Each tool calls the Delhivery endpoint named in its "
                    "description and returns Delhivery's response fields unchanged. Responses can be failures: "
                    "non-serviceable pincodes, no rider available, gateway timeouts, malformed bodies, NDR.")


@delhivery.tool(annotations=READ)
def pincode_serviceability(filter_codes: str) -> dict:
    """GET /c/api/pin-codes/json/?filter_codes=<pin>. Empty delivery_codes = not serviceable. pickup='N' = no pickup."""
    log("delhivery", f"GET /c/api/pin-codes/json/?filter_codes={filter_codes}")
    return dlv_pincode(filter_codes)


@delhivery.tool(annotations=READ)
def calculate_shipping_cost(md: str, ss: str, d_pin: str, o_pin: str, cgm: int, pt: str = "Pre-paid") -> dict:
    """GET /api/kinko/v1/invoice/charges/.json. md: E (Express) or S (Surface). ss: Delivered. cgm: chargeable grams."""
    log("delhivery", f"GET /api/kinko/v1/invoice/charges/.json?md={md}&o_pin={o_pin}&d_pin={d_pin}&cgm={cgm}")
    r = dlv_charges(md, ss, d_pin, o_pin, cgm, pt)
    return {"response": r}


@delhivery.tool(annotations=WRITE)
def fetch_waybill(count: int = 1) -> dict:
    """GET /waybill/api/fetch/json/?count=<n>. Returns pre-allocated waybill number(s)."""
    log("delhivery", f"GET /waybill/api/fetch/json/?count={count}")
    return {"waybill": dlv_fetch_waybill(count)}


@delhivery.tool(annotations=WRITE)
def create_shipment(shipments: list[dict], pickup_location: dict) -> dict:
    """POST /api/cmu/create.json with data={"shipments":[{name, add, pin, phone, order, payment_mode, products_desc,
    weight, quantity, waybill?}], "pickup_location":{"name":...}}. Can return http_status 504 (timeout): the shipment
    may still have been created, so check GET /api/v1/packages/json/?ref_ids=<order> before retrying."""
    log("delhivery", f"POST /api/cmu/create.json order={shipments[0].get('order') if shipments else None}")
    code, body = dlv_create({"shipments": shipments, "pickup_location": pickup_location})
    return {"http_status": code, "body": body}


@delhivery.tool(annotations=WRITE)
def create_pickup_request(pickup_location: str, pickup_time: str, pickup_date: str, expected_package_count: int) -> dict:
    """POST /fm/request/new/. pickup_time HH:MM:SS (10:00:00-18:00:00), pickup_date YYYY-MM-DD.
    May fail with error.code NO_RIDER_AVAILABLE and a next_available_slot."""
    log("delhivery", f"POST /fm/request/new/ {pickup_date} {pickup_time}")
    code, body = dlv_pickup({"pickup_location": pickup_location, "pickup_time": pickup_time,
                             "pickup_date": pickup_date, "expected_package_count": expected_package_count})
    return {"http_status": code, "body": body}


@delhivery.tool(annotations=READ)
def track_shipment(waybill: str = "", ref_ids: str = "") -> dict:
    """GET /api/v1/packages/json/?waybill=<awb> or ?ref_ids=<order id>. The body may be malformed (not valid JSON);
    if so, report it and retry later. Status.StatusType DL = delivered. Status 'Pending' with an NDR instruction
    = delivery failed and needs an NDR action."""
    log("delhivery", f"GET /api/v1/packages/json/?waybill={waybill}&ref_ids={ref_ids}")
    code, body = dlv_track(waybill or None, ref_ids or None)
    if isinstance(body, str):
        return {"http_status": code, "content_type": "application/json", "raw_body": body,
                "parse_error": "Expecting ',' delimiter: unterminated string (malformed JSON)"}
    return {"http_status": code, "body": body}


@delhivery.tool(annotations=WRITE)
def ndr_update(waybill: str, act: str, action_data: dict | None = None) -> dict:
    """POST /api/p/update {"data":[{"waybill","act","action_data"}]}. act: RE-ATTEMPT, DEFER_DLV (action_data
    {"deferred_date":"YYYY-MM-DD"}) or EDIT_DETAILS (action_data {name, add, phone}). Only valid in NDR state."""
    log("delhivery", f"POST /api/p/update waybill={waybill} act={act}")
    item = {"waybill": waybill, "act": act}
    if action_data:
        item["action_data"] = action_data
    code, body = dlv_ndr({"data": [item]})
    return {"http_status": code, "body": body}


@delhivery.tool(annotations=WRITE)
def cancel_shipment(waybill: str) -> dict:
    """POST /api/p/edit {"waybill": ..., "cancellation": "true"}. Fails once the shipment is picked up."""
    log("delhivery", f"POST /api/p/edit waybill={waybill} cancellation=true")
    code, body = dlv_cancel({"waybill": waybill, "cancellation": "true"})
    return {"http_status": code, "body": body}


# ======================================================================================
# PINE LABS mock (Plural API). Amounts in paisa, as Plural does.
# ======================================================================================
PINE = {"links": {}, "orders": {}, "refunds": {}, "status_calls": {}}
ACCOUNTS = {"salary": ("HDFC Salary ****8890", 4200000), "savings": ("SBI Savings ****4321", 125000)}  # paisa


def pine_token():
    return {"access_token": "uat_" + uuid.uuid4().hex, "expires_at": (now() + timedelta(hours=1)).isoformat(timespec="seconds"),
            "token_type": "Bearer"}


def pine_create_link(body):
    amt = (body.get("amount") or {})
    value = int(amt.get("value") or 0)
    ref = body.get("merchant_payment_link_reference")
    if value < 100:
        return 400, {"code": "INVALID_REQUEST", "message": "amount.value must be at least 100 (paisa)"}
    if not ref:
        return 400, {"code": "INVALID_REQUEST", "message": "merchant_payment_link_reference is required"}
    for l in PINE["links"].values():
        if l["merchant_payment_link_reference"] == ref:
            return 409, {"code": "DUPLICATE_REQUEST", "message": "Payment link already exists for this reference",
                         "payment_link_id": l["payment_link_id"]}
    lid = "pl-v1-" + now().strftime("%y%m%d%H%M%S") + "-aa-" + uuid.uuid4().hex[:6]
    oid = "v1-" + now().strftime("%y%m%d%H%M%S") + "-aa-" + uuid.uuid4().hex[:6]
    link = {"payment_link": f"{BASE_URL}/pinelabs/checkout/{lid}", "payment_link_id": lid, "status": "CREATED",
            "amount": {"value": value, "currency": amt.get("currency", "INR")},
            "amount_due": {"value": value, "currency": amt.get("currency", "INR")}, "order_id": oid,
            "merchant_payment_link_reference": ref, "description": body.get("description", ""),
            "expire_by": body.get("expire_by") or (now() + timedelta(hours=24)).isoformat(timespec="seconds"),
            "allowed_payment_methods": body.get("allowed_payment_methods") or ["UPI", "CARD", "NETBANKING"],
            "customer": body.get("customer") or {}, "created_at": ts()}
    PINE["links"][lid] = link
    PINE["orders"][oid] = {"order_id": oid, "merchant_order_reference": ref, "type": "CHARGE", "status": "CREATED",
                           "order_amount": link["amount"], "payments": [], "created_at": ts(), "updated_at": ts()}
    return 200, link


def pine_get_link(lid):
    l = PINE["links"].get(lid)
    if not l:
        return 404, {"code": "NOT_FOUND", "message": "payment link not found"}
    n = PINE["status_calls"].get(lid, 0) + 1
    PINE["status_calls"][lid] = n
    if SIM["payment_status_timeout_once"] and n == 1:
        return 504, {"code": "GATEWAY_TIMEOUT", "message": "Request timed out. Retry with the same identifiers."}
    return 200, l


def pine_get_order(oid):
    o = PINE["orders"].get(oid)
    return (200, {"data": o}) if o else (404, {"code": "NOT_FOUND", "message": "order not found"})


def pine_refund(oid, body):
    o = PINE["orders"].get(oid)
    if not o:
        return 404, {"code": "NOT_FOUND", "message": "order not found"}
    if o["status"] != "PROCESSED":
        return 400, {"code": "INVALID_REQUEST", "message": f"order is {o['status']}; only PROCESSED orders can be refunded"}
    ref = body.get("merchant_order_reference") or ("rf-" + uuid.uuid4().hex[:8])
    if ref in PINE["refunds"]:
        return 200, {"data": PINE["refunds"][ref], "note": "existing refund returned (idempotent)"}
    val = int((body.get("order_amount") or {}).get("value") or o["order_amount"]["value"])
    rid = "v1-rf-" + uuid.uuid4().hex[:10]
    r = {"order_id": rid, "parent_order_id": oid, "merchant_order_reference": ref, "type": "REFUND",
         "status": "PROCESSED", "order_amount": {"value": val, "currency": "INR"}, "created_at": ts()}
    PINE["refunds"][ref] = r
    o["status"] = "REFUNDED" if val >= o["order_amount"]["value"] else "PARTIALLY_REFUNDED"
    return 200, {"data": r}


def pine_pay(lid, account):
    l = PINE["links"].get(lid)
    if not l:
        return "Payment link not found."
    o = PINE["orders"][l["order_id"]]
    if l["status"] == "PROCESSED":
        return "Already paid."
    name, bal = ACCOUNTS.get(account, ACCOUNTS["salary"])
    pay = {"id": "pay-" + uuid.uuid4().hex[:10], "payment_method": "UPI", "instrument": name,
           "payment_amount": l["amount"], "created_at": ts()}
    if bal < l["amount"]["value"]:
        pay.update({"status": "FAILED", "error_detail": {"code": "INSUFFICIENT_FUNDS",
                    "message": "Transaction declined by issuer: insufficient balance"}})
        o["payments"].append(pay); o["status"] = "FAILED"; o["updated_at"] = ts()
        l["status"] = "CREATED"  # link stays open for another attempt
        l["last_attempt"] = {"status": "FAILED", "reason": "INSUFFICIENT_FUNDS", "at": ts()}
        return f"Payment failed: insufficient balance in {name}."
    pay["status"] = "PROCESSED"
    o["payments"].append(pay); o["status"] = "PROCESSED"; o["updated_at"] = ts()
    l["status"] = "PROCESSED"; l["amount_due"] = {"value": 0, "currency": "INR"}
    l["last_attempt"] = {"status": "PROCESSED", "at": ts()}
    return f"Paid \u20b9{l['amount']['value'] / 100:,.2f} from {name}."


pinelabs = new_mcp("pinelabs-mock", "Pine Labs Online (Plural) API mock. Amounts are in paisa. Each tool calls the "
                   "Plural endpoint named in its description. Calls can time out (504); retry with the same identifiers.")


@pinelabs.tool(annotations=WRITE)
def generate_token(client_id: str = "settld_uat", client_secret: str = "***", grant_type: str = "client_credentials") -> dict:
    """POST /api/auth/v1/token. Returns a Bearer access token (UAT)."""
    log("pinelabs", "POST /api/auth/v1/token")
    return pine_token()


@pinelabs.tool(annotations=WRITE)
def create_payment_link(amount_value: int, merchant_payment_link_reference: str, description: str = "",
                        customer_name: str = "", customer_mobile: str = "", expire_by: str = "") -> dict:
    """POST /api/pay/v1/paymentlink {"amount":{"value":<paisa>,"currency":"INR"}, "merchant_payment_link_reference",
    "description", "customer", "expire_by"}. Returns payment_link (URL to send to the customer), payment_link_id,
    order_id, status CREATED. Reusing a reference returns 409 DUPLICATE_REQUEST with the existing id."""
    log("pinelabs", f"POST /api/pay/v1/paymentlink ref={merchant_payment_link_reference} value={amount_value}")
    code, body = pine_create_link({"amount": {"value": amount_value, "currency": "INR"},
                                   "merchant_payment_link_reference": merchant_payment_link_reference,
                                   "description": description, "expire_by": expire_by or None,
                                   "customer": {"first_name": customer_name, "mobile_number": customer_mobile}})
    return {"http_status": code, "body": body}


@pinelabs.tool(annotations=READ)
def get_payment_link(payment_link_id: str) -> dict:
    """GET /api/pay/v1/paymentlink/{payment_link_id}. status CREATED (unpaid; see last_attempt for a failed try) or
    PROCESSED (paid). Can return 504 GATEWAY_TIMEOUT: retry later with the same id."""
    log("pinelabs", f"GET /api/pay/v1/paymentlink/{payment_link_id}")
    code, body = pine_get_link(payment_link_id)
    return {"http_status": code, "body": body}


@pinelabs.tool(annotations=READ)
def get_order(order_id: str) -> dict:
    """GET /api/pay/v1/orders/{order_id}. data.status: CREATED, PROCESSED, FAILED, REFUNDED; data.payments[] has
    error_detail.code (e.g. INSUFFICIENT_FUNDS) for failed attempts."""
    log("pinelabs", f"GET /api/pay/v1/orders/{order_id}")
    code, body = pine_get_order(order_id)
    return {"http_status": code, "body": body}


@pinelabs.tool(annotations=WRITE)
def create_refund(order_id: str, merchant_order_reference: str, amount_value: int = 0) -> dict:
    """POST /api/pay/v1/refunds/{order_id} {"merchant_order_reference", "order_amount":{"value","currency"}}.
    Same reference twice returns the existing refund (no double refund)."""
    log("pinelabs", f"POST /api/pay/v1/refunds/{order_id}")
    body = {"merchant_order_reference": merchant_order_reference}
    if amount_value:
        body["order_amount"] = {"value": amount_value, "currency": "INR"}
    code, b = pine_refund(order_id, body)
    return {"http_status": code, "body": b}


# ======================================================================================
# TELEGRAM (real) — renter inbox and replies
# ======================================================================================
TG = {"offset": 0, "chat_id": os.environ.get("TELEGRAM_CHAT_ID", "").strip(), "audio": {}}


def _tg_api(method, params=None, files=None, timeout=15):
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not tok:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    url = f"https://api.telegram.org/bot{tok}/{method}"
    if files:
        boundary = "----settld" + uuid.uuid4().hex
        parts = []
        for k, v in (params or {}).items():
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
        for k, (fname, data, ctype) in files.items():
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fname}\"\r\n"
                         f"Content-Type: {ctype}\r\n\r\n".encode() + data + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(url, data=b"".join(parts))
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    else:
        req = urllib.request.Request(url, data=urllib.parse.urlencode(params or {}).encode())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode())
    if not out.get("ok"):
        raise RuntimeError(out.get("description", "telegram error"))
    return out["result"]


def _tg_download(file_id):
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    f = _tg_api("getFile", {"file_id": file_id})
    with urllib.request.urlopen(f"https://api.telegram.org/file/bot{tok}/{f['file_path']}", timeout=20) as r:
        return r.read(), f["file_path"]


telegram = new_mcp("telegram-settld", "Real Telegram Bot API for the renter's chat with Settld: read new messages, "
                   "voice notes and button taps; send text, buttons and voice notes.")


@telegram.tool(annotations=WRITE)
def get_renter_updates() -> dict:
    """Fetch NEW renter messages since the last call (Telegram getUpdates). Each item has type text | voice | button,
    the text or button data, a voice file_id (transcribe with Gnani speech_to_text), and sent_at (IST).
    Also returns now_ist so you can tell how long the renter has been silent."""
    try:
        ups = _tg_api("getUpdates", {"offset": TG["offset"], "timeout": 0,
                                     "allowed_updates": json.dumps(["message", "callback_query"])})
    except Exception as e:
        return {"error": str(e)[:200], "now_ist": ts(), "messages": []}
    msgs = []
    for u in ups:
        TG["offset"] = max(TG["offset"], u["update_id"] + 1)
        if "callback_query" in u:
            cq = u["callback_query"]
            TG["chat_id"] = str(cq["message"]["chat"]["id"])
            with contextlib.suppress(Exception):
                _tg_api("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "Got it"})
            msgs.append({"type": "button", "data": cq.get("data"), "from": cq["from"].get("first_name"),
                         "sent_at": ts()})
        elif "message" in u:
            m = u["message"]
            TG["chat_id"] = str(m["chat"]["id"])
            when = datetime.fromtimestamp(m["date"], IST).isoformat(timespec="seconds")
            if "voice" in m or "audio" in m:
                v = m.get("voice") or m.get("audio")
                msgs.append({"type": "voice", "file_id": v["file_id"], "duration_s": v.get("duration"),
                             "from": m["from"].get("first_name"), "sent_at": when})
            elif "text" in m:
                msgs.append({"type": "text", "text": m["text"], "from": m["from"].get("first_name"), "sent_at": when})
    log("telegram", f"getUpdates -> {len(msgs)} new")
    return {"now_ist": ts(), "chat_connected": bool(TG["chat_id"]), "messages": msgs}


@telegram.tool(annotations=WRITE)
def send_renter_message(text: str, buttons: list[str] | None = None) -> dict:
    """Send a text message to the renter (Telegram sendMessage). Optional buttons (max 3), e.g.
    ["Confirm", "Cheaper option", "Cancel"]; a tap comes back in get_renter_updates as type=button."""
    if not TG["chat_id"]:
        return {"sent": False, "error": "Renter has not messaged the bot yet (send /start)."}
    params = {"chat_id": TG["chat_id"], "text": text[:4000]}
    if buttons:
        params["reply_markup"] = json.dumps({"inline_keyboard": [[{"text": b, "callback_data": b[:60]} for b in buttons[:3]]]})
    try:
        r = _tg_api("sendMessage", params)
        log("telegram", f"sendMessage -> {r['message_id']}")
        return {"sent": True, "message_id": r["message_id"], "at": ts()}
    except Exception as e:
        return {"sent": False, "error": str(e)[:200]}


@telegram.tool(annotations=WRITE)
def send_renter_voice(audio_id: str, caption: str = "") -> dict:
    """Send a voice note produced by Gnani text_to_speech (pass its audio_id) to the renter (Telegram sendVoice)."""
    a = TG["audio"].get(audio_id)
    if not a:
        return {"sent": False, "error": "unknown audio_id; call Gnani text_to_speech first"}
    if not TG["chat_id"]:
        return {"sent": False, "error": "Renter has not messaged the bot yet (send /start)."}
    try:
        r = _tg_api("sendVoice", {"chat_id": TG["chat_id"], "caption": caption[:1000]},
                    files={"voice": ("settld.ogg", a, "audio/ogg")}, timeout=30)
        log("telegram", f"sendVoice -> {r['message_id']}")
        return {"sent": True, "message_id": r["message_id"], "at": ts()}
    except Exception as e:
        return {"sent": False, "error": str(e)[:200]}


# ======================================================================================
# GNANI (real) — speech-to-text and text-to-speech
# ======================================================================================
gnani = new_mcp("gnani-settld", "Real Gnani (Vachana) speech APIs. speech_to_text transcribes the renter's Telegram "
                "voice note (Hinglish supported); text_to_speech turns Settld's reply into a voice note.")


@gnani.tool(annotations=READ)
def speech_to_text(telegram_file_id: str, language_code: str = "") -> dict:
    """Transcribe a renter voice note with Gnani STT REST (max 60 s). Pass the voice file_id from get_renter_updates.
    language_code defaults to hi-IN (handles Hindi-English mix); use en-IN for English."""
    key = os.environ.get("GNANI_API_KEY", "").strip()
    if not key:
        return {"success": False, "error": "GNANI_API_KEY not set"}
    lang = language_code or os.environ.get("GNANI_STT_LANG", "hi-IN")
    try:
        audio, path = _tg_download(telegram_file_id)
    except Exception as e:
        return {"success": False, "error": f"could not download voice note: {str(e)[:150]}"}
    try:
        from gnani.stt import GnaniSTTClient
        t0 = time.time()
        res = GnaniSTTClient(api_key=key).transcribe_bytes(audio, filename=os.path.basename(path) or "voice.ogg",
                                                           language_code=lang)
        log("gnani", f"STT {lang} {len(audio)}B -> {str(res.get('transcript'))[:80]}")
        return {"success": bool(res.get("success", True)), "transcript": res.get("transcript", ""),
                "language_code": lang, "request_id": res.get("request_id"),
                "latency_ms": int((time.time() - t0) * 1000),
                "audio_sha256": hashlib.sha256(audio).hexdigest()[:16]}
    except Exception as e:
        log("gnani", f"STT error {e}")
        return {"success": False, "error": f"Gnani STT failed: {str(e)[:200]}"}


@gnani.tool(annotations=WRITE)
def text_to_speech(text: str, voice: str = "", language: str = "") -> dict:
    """Synthesize Settld's reply with Gnani TTS (Timbre) as an OGG/Opus voice note. Returns audio_id for
    Telegram send_renter_voice. Keep text short (1-3 sentences); write amounts as words or plain numbers."""
    key = os.environ.get("GNANI_API_KEY", "").strip()
    if not key:
        return {"success": False, "error": "GNANI_API_KEY not set"}
    model = os.environ.get("GNANI_TTS_MODEL", "timbre-v2.5")
    voice = voice or os.environ.get("GNANI_TTS_VOICE", "Kaveri")
    lang = language or os.environ.get("GNANI_TTS_LANG", "hi-IN")
    try:
        from gnani.tts import AudioConfig, GnaniTTSClient
        kwargs = {"voice": voice, "model": model,
                  "audio_config": AudioConfig(container="ogg", encoding="oggopus", sample_rate=48000)}
        if model == "timbre-v2.5":
            kwargs["language"] = lang
        t0 = time.time()
        audio = GnaniTTSClient(api_key=key).synthesize(text[:600], **kwargs)
        aid = "aud-" + uuid.uuid4().hex[:10]
        TG["audio"][aid] = audio
        for k in list(TG["audio"])[:-20]:
            TG["audio"].pop(k, None)
        log("gnani", f"TTS {model}/{voice} {len(text)} chars -> {len(audio)}B")
        return {"success": True, "audio_id": aid, "bytes": len(audio), "model": model, "voice": voice,
                "latency_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        log("gnani", f"TTS error {e}")
        return {"success": False, "error": f"Gnani TTS failed: {str(e)[:200]}"}


# ======================================================================================
# SETTLD — 3 capabilities no rail offers today + agent memory
# ======================================================================================
MEM = {"missions": {}, "consents": {}, "releases": {}}
HEDGES = ["dekh lenge", "dekhte hain", "baad mein", "shayad", "maybe", "not sure", "sochke", "soch ke", "let me think",
          "later", "kal batata", "kal bataungi", "abhi nahi"]
YES = ["haan", "han", "ha ", "yes", "ok", "okay", "theek", "thik", "kar do", "karo", "confirm", "chalega", "done", "go ahead"]
NO = ["nahi", "nahin", "no", "mat", "cancel", "mehenga", "mehnga", "expensive", "zyada", "rehne do", "ruk"]

settld = new_mcp("settld-capabilities", "Settld capabilities that no rail offers today: Pine Labs mandate evaluation, "
                 "Pine Labs purpose-bound settlement release, Gnani voice consent extraction; plus mission memory.")


@settld.tool(annotations=WRITE)
def pine_mandate_evaluate(mission_id: str, purpose: str, amount_value: int, payee: str = "") -> dict:
    """[Capability 1 — Pine Labs, proposed POST /api/pay/v1/mandates/evaluate]
    Check a payment against the renter's mandate before creating it. Returns decision ALLOW (within budget and
    purpose), HUMAN_REQUIRED (needs the renter's explicit yes) or DENY, with the rule that fired.
    amount_value in paisa. Mandate comes from mission memory: budget_paisa, allowed_purposes."""
    m = MEM["missions"].get(mission_id, {})
    mandate = m.get("mandate") or {}
    budget = int(mandate.get("budget_paisa") or 0)
    purposes = mandate.get("allowed_purposes") or ["moving_charges"]
    if mandate.get("revoked"):
        d, rule = "DENY", "mandate_revoked"
    elif purpose not in purposes:
        d, rule = "DENY", f"purpose '{purpose}' not in mandate {purposes}"
    elif not budget:
        d, rule = "HUMAN_REQUIRED", "no budget stated by renter"
    elif amount_value > budget:
        d, rule = "HUMAN_REQUIRED", f"amount {amount_value / 100:.0f} exceeds renter budget {budget / 100:.0f}"
    elif amount_value > 2500000:
        d, rule = "HUMAN_REQUIRED", "single payment above 25,000 always needs approval"
    else:
        d, rule = "ALLOW", f"within budget {budget / 100:.0f} for {purpose}"
    log("settld", f"mandate {mission_id} {purpose} {amount_value} -> {d}")
    return {"decision": d, "rule": rule, "mandate": mandate, "evaluated_at": ts()}


@settld.tool(annotations=WRITE)
def pine_conditional_release(mission_id: str, order_id: str, waybill: str, renter_confirmed: bool,
                             renter_confirmation_text: str = "") -> dict:
    """[Capability 2 — Pine Labs, proposed POST /api/pay/v1/settlements/conditional-release]
    Release the renter's captured payment to the logistics payee ONLY when the purpose is fulfilled: the Pine
    order is PROCESSED, the Delhivery waybill shows Delivered (StatusType DL), and the renter confirmed receipt.
    Otherwise the money stays HELD (or should be refunded). Idempotent per order_id."""
    if order_id in MEM["releases"]:
        return {**MEM["releases"][order_id], "note": "already decided (idempotent)"}
    o = PINE["orders"].get(order_id)
    s = DLV["shipments"].get(str(waybill))
    checks = {"payment_processed": bool(o and o["status"] == "PROCESSED"),
              "delivered": bool(s and s.get("status", {}).get("StatusType") == "DL"),
              "renter_confirmed": bool(renter_confirmed)}
    ok = all(checks.values())
    out = {"order_id": order_id, "waybill": waybill, "decision": "RELEASED" if ok else "HELD", "checks": checks,
           "renter_confirmation_text": renter_confirmation_text, "decided_at": ts()}
    if ok:
        out["settlement_ref"] = "stl-" + uuid.uuid4().hex[:10]
        MEM["releases"][order_id] = out
    log("settld", f"release {order_id} -> {out['decision']} {checks}")
    return out


@settld.tool(annotations=WRITE)
def gnani_consent_extract(mission_id: str, transcript: str, question_asked: str, amount_value: int = 0) -> dict:
    """[Capability 3 — Gnani, proposed POST /api/v1/conversation/consent]
    Turn the renter's reply (voice transcript or text) to a specific question into a consent record:
    consent YES / NO / UNCLEAR, hedges found (e.g. "dekh lenge" = UNCLEAR, never YES), and a record id that ties
    the consent to the transcript. Use it before acting on any money decision."""
    import re as _re
    t = " " + " ".join(_re.findall(r"[a-z\u0900-\u097f]+", transcript.lower())) + " "
    hedges = [h for h in HEDGES if f" {h} " in t]
    yes = [w for w in YES if f" {w.strip()} " in t]
    no = [w for w in NO if f" {w} " in t]
    if hedges or (yes and no):
        c = "UNCLEAR"
    elif no:
        c = "NO"
    elif yes:
        c = "YES"
    else:
        c = "UNCLEAR"
    rid = "cns-" + uuid.uuid4().hex[:10]
    rec = {"consent_id": rid, "mission_id": mission_id, "consent": c, "question_asked": question_asked,
           "transcript": transcript, "hedges": hedges, "yes_markers": yes, "no_markers": no,
           "amount_value": amount_value, "transcript_sha256": hashlib.sha256(transcript.encode()).hexdigest()[:16],
           "recorded_at": ts()}
    MEM["consents"][rid] = rec
    log("settld", f"consent {mission_id} -> {c}")
    return rec


@settld.tool(annotations=READ)
def mission_get(mission_id: str = "") -> dict:
    """Read Settld's memory for a mission (state, facts, ids, timers). With no id, returns the active mission.
    Settld runs on a schedule, so ALWAYS start a run by reading memory."""
    if not mission_id:
        act = [m for m in MEM["missions"].values() if m.get("state") not in ("CLOSED", "CANCELLED")]
        if not act:
            return {"active": False, "now_ist": ts(), "message": "No active mission. Wait for a renter request."}
        m = sorted(act, key=lambda x: x["updated_at"])[-1]
        return {"active": True, "now_ist": ts(), **m}
    m = MEM["missions"].get(mission_id)
    return {"active": bool(m), "now_ist": ts(), **(m or {})}


@settld.tool(annotations=WRITE)
def mission_save(mission_id: str, state: str, updates: dict, event: str) -> dict:
    """Create or update mission memory. state: CAPTURE, VERIFY, PLAN, EXECUTE, MONITOR, VERIFY_OUTCOME,
    HUMAN_REQUIRED, CLOSED, CANCELLED. updates: dict merged into facts (e.g. from_pin, to_pin, move_date, items,
    weight_g, mandate, quote_paisa, payment_link_id, order_id, waybill, pickup_id, waiting_for, asked_at,
    reminders_sent). event: one line for the decision log, e.g. "Pickup slot 11:00 refused (no rider); booked 14:00"."""
    m = MEM["missions"].get(mission_id) or {"mission_id": mission_id, "created_at": ts(), "facts": {}, "log": []}
    m["facts"].update(updates or {})
    if "mandate" in (updates or {}):
        m["mandate"] = updates["mandate"]
    m["state"] = state
    m["updated_at"] = ts()
    m["log"].append({"at": ts(), "state": state, "event": event})
    MEM["missions"][mission_id] = m
    log("settld", f"{mission_id} {state}: {event}")
    return {"saved": True, "mission_id": mission_id, "state": state, "at": m["updated_at"]}


@settld.tool(annotations=WRITE)
def sim_config(reset_all: bool = False, set_flags: dict | None = None) -> dict:
    """Test control: reset all mock data and memory (reset_all=true) and/or switch failure modes on/off.
    Flags: pickup_no_rider_first_slot, create_timeout_first_try, track_malformed_first_call, delivery_ndr_once,
    payment_status_timeout_once."""
    if reset_all:
        for d in (DLV, PINE):
            for k in d:
                d[k] = {}
        MEM.update({"missions": {}, "consents": {}, "releases": {}})
        SIM.update(SIM_DEFAULTS)
    for k, v in (set_flags or {}).items():
        if k in SIM:
            SIM[k] = bool(v)
    return {"sim": SIM, "reset": reset_all, "at": ts()}


# ======================================================================================
# REST routes (same paths as the real APIs) + renter checkout page
# ======================================================================================
async def _json(request):
    ctype = request.headers.get("content-type", "")
    raw = await request.body()
    if "application/x-www-form-urlencoded" in ctype:
        form = urllib.parse.parse_qs(raw.decode())
        if "data" in form:
            return json.loads(form["data"][0])
        return {k: v[0] for k, v in form.items()}
    return json.loads(raw.decode() or "{}")


def _resp(code, body):
    return PlainTextResponse(body, status_code=code, media_type="application/json") if isinstance(body, str) \
        else JSONResponse(body, status_code=code)


async def r_pin(request):
    return JSONResponse(dlv_pincode(request.query_params.get("filter_codes", "")))


async def r_charges(request):
    q = request.query_params
    return JSONResponse(dlv_charges(q.get("md", "S"), q.get("ss", "Delivered"), q.get("d_pin"), q.get("o_pin"),
                                    q.get("cgm", 500), q.get("pt", "Pre-paid")))


async def r_waybill(request):
    return JSONResponse(dlv_fetch_waybill(request.query_params.get("count", 1)))


async def r_create(request):
    return _resp(*dlv_create(await _json(request)))


async def r_pickup(request):
    return _resp(*dlv_pickup(await _json(request)))


async def r_track(request):
    q = request.query_params
    return _resp(*dlv_track(q.get("waybill"), q.get("ref_ids")))


async def r_ndr(request):
    return _resp(*dlv_ndr(await _json(request)))


async def r_edit(request):
    return _resp(*dlv_cancel(await _json(request)))


async def r_token(request):
    return JSONResponse(pine_token())


async def r_link_create(request):
    return _resp(*pine_create_link(await _json(request)))


async def r_link_get(request):
    return _resp(*pine_get_link(request.path_params["lid"]))


async def r_order_get(request):
    return _resp(*pine_get_order(request.path_params["oid"]))


async def r_refund(request):
    return _resp(*pine_refund(request.path_params["oid"], await _json(request)))


async def r_checkout(request):
    lid = request.path_params["lid"]
    l = PINE["links"].get(lid)
    if not l:
        return HTMLResponse("<h3>Payment link not found</h3>", status_code=404)
    amt = l["amount"]["value"] / 100
    done = l["status"] == "PROCESSED"
    last = l.get("last_attempt", {})
    msg = request.query_params.get("msg", "")
    btns = "" if done else "".join(
        f'<form method="post" action="/pinelabs/checkout/{lid}/pay"><input type="hidden" name="account" value="{k}">'
        f'<button>Pay with UPI &middot; {n}</button></form>' for k, (n, _) in ACCOUNTS.items())
    html = f"""<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pine Labs Checkout (UAT)</title><style>
body{{font-family:system-ui,sans-serif;max-width:420px;margin:24px auto;padding:0 16px;color:#1d2433}}
.card{{border:1px solid #dfe3eb;border-radius:14px;padding:20px}} .tag{{font-size:12px;color:#6b7385}}
.amt{{font-size:34px;font-weight:700;margin:8px 0}} button{{width:100%;padding:14px;margin:8px 0;border:0;
border-radius:10px;background:#0b5cff;color:#fff;font-size:15px}} .ok{{color:#0a7d3c}} .bad{{color:#c0262d}}</style></head>
<body><div class="card"><div class="tag">Pine Labs Online &middot; UAT sandbox checkout</div>
<div>{l['description'] or 'Payment'}</div><div class="amt">&#8377;{amt:,.2f}</div>
<div class="tag">Ref {l['merchant_payment_link_reference']} &middot; Link {lid}</div>
{f'<p class="ok"><b>Paid.</b> You can close this page.</p>' if done else ''}
{f'<p class="bad">Last attempt failed: {last.get("reason")}</p>' if last.get("status") == "FAILED" else ''}
{f'<p>{msg}</p>' if msg else ''}{btns}</div></body></html>"""
    return HTMLResponse(html)


async def r_checkout_pay(request):
    lid = request.path_params["lid"]
    form = urllib.parse.parse_qs((await request.body()).decode())
    msg = pine_pay(lid, form.get("account", ["salary"])[0])
    log("pinelabs", f"checkout {lid}: {msg}")
    return RedirectResponse(f"/pinelabs/checkout/{lid}?msg={urllib.parse.quote(msg)}", status_code=303)


async def r_health(request):
    return JSONResponse({"service": "settld-v2", "at": ts(), "connectors": ["/gnani/mcp", "/telegram/mcp",
                         "/delhivery/mcp", "/pinelabs/mcp", "/settld/mcp"], "sim": SIM,
                         "gnani_key": bool(os.environ.get("GNANI_API_KEY")),
                         "telegram_token": bool(os.environ.get("TELEGRAM_BOT_TOKEN"))})


SERVERS = [gnani, telegram, delhivery, pinelabs, settld]


@contextlib.asynccontextmanager
async def lifespan(app):
    async with contextlib.AsyncExitStack() as stack:
        for s in SERVERS:
            await stack.enter_async_context(s.session_manager.run())
        yield


routes = [
    Route("/", r_health), Route("/health", r_health),
    Route("/delhivery/c/api/pin-codes/json/", r_pin),
    Route("/delhivery/api/kinko/v1/invoice/charges/.json", r_charges),
    Route("/delhivery/waybill/api/fetch/json/", r_waybill),
    Route("/delhivery/api/cmu/create.json", r_create, methods=["POST"]),
    Route("/delhivery/fm/request/new/", r_pickup, methods=["POST"]),
    Route("/delhivery/api/v1/packages/json/", r_track),
    Route("/delhivery/api/p/update", r_ndr, methods=["POST"]),
    Route("/delhivery/api/p/edit", r_edit, methods=["POST"]),
    Route("/pinelabs/api/auth/v1/token", r_token, methods=["POST"]),
    Route("/pinelabs/api/pay/v1/paymentlink", r_link_create, methods=["POST"]),
    Route("/pinelabs/api/pay/v1/paymentlink/{lid}", r_link_get),
    Route("/pinelabs/api/pay/v1/orders/{oid}", r_order_get),
    Route("/pinelabs/api/pay/v1/refunds/{oid}", r_refund, methods=["POST"]),
    Route("/pinelabs/checkout/{lid}", r_checkout),
    Route("/pinelabs/checkout/{lid}/pay", r_checkout_pay, methods=["POST"]),
]
# MCP apps are mounted last so the REST routes above win on overlapping prefixes.
for prefix, srv in (("/gnani", gnani), ("/telegram", telegram), ("/delhivery", delhivery),
                    ("/pinelabs", pinelabs), ("/settld", settld)):
    routes.append(Mount(prefix, app=srv.streamable_http_app()))

app = Starlette(routes=routes, lifespan=lifespan)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
