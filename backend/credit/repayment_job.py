"""
Repayment Scheduler

Runs every hour to:
  - Mark overdue loans (past due_date, still 'disbursed')
  - Simulate automatic repayments for demo purposes

In production: replace simulate_repayments() with a webhook handler
from your UPI payment gateway (Razorpay/Cashfree collection callback).

Run:  python -m credit.repayment_job
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, text

from shared.config import configure_logging, get_settings
from shared.database import AsyncSessionLocal
from shared.models import CreditApplication, Transaction

logger = structlog.get_logger(__name__)


async def check_overdue_loans() -> None:
    """Mark disbursed loans past due date as overdue."""
    async with AsyncSessionLocal() as session:
        now = datetime.now(timezone.utc)
        result = await session.execute(
            select(CreditApplication).where(
                CreditApplication.status == "disbursed",
                CreditApplication.due_date < now,
            )
        )
        overdue = result.scalars().all()

        for loan in overdue:
            loan.status = "overdue"
            logger.warning(
                "Loan overdue",
                loan_id=str(loan.id),
                amount=str(loan.amount),
                due=loan.due_date.isoformat(),
            )

        if overdue:
            await session.commit()
            logger.info("Overdue check complete", marked=len(overdue))
        else:
            logger.info("Overdue check complete", marked=0)


async def simulate_repayments() -> None:
    """
    Demo: randomly repay ~20 % of disbursed loans per run.
    In production this is triggered by a payment gateway webhook.
    """
    import random

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(CreditApplication)
            .where(CreditApplication.status == "disbursed")
            .limit(20)
        )
        loans = result.scalars().all()

        repaid = 0
        for loan in loans:
            if random.random() < 0.20:
                loan.status = "repaid"
                loan.repaid_at = datetime.now(timezone.utc)

                tx = Transaction(
                    id=uuid.uuid4(),
                    application_id=loan.id,
                    tx_type="repayment",
                    amount=loan.amount,
                    gateway="mock",
                    gateway_tx_id=f"RPY{uuid.uuid4().hex[:10].upper()}",
                    status="success",
                    completed_at=datetime.now(timezone.utc),
                )
                session.add(tx)

                await session.execute(
                    text(
                        "UPDATE dealers "
                        "SET outstanding = GREATEST(0, outstanding - :amt) "
                        "WHERE id = :did"
                    ),
                    {"amt": float(loan.amount), "did": str(loan.dealer_id)},
                )
                repaid += 1

        if repaid:
            await session.commit()
            logger.info("Repayments simulated", count=repaid)


async def run() -> None:
    configure_logging("repayment-job")
    logger.info("Repayment scheduler starting")

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(check_overdue_loans,  "interval", hours=1,   id="overdue")
    scheduler.add_job(simulate_repayments,  "interval", minutes=30, id="repay")
    scheduler.start()

    logger.info("Scheduler running — press Ctrl+C to stop")
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Repayment scheduler stopped")


if __name__ == "__main__":
    asyncio.run(run())
