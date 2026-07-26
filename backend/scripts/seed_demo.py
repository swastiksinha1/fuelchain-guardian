"""
Demo Data Seeder

Seeds the database with:
  - Admin user  (admin@fuelchain.dev / Admin@1234)
  - Sample dealer with verified KYC (dealer@fuelchain.dev / Dealer@1234)

Run:  docker compose exec backend python -m scripts.seed_demo
"""
from __future__ import annotations
import asyncio
import uuid
import structlog

from app.routers.auth import hash_password
from shared.config import configure_logging
from shared.database import AsyncSessionLocal
from shared.models import Dealer, User

logger = structlog.get_logger(__name__)


async def seed() -> None:
    configure_logging("seed-demo")

    async with AsyncSessionLocal() as session:
        # Check if already seeded
        from sqlalchemy import select, text
        existing = await session.execute(
            text("SELECT COUNT(*) FROM users WHERE email = 'admin@fuelchain.dev'")
        )
        count = existing.scalar()
        if count and count > 0:
            logger.info("Demo data already exists, skipping")
            return

        # Admin user
        admin_id = uuid.uuid4()
        admin = User(
            id=admin_id,
            email="admin@fuelchain.dev",
            hashed_password=hash_password("Admin@1234"),
            full_name="FuelChain Admin",
            role="admin",
        )
        session.add(admin)

        # Demo dealer user
        dealer_user_id = uuid.uuid4()
        dealer_user = User(
            id=dealer_user_id,
            email="dealer@fuelchain.dev",
            hashed_password=hash_password("Dealer@1234"),
            full_name="Ravi Kumar",
            role="dealer",
        )
        session.add(dealer_user)

        # Demo dealer profile
        dealer = Dealer(
            id=uuid.uuid4(),
            user_id=dealer_user_id,
            business_name="Ravi Kumar Petroleum",
            gstin="27AAPFU0939F1ZV",
            pan="AAPFU0939F",
            omc="IOCL",
            credit_limit=1000000,
            outstanding=0,
            verified=True,
        )
        session.add(dealer)

        await session.commit()
        logger.info(
            "Demo data seeded",
            admin="admin@fuelchain.dev / Admin@1234",
            dealer="dealer@fuelchain.dev / Dealer@1234",
        )


if __name__ == "__main__":
    asyncio.run(seed())
