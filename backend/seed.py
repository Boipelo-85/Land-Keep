"""Seed the LandKeep database with realistic demo data.

Run from the backend folder:   python seed.py

Creates: 1 landlord, 5 properties, 50 units (42 occupied), 42 tenants with leases,
up to 12 months of rent charges and payments (on-time, chronically late and
in-arrears tenants), ~400 labelled maintenance requests, 12 tenant applications
with status history, reminder logs, and a CSV of labelled requests for the ML model.

Everything is synthetic. Say so in the report: model accuracy on this data does not
predict accuracy on real landlords.
"""
import csv
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

from app import models as m
from app.database import Base, SessionLocal, engine
from app.security import hash_password
from app.services.credit import MockCreditBureau, recommend

DEMO_PASSWORD = "password123"
N_REQUESTS = 400
NOW = datetime.now().replace(microsecond=0)
TODAY = NOW.date()
CSV_PATH = Path(__file__).resolve().parent / "data" / "maintenance_requests.csv"

PROPERTIES = [
    ("Baobab Court", "12 Church Street", "Pretoria"),
    ("Marula Gardens", "48 Bree Street", "Johannesburg"),
    ("Jacaranda Heights", "7 Marine Parade", "Durban"),
    ("Fynbos Place", "21 Long Street", "Cape Town"),
    ("Acacia Mews", "3 President Brand Street", "Bloemfontein"),
]
RENT_RANGE = {1: (4800, 6500), 2: (6500, 9000), 3: (9000, 12500)}
FIRST = ["Thandi", "Sipho", "Lerato", "Pieter", "Naledi", "Kagiso", "Ayesha", "Johan", "Nomsa", "Tebogo",
         "Zanele", "Mpho", "Anele", "Riaan", "Palesa", "Bongani", "Fatima", "Dineo", "Kabelo", "Lindiwe"]
LAST = ["Dlamini", "Nkosi", "Mokoena", "van der Merwe", "Khumalo", "Naidoo", "Botha", "Sithole", "Molefe",
        "Pillay", "Ndlovu", "Mahlangu", "Venter", "Zulu", "Radebe", "Maseko", "Jacobs", "Mthembu"]
EMPLOYERS = ["Retail chain", "Government department", "Bank", "Mining company", "School", "Hospital",
             "Logistics firm", "Self-employed", "Call centre", "Construction firm"]

# --------------------------------------------------------------------------------------
# Maintenance request text. Templates are varied on purpose, but they are still templates:
# a classifier will score optimistically on them. Add ~50 hand-written test requests
# before reporting final accuracy.
# --------------------------------------------------------------------------------------
ROOMS = ["kitchen", "bathroom", "bedroom", "lounge", "passage", "toilet", "main bedroom"]
FIXTURES = ["kitchen sink", "bathroom basin", "bath", "shower"]
INTROS = ["", "", "", "Hi, ", "Good morning, ", "Hello landlord, ", "Please help: ", "Urgent: "]
OUTROS = ["", "", "", " Please assist.", " Can someone come and look?", " It started last night.",
          " It is getting worse.", " Thanks.", " I have attached a photo."]

TEMPLATES = {
    ("plumbing", "high"): [
        "Water is leaking through the {room} ceiling",
        "Burst pipe in the {room}, water everywhere",
        "The toilet is overflowing and flooding the {room}",
        "Geyser is leaking and dripping onto the floor",
        "Water is pouring out from under the {fixture}",
        "No water at all in the unit since this morning and the pipe outside is flooding",
        "Sewage is coming up through the {fixture} drain",
    ],
    ("plumbing", "low"): [
        "The {fixture} tap is dripping",
        "Slow draining {fixture}, probably blocked",
        "Toilet keeps running after flushing",
        "Low water pressure in the {room}",
        "Shower head is loose and sprays sideways",
        "Geyser takes very long to heat up",
        "Tap in the {room} is stiff and hard to turn",
    ],
    ("electrical", "high"): [
        "Sparks coming from the {room} plug socket",
        "No power in the whole unit and the DB board keeps tripping",
        "Burning smell from the stove plug",
        "Exposed live wires hanging in the {room}",
        "Smoke coming from the distribution board",
        "I got an electric shock when I touched the {room} switch",
    ],
    ("electrical", "low"): [
        "The light bulb in the {room} needs replacing",
        "Light in the {room} flickers sometimes",
        "Plug socket in the {room} is loose",
        "Passage light switch is not working",
        "One stove plate is not heating properly",
        "Doorbell is not working",
        "Power does not come back on by itself after load shedding",
    ],
    ("security", "high"): [
        "Front door lock is broken and the door will not close",
        "Someone tried to break in through the {room} window",
        "Burglar bars on the {room} window were cut",
        "I lost my keys and need the locks changed urgently",
        "Security gate is stuck open and strangers are walking in",
        "Window in the {room} is smashed and the unit is not secure",
    ],
    ("security", "low"): [
        "Gate remote battery is flat",
        "Intercom is crackling and hard to hear",
        "Back door key is stiff to turn",
        "Need a spare key cut for the {room} door",
        "Outside security light is dim",
        "Visitor buzzer is not working",
    ],
    ("general", "high"): [
        "Ceiling is sagging in the {room} and looks like it may fall",
        "Large crack in the {room} wall is getting wider every day",
        "Mould is spreading quickly in the {room} and the kids are coughing",
        "The balcony railing has come loose and is dangerous",
    ],
    ("general", "low"): [
        "Paint is peeling in the {room}",
        "Kitchen cupboard door is hanging loose",
        "Window in the {room} will not close properly",
        "Garden needs trimming",
        "Floor tiles in the {room} are cracked",
        "Please repaint the {room} before winter",
        "Damp patch on the {room} wall",
        "Cockroaches in the kitchen, need pest control",
    ],
}
CATEGORY_WEIGHTS = {"plumbing": 35, "electrical": 25, "security": 12, "general": 28}
HIGH_URGENCY_CHANCE = {"plumbing": 0.30, "electrical": 0.35, "security": 0.40, "general": 0.10}


def make_request_text(category: str, urgency: str, rng: random.Random) -> str:
    sentence = rng.choice(TEMPLATES[(category, urgency)])
    sentence = sentence.format(room=rng.choice(ROOMS), fixture=rng.choice(FIXTURES))
    text = rng.choice(INTROS) + sentence + rng.choice(OUTROS)
    if text[0].islower():
        text = text[0].upper() + text[1:]
    return text


# --------------------------------------------------------------------------------------
def first_of_month(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, n: int) -> date:
    idx = d.year * 12 + (d.month - 1) + n
    return date(idx // 12, idx % 12 + 1, 1)


def at(d: date, hour: int = 9, minute: int = 0) -> datetime:
    return datetime.combine(d, time(hour, minute))


def main() -> None:
    rng = random.Random(42)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    demo_hash = hash_password(DEMO_PASSWORD)  # hashed once; every demo user shares the password
    used_emails: set[str] = set()

    with SessionLocal() as s:

        def new_person(role: str, created: datetime) -> m.User:
            while True:
                first, last = rng.choice(FIRST), rng.choice(LAST)
                email = f"{first}.{last}{rng.randint(1, 99)}@example.com".lower().replace(" ", "")
                if email not in used_emails:
                    used_emails.add(email)
                    break
            user = m.User(role=role, full_name=f"{first} {last}", email=email,
                          phone=f"+2771{rng.randint(1000000, 9999999)}", password_hash=demo_hash,
                          created_at=created)
            s.add(user)
            s.flush()
            return user

        def add_history(app, status, note, when, by):
            s.add(m.ApplicationStatusHistory(application_id=app.id, status=status, note=note,
                                             changed_by_id=by, created_at=when))

        # ---- landlord, properties, units ------------------------------------------------
        landlord = m.User(role="landlord", full_name="Thabo Mokoena", email="landlord@landkeep.test",
                          phone="+27715550100", password_hash=demo_hash,
                          created_at=at(add_months(TODAY, -14)))
        s.add(landlord)
        s.flush()
        used_emails.add(landlord.email)

        # A known applicant account with no application yet, for the live demo (scene 1)
        s.add(m.User(role="tenant", full_name="Naledi Khumalo", email="applicant@landkeep.test",
                     phone="+27825550123", password_hash=demo_hash, created_at=at(TODAY)))
        used_emails.add("applicant@landkeep.test")
        s.flush()

        # Demo tenant with an active lease (report a problem without the application flow)
        demo_tenant = m.User(role="tenant", full_name="Sipho Dlamini", email="tenant@landkeep.test",
                             phone="+27825550199", password_hash=demo_hash,
                             created_at=at(add_months(TODAY, -8)))
        s.add(demo_tenant)
        s.flush()
        used_emails.add(demo_tenant.email)

        units: list[m.Unit] = []
        for pi, (pname, address, city) in enumerate(PROPERTIES):
            prop = m.Property(landlord_id=landlord.id, name=pname, address=address, city=city,
                              created_at=at(add_months(TODAY, -14)))
            s.add(prop)
            s.flush()
            for n in range(1, 11):
                beds = rng.choice([1, 2, 2, 3])
                rent = round(rng.uniform(*RENT_RANGE[beds]) / 50) * 50
                unit = m.Unit(property_id=prop.id, unit_number=f"{chr(65 + pi)}{n:02d}", bedrooms=beds,
                              monthly_rent=float(rent), status="vacant", created_at=at(add_months(TODAY, -14)))
                s.add(unit)
                units.append(unit)
        s.flush()

        # ---- tenants and leases ---------------------------------------------------------
        occupied = rng.sample(units, 42)
        leases: list[m.Lease] = []
        profile: dict[int, str] = {}

        # First occupied unit belongs to the known demo tenant
        demo_unit = occupied[0]
        demo_unit.status = "occupied"
        demo_start = add_months(first_of_month(TODAY), -6)
        demo_lease = m.Lease(unit_id=demo_unit.id, tenant_id=demo_tenant.id, start_date=demo_start,
                             end_date=add_months(demo_start, 12) - timedelta(days=1),
                             monthly_rent=demo_unit.monthly_rent, deposit=demo_unit.monthly_rent,
                             due_day=1, status="active",
                             accepted_at=at(demo_start - timedelta(days=5)),
                             created_at=at(demo_start - timedelta(days=14)))
        s.add(demo_lease)
        s.flush()
        leases.append(demo_lease)
        profile[demo_lease.id] = "on_time"

        for unit in occupied[1:]:
            unit.status = "occupied"
            start = add_months(first_of_month(TODAY), -rng.randint(3, 12))
            tenant = new_person("tenant", at(start - timedelta(days=20)))
            term = rng.choice([12, 12, 24])
            lease = m.Lease(unit_id=unit.id, tenant_id=tenant.id, start_date=start,
                            end_date=add_months(start, term) - timedelta(days=1),
                            monthly_rent=unit.monthly_rent, deposit=unit.monthly_rent,
                            due_day=rng.choice([1, 1, 1, 5, 7, 25]), status="active",
                            accepted_at=at(start - timedelta(days=rng.randint(3, 10))),
                            created_at=at(start - timedelta(days=14)))
            s.add(lease)
            s.flush()
            leases.append(lease)
            profile[lease.id] = rng.choices(["on_time", "late", "arrears"], [70, 18, 12])[0]

        # ---- rent charges, payments, reminder logs --------------------------------------
        for lease in leases:
            kind = profile[lease.id]
            arrears_from = add_months(first_of_month(TODAY), -rng.randint(2, 3)) if kind == "arrears" else None
            period = first_of_month(lease.start_date)
            while period <= first_of_month(TODAY):
                due = date(period.year, period.month, lease.due_day)
                charge = m.RentCharge(lease_id=lease.id, period=period, amount_due=lease.monthly_rent,
                                      due_date=due, created_at=at(period))
                s.add(charge)
                s.flush()

                paid_on = None
                if kind == "arrears" and period >= arrears_from:
                    paid_on = None
                elif kind == "arrears":
                    paid_on = due + timedelta(days=rng.randint(0, 5))
                elif kind == "late":
                    paid_on = due + timedelta(days=rng.randint(4, 18))
                else:
                    paid_on = due - timedelta(days=rng.randint(0, 2))
                    if rng.random() < 0.05:
                        paid_on = due + timedelta(days=rng.randint(1, 3))

                if paid_on is not None and paid_on <= TODAY:
                    paid_at = at(paid_on, rng.randint(7, 18), rng.randint(0, 59))
                    s.add(m.Payment(charge_id=charge.id, amount=lease.monthly_rent, paid_at=paid_at,
                                    method=rng.choices(["eft", "debit_order", "cash"], [80, 15, 5])[0],
                                    created_at=paid_at))
                elif due < TODAY:
                    # unpaid and overdue: the automation already sent its reminders
                    days_overdue = (TODAY - due).days
                    for step, channel in ((1, "sms"), (5, "email"), (10, "sms")):
                        if days_overdue >= step:
                            s.add(m.ReminderLog(charge_id=charge.id, step=step, channel=channel,
                                                sent_at=at(due + timedelta(days=step), 9, 0)))
                period = add_months(period, 1)

        # ---- maintenance requests -------------------------------------------------------
        weights = [rng.paretovariate(3.5) for _ in leases]  # a few units have many repeat problems
        picks = rng.choices(leases, weights=weights, k=N_REQUESTS)
        categories = list(CATEGORY_WEIGHTS)
        cat_weights = list(CATEGORY_WEIGHTS.values())
        rows_for_csv = []
        for lease in picks:
            category = rng.choices(categories, cat_weights)[0]
            urgency = "high" if rng.random() < HIGH_URGENCY_CHANCE[category] else "low"
            text = make_request_text(category, urgency, rng)

            earliest = at(lease.start_date) + timedelta(days=1)
            span = int((NOW - earliest).total_seconds())
            created = earliest + timedelta(seconds=rng.randint(0, max(span, 1)))
            status, resolved_at = "open", None
            if (NOW - created).days < 2:
                status = rng.choice(["open", "open", "in_progress"])
            elif rng.random() >= 0.06:
                hours = rng.randint(4, 72) if urgency == "high" else rng.randint(48, 14 * 24)
                if created + timedelta(hours=hours) <= NOW:
                    status, resolved_at = "resolved", created + timedelta(hours=hours)
                else:
                    status = "in_progress"
            else:
                status = "in_progress"  # stuck request: useful for the "long delays" analytics

            req = m.MaintenanceRequest(unit_id=lease.unit_id, tenant_id=lease.tenant_id, description=text,
                                       status=status, confirmed_category=category, confirmed_urgency=urgency,
                                       created_at=created, resolved_at=resolved_at)
            s.add(req)
            rows_for_csv.append((text, category, urgency, created.isoformat(sep=" ")))
        s.flush()

        # ---- tenant applications (the onboarding flow) ----------------------------------
        vacant = [u for u in units if u.status == "vacant"]
        bureau = MockCreditBureau()
        # 1 just submitted, 5 waiting for the landlord (live demo material), 6 already decided
        plan = ["submitted"] + ["under_review"] * 5 + ["decided"] * 6
        for i, outcome in enumerate(plan):
            submitted = NOW - timedelta(days=rng.randint(1, 20), hours=rng.randint(0, 12))
            applicant = new_person("tenant", submitted - timedelta(minutes=30))
            unit = vacant[i % len(vacant)]
            income = float(rng.randrange(9000, 45001, 500))
            id_number = "".join(rng.choice("0123456789") for _ in range(13))
            app = m.TenantApplication(reference_no=f"LK-{TODAY.year}-{i + 1:05d}", applicant_id=applicant.id,
                                      unit_id=unit.id, monthly_income=income,
                                      employer=rng.choice(EMPLOYERS), id_number=id_number,
                                      consent_given=True, consent_at=submitted, status="submitted",
                                      created_at=submitted)
            s.add(app)
            s.flush()
            add_history(app, "submitted", "Application received", submitted, applicant.id)
            if outcome == "submitted":
                continue

            checked = submitted + timedelta(minutes=5)
            result = bureau.check(id_number, income)
            app.credit_score = result.score
            app.credit_checked_at = checked
            app.recommendation = recommend(result.score, income, unit.monthly_rent)
            app.status = "under_review"
            add_history(app, "under_review", f"Credit check done ({result.source}), recommendation: "
                        f"{app.recommendation}", checked, None)
            if outcome == "under_review":
                continue

            # Seeded landlord decisions follow the system's recommendation ("review" cases get approved)
            outcome = "rejected" if app.recommendation == "decline" else "approved"
            decided = min(submitted + timedelta(days=rng.randint(1, 3)), NOW)
            app.status, app.decision_by, app.decided_at = outcome, landlord.id, decided
            add_history(app, outcome, f"Landlord {outcome} the application", decided, landlord.id)
            first = applicant.full_name.split()[0]
            for channel in ("email", "sms"):
                s.add(m.Notification(user_id=applicant.id, channel=channel, template=f"application_{outcome}",
                                     subject="Your LandKeep application",
                                     body=f"Hi {first}, your application {app.reference_no} was {outcome}.",
                                     status="sent", created_at=decided))

        s.commit()

        # ---- summary ---------------------------------------------------------------------
        overdue_leases = {
            c.lease_id for c in s.query(m.RentCharge).filter(m.RentCharge.due_date < TODAY)
            if not s.query(m.Payment).filter(m.Payment.charge_id == c.id).first()
        }
        print("Seed complete")
        for label, model in [("users", m.User), ("properties", m.Property), ("units", m.Unit),
                             ("leases", m.Lease), ("rent charges", m.RentCharge), ("payments", m.Payment),
                             ("maintenance requests", m.MaintenanceRequest),
                             ("applications", m.TenantApplication),
                             ("status history rows", m.ApplicationStatusHistory),
                             ("reminder logs", m.ReminderLog), ("notifications", m.Notification)]:
            print(f"  {label:<22}{s.query(model).count()}")
        print(f"  leases with unpaid overdue rent: {len(overdue_leases)}")

    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["text", "category", "urgency", "created_at"])
        writer.writerows(rows_for_csv)
    print(f"  ML training data written to {CSV_PATH}")
    print(f"\nLandlord login:  landlord@landkeep.test / {DEMO_PASSWORD}")
    print(f"Applicant login: applicant@landkeep.test / {DEMO_PASSWORD}")
    print(f"Tenant login:    tenant@landkeep.test / {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
