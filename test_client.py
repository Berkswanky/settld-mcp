import asyncio, json
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def call(s, name, **kw):
    r = await s.call_tool(name, kw)
    data = r.structuredContent or json.loads(r.content[0].text)
    return data.get("result", data) if isinstance(data, dict) else data

async def main():
    async with streamablehttp_client("http://localhost:8765/mcp") as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            await call(s, "reset_demo")
            tools = (await s.list_tools()).tools
            print("TOOLS:", len(tools), [t.name for t in tools])
            m = await call(s, "create_mission", mission_type="HOUSE_HUNT", goal="2BHK under 50k, bachelors allowed",
                           hard_constraints={"bachelors_allowed": True, "rent_max": 50000}, closure_condition="renter approves signing",
                           principals=["Rahul", "Aman"])
            mid = m["mission_id"]; await call(s, "set_mandate", mission_id=mid)
            print("\n-- P2 contradiction --")
            for role in ["broker", "owner", "society"]:
                c = await call(s, "represent_counterparty", mission_id=mid, property_id="P2", counterparty_role=role, question_topic="bachelors_allowed")
                cl = await call(s, "add_claim", mission_id=mid, subject_id="P2", fact="bachelors_allowed", value=c["stated_value"],
                                source_role=role, statement=c["statement"], evidence_ref=c["call_id"])
                print(role, "->", cl["claim"]["status"], "| fact:", cl["fact_status"]["status"], "|", cl["fact_status"]["reason"])
            print("\n-- P1 happy --")
            for role in ["broker", "owner", "society"]:
                c = await call(s, "represent_counterparty", mission_id=mid, property_id="P1", counterparty_role=role, question_topic="bachelors_allowed")
                cl = await call(s, "add_claim", mission_id=mid, subject_id="P1", fact="bachelors_allowed", value=c["stated_value"],
                                source_role=role, statement=c["statement"], evidence_ref=c["call_id"])
                print(role, "->", cl["fact_status"]["status"])
            print("\n-- P4 no answer + chase --")
            c = await call(s, "represent_counterparty", mission_id=mid, property_id="P4", counterparty_role="owner", question_topic="bachelors_allowed")
            print("owner:", c["disposition"])
            cm = await call(s, "add_commitment", mission_id=mid, who="Mr. Iyer", what="confirm bachelor policy", firm=False)
            for _ in range(10):
                ch = await call(s, "chase_until_resolution", commitment_id=cm["commitment_id"])
            print("after 10 chases:", ch["status"], ch.get("next_action"))
            print("\n-- mandate checks --")
            for a, amt in [("accept_rent", 53000), ("pay_token", 8000), ("pay_token", 12000), ("pay_repair", 2400),
                           ("pay_repair", 5800), ("pay_rent", 48000), ("sign_agreement", 0)]:
                d = await call(s, "enforce_mandate", mission_id=mid, action_type=a, amount=amt)
                print(a, amt, "->", d["decision"], d["rule"])
            d = await call(s, "enforce_mandate", mission_id=mid, action_type="call", at_time="2026-10-02T21:30:00+05:30")
            print("call at 21:30 ->", d["decision"], d["note"])
            await call(s, "set_mandate", mission_id=mid, overrides={"standing_rent_mandate": {"payee": "Mr. Kulkarni", "amount": 48000}})
            d = await call(s, "enforce_mandate", mission_id=mid, action_type="pay_rent", amount=48000, payee="Mr. Kulkarni")
            print("rent w/ standing mandate ->", d["decision"], d["rule"])
            print("\n-- token gate --")
            g = await call(s, "purpose_evidence_gate", mission_id=mid, purpose="token", payee="Mr. Kulkarni", amount=8000, evidence_ref="P1")
            print("P1 gate:", g["condition_met"], g["why"])
            g2 = await call(s, "purpose_evidence_gate", mission_id=mid, purpose="token", payee="Mrs. Shah", amount=8000, evidence_ref="P2")
            print("P2 gate:", g2["condition_met"])
            print("\n-- repair --")
            r = await call(s, "create_mission", mission_type="REPAIR", goal="Fix bathroom leak", hard_constraints={}, closure_condition="leak fixed", principals=["Rahul"])
            rid = r["mission_id"]; await call(s, "set_mandate", mission_id=rid)
            q1 = await call(s, "get_quote", mission_id=rid, professional_id="PRO-QFIX", problem="leak")
            q2 = await call(s, "get_quote", mission_id=rid, professional_id="PRO-RAVI", problem="leak")
            print("quotes:", q1["total"], q2["total"])
            dec = await call(s, "enforce_mandate", mission_id=rid, action_type="pay_repair", amount=2400)
            b = await call(s, "book_visit", quote_id=q2["quote_id"], slot="Today 16:00", idempotency_key="k1")
            b2 = await call(s, "book_visit", quote_id=q2["quote_id"], slot="Today 16:00", idempotency_key="k1")
            print("idempotent booking same id:", b["booking_id"] == b2["booking_id"])
            await call(s, "capture_completion", booking_id=b["booking_id"])
            f = await call(s, "check_fix_status", booking_id=b["booking_id"]); print("check 1 fixed:", f["fixed"])
            g = await call(s, "purpose_evidence_gate", mission_id=rid, purpose="repair", payee="Ravi", amount=2400, evidence_ref=b["booking_id"])
            p = await call(s, "simulate_payment", mission_id=rid, payee="Ravi", amount=2400, purpose="repair", mandate_decision_id=dec["decision_id"], gate_id=g["gate_id"], idempotency_key="pay1")
            print("pay before fix:", p["status"], p.get("reason"))
            await call(s, "request_rework", booking_id=b["booking_id"], failure_evidence="still leaking photo")
            await call(s, "capture_completion", booking_id=b["booking_id"])
            f = await call(s, "check_fix_status", booking_id=b["booking_id"]); print("check 2 fixed:", f["fixed"])
            g = await call(s, "purpose_evidence_gate", mission_id=rid, purpose="repair", payee="Ravi", amount=2400, evidence_ref=b["booking_id"])
            p = await call(s, "simulate_payment", mission_id=rid, payee="Ravi", amount=2400, purpose="repair", mandate_decision_id=dec["decision_id"], gate_id=g["gate_id"], idempotency_key="pay2")
            p2 = await call(s, "simulate_payment", mission_id=rid, payee="Ravi", amount=2400, purpose="repair", mandate_decision_id=dec["decision_id"], gate_id=g["gate_id"], idempotency_key="pay2")
            print("pay after fix:", p["status"], "| retry same id:", p2["payment_id"] == p["payment_id"])
            x = await call(s, "update_mission_state", mission_id=rid, new_state="CLOSED", reason="done")
            print("close w/o receipt:", x.get("error"))
            rc = await call(s, "create_closure_receipt", mission_id=rid, outcome_summary="Leak fixed, verified after 24h", verified_evidence_refs=[f["evidence"]["renter_photo"]], renter_confirmed=True)
            x = await call(s, "update_mission_state", mission_id=rid, new_state="CLOSED", reason="verified")
            print("closed:", x["to"], "| receipt payments:", rc["payments"])
            print("\n-- logistics --")
            mv = await call(s, "create_physical_move", mission_id=mid, pickup_address="Old flat, Thane 400601", drop_address="Skyline Heights 400053", items=["boxes"], date="2026-10-01", slot="10-12", idempotency_key="mv1")
            t = await call(s, "track_and_prove_delivery", waybill=mv["waybill"]); print("track:", t["status"])
            await call(s, "recover_logistics_failure", waybill=mv["waybill"], action="PICKUP_RESCHEDULE", new_date="2026-10-02")
            t = await call(s, "track_and_prove_delivery", waybill=mv["waybill"]); print("track:", t["status"])
            t = await call(s, "track_and_prove_delivery", waybill=mv["waybill"]); print("track:", t["status"], "POD" in str(t).upper())
asyncio.run(main())
