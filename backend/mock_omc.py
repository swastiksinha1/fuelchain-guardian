"""
Mock OMC (Oil Marketing Company) Server

Simulates the OMC invoice validation API used by the credit service.
In production, replace with real IOCL/BPCL/HPCL API integration.

Run:  uvicorn mock_omc:app --port 8003
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Mock OMC API", version="1.0.0")

# Simulated dealer dispatch database
_dispatch_db: dict[str, dict] = {}


class ValidateRequest(BaseModel):
    invoice_ref: str
    dealer_id: str


@app.post("/validate")
async def validate_invoice(req: ValidateRequest):
    """Validate an OMC invoice reference and return dispatch details."""
    # Simulate ~90% valid invoices
    if random.random() < 0.1:
        return {"valid": False, "reason": "Invoice not found or already processed"}

    dispatch_id = f"DISP-{uuid.uuid4().hex[:8].upper()}"
    _dispatch_db[req.invoice_ref] = {
        "dispatch_id": dispatch_id,
        "dealer_id": req.dealer_id,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }

    return {
        "valid": True,
        "dispatch_id": dispatch_id,
        "invoice_ref": req.invoice_ref,
        "allocated_volume_l": random.randint(5000, 25000),
        "omc": random.choice(["IOCL", "BPCL", "HPCL"]),
        "dispatch_eta": "2024-01-15",
    }


@app.get("/dispatch/{dispatch_id}")
async def get_dispatch(dispatch_id: str):
    """Return dispatch status."""
    return {
        "dispatch_id": dispatch_id,
        "status": "confirmed",
        "vehicle": f"TN{random.randint(10, 99)}AB{random.randint(1000, 9999)}",
        "eta": "2024-01-16T08:00:00Z",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003)
