from datetime import datetime, timedelta
from io import BytesIO

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session

from app.models import Application, Lease, RentCharge, Unit, User
from app.services.notifications import notify


def create_lease(db: Session, application: Application, unit: Unit) -> Lease:
    lease = Lease(
        application_id=application.id,
        tenant_id=application.tenant_id,
        unit_id=unit.id,
        monthly_rent=unit.monthly_rent,
    )
    unit.is_vacant = False
    db.add(lease)
    return lease


def create_lease_pdf(lease: Lease, tenant: User, unit: Unit) -> bytes:
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=letter)
    pdf.setTitle(f"Land-Keep lease {lease.id}")
    pdf.drawString(72, 730, "Land-Keep Residential Lease")
    pdf.drawString(72, 700, f"Tenant: {tenant.full_name}")
    pdf.drawString(72, 680, f"Property: {unit.address} - {unit.title}")
    pdf.drawString(72, 660, f"Monthly rent: R{lease.monthly_rent:,.2f}")
    pdf.drawString(72, 640, f"Lease status: {lease.status}")
    pdf.drawString(72, 600, "This document is a demonstration lease summary.")
    pdf.save()
    return output.getvalue()


def accept_lease(db: Session, lease: Lease) -> RentCharge:
    lease.status = "active"
    charge = RentCharge(
        lease_id=lease.id,
        amount=lease.monthly_rent,
        due_date=datetime.utcnow() + timedelta(days=30),
        status="due",
    )
    db.add(charge)
    notify(db, lease.tenant_id, f"Lease {lease.id} accepted; your first rent charge is due in 30 days.")
    return charge
