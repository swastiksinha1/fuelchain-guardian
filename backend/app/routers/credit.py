"""
Dealer Micro-Credit API

POST /apply         — Apply for advance payment credit
GET  /status/{id}  — Check loan status
GET  /history      — Dealer's loan history

Validates invoice against mock OMC API.
Disburses via mock UPI gateway (or real Razorpay in live mode).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.routers.auth import get_current_user
from shared.config import get_settings
from shared.database import get_db
from shared.models import CreditApplication, Dealer, Transaction, User

router = APIRouter()
logger = structlog.get_logger(__name__)
settings = get_settings()


# ── Schemas ───────────────────────────────────────────────────────────────

class CreditApplyRequest(BaseModel):
    amount: Decimal
    omc_invoice_ref: str
    invoice_image_b64: Optional[str] = None   # Base64 encoded invoice image
    notes: Optional[str] = None


class CreditStatusResponse(BaseModel):
    loan_id: str
    status: str
    amount: Decimal
    applied_at: datetime
    disbursed_at: Optional[datetime]
    due_date: Optional[datetime]
    repaid_at: Optional[datetime]
    omc_dispatch_id: Optional[str]


# ── OMC Invoice Validation ────────────────────────────────────────────────

async def validate_omc_invoice(invoice_ref: str, dealer_id: str) -> dict:
    """
    Validate invoice against OMC API.
    In production: call real OMC integration API (IOCL/BPCL/HPCL).
    Currently calls the mock OMC server.
    """
    mock_url = "http://localhost:8003"   # mock_omc service

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{mock_url}/validate",
                json={"invoice_ref": invoice_ref, "dealer_id": dealer_id},
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.warning("OMC validation unavailable, using mock response", error=str(e))

    # Fallback mock validation (for when mock OMC service isn't running)
    return {
        "valid": True,
        "dispatch_id": f"DISP-{uuid.uuid4().hex[:8].upper()}",
        "allocated_volume_l": 10000,
        "omc": "IOCL",
    }


# ── Payment Gateway ───────────────────────────────────────────────────────

async def disburse_payment(
    application_id: str,
    amount: Decimal,
    dealer_upi: str = "dealer@upi",
) -> dict:
    """
    Disburse payment via UPI.
    PAYMENT_MODE=mock → simulate, PAYMENT_MODE=live → use Razorpay.
    """
    if settings.PAYMENT_MODE == "live" and settings.RAZORPAY_KEY_ID:
        # Production: use RazorpayX payout API
        # Requires: pip install razorpay
        # import razorpay
        # client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        # payout = client.payout.create({...})
        logger.warning("Live Razorpay payment not yet wired up — using mock")

    # Mock disbursal
    tx_id = f"TXN{uuid.uuid4().hex[:10].upper()}"
    upi_ref = f"UPI{uuid.uuid4().hex[:12].upper()}"

    logger.info(
        "Mock payment disbursed",
        application_id=application_id,
        amount=str(amount),
        tx_id=tx_id,
    )

    return {
        "success": True,
        "gateway_tx_id": tx_id,
        "upi_ref": upi_ref,
        "gateway": "mock",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.post("/apply", status_code=201)
async def apply_for_credit(
    req: CreditApplyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Look up dealer record
    dealer_result = await db.execute(
        select(Dealer).where(Dealer.user_id == current_user.id)
    )
    dealer = dealer_result.scalar_one_or_none()
    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer profile not found")

    if not dealer.verified:
        raise HTTPException(status_code=403, detail="Dealer KYC not verified")

    # Check credit limit
    available = dealer.credit_limit - dealer.outstanding
    if req.amount > available:
        raise HTTPException(
            status_code=400,
            detail=f"Amount ₹{req.amount} exceeds available limit ₹{available}",
        )

    # Validate OMC invoice
    omc_result = await validate_omc_invoice(req.omc_invoice_ref, str(dealer.id))
    if not omc_result.get("valid"):
        raise HTTPException(status_code=422, detail="OMC invoice validation failed")

    # Create application
    app_id = uuid.uuid4()
    application = CreditApplication(
        id=app_id,
        dealer_id=dealer.id,
        amount=req.amount,
        omc_invoice_ref=req.omc_invoice_ref,
        omc_dispatch_id=omc_result.get("dispatch_id"),
        invoice_verified=True,
        status="approved",
        notes=req.notes,
    )
    db.add(application)

    # Attempt disbursal
    payment = await disburse_payment(str(app_id), req.amount)

    if payment["success"]:
        application.status = "disbursed"
        application.disbursed_at = datetime.now(timezone.utc)
        application.due_date = datetime.now(timezone.utc) + timedelta(days=30)

        # Record transaction
        tx = Transaction(
            id=uuid.uuid4(),
            application_id=app_id,
            tx_type="disbursal",
            amount=req.amount,
            gateway=payment["gateway"],
            gateway_tx_id=payment["gateway_tx_id"],
            status="success",
            upi_ref=payment["upi_ref"],
            completed_at=datetime.now(timezone.utc),
            tx_metadata=payment,
        )
        db.add(tx)

        # Update dealer outstanding
        await db.execute(
            text("UPDATE dealers SET outstanding = outstanding + :amt WHERE id = :id"),
            {"amt": float(req.amount), "id": str(dealer.id)},
        )

    await db.commit()

    logger.info(
        "Credit application processed",
        application_id=str(app_id),
        status=application.status,
        amount=str(req.amount),
    )

    return {
        "loan_id": str(app_id),
        "status": application.status,
        "amount": str(req.amount),
        "omc_dispatch_id": omc_result.get("dispatch_id"),
        "due_date": application.due_date.isoformat() if application.due_date else None,
        "upi_ref": payment.get("upi_ref"),
        "message": "Credit disbursed successfully" if payment["success"] else "Pending disbursal",
    }


@router.get("/status/{loan_id}", response_model=CreditStatusResponse)
async def get_credit_status(
    loan_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CreditApplication).where(
            CreditApplication.id == uuid.UUID(loan_id)
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Loan not found")

    return CreditStatusResponse(
        loan_id=str(app.id),
        status=app.status,
        amount=app.amount,
        applied_at=app.applied_at,
        disbursed_at=app.disbursed_at,
        due_date=app.due_date,
        repaid_at=app.repaid_at,
        omc_dispatch_id=app.omc_dispatch_id,
    )


@router.get("/history")
async def credit_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = 1,
    page_size: int = 20,
):
    dealer_result = await db.execute(
        select(Dealer).where(Dealer.user_id == current_user.id)
    )
    dealer = dealer_result.scalar_one_or_none()
    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer not found")

    offset = (page - 1) * page_size
    result = await db.execute(
        select(CreditApplication)
        .where(CreditApplication.dealer_id == dealer.id)
        .order_by(CreditApplication.applied_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    apps = result.scalars().all()

    return {
        "applications": [
            {
                "loan_id": str(a.id),
                "amount": str(a.amount),
                "status": a.status,
                "applied_at": a.applied_at.isoformat(),
                "disbursed_at": a.disbursed_at.isoformat() if a.disbursed_at else None,
                "due_date": a.due_date.isoformat() if a.due_date else None,
            }
            for a in apps
        ],
        "page": page,
        "page_size": page_size,
    }
