"""
Panic NLP Classification Service

FastAPI service that classifies text for fuel panic.
Uses a fine-tuned multilingual DistilBERT exported to ONNX.

Falls back to a keyword-based classifier if ONNX model is not available
(allows the system to run without training the model first).

POST /classify  → {text, city} → {is_panic, score, city}

Run:  python -m panic_nlp.service
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import numpy as np
import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram, make_asgi_app
from pydantic import BaseModel

from shared.config import configure_logging, get_settings

logger = structlog.get_logger(__name__)
configure_logging("panic-nlp")

# ── Metrics ────────────────────────────────────────────────────────────────
classifications = Counter("panic_nlp_classifications_total", "Texts classified", ["is_panic"])
inference_latency = Histogram("panic_nlp_inference_seconds", "Inference latency")

# ── Panic keywords (multilingual fallback) ────────────────────────────────
PANIC_KEYWORDS_EN = [
    "no petrol", "no diesel", "fuel shortage", "pump empty", "pump closed",
    "fuel crisis", "long queue", "panic buying", "hoarding", "dry out",
    "fuel dry", "no fuel", "queue", "shortage", "crisis", "empty", "finished",
    "khatam", "band", "nahi", "bahut", "line",
]

CITY_KEYWORDS = [
    "mumbai", "delhi", "bangalore", "bengaluru", "chennai", "kolkata",
    "hyderabad", "pune", "ahmedabad", "jaipur", "lucknow", "ranchi",
    "bhopal", "surat", "nagpur", "indore",
]


class KeywordClassifier:
    """Fast keyword-based classifier used as fallback."""

    def predict(self, text: str) -> tuple[bool, float]:
        text_lower = text.lower()
        score = 0.0
        matches = sum(1 for kw in PANIC_KEYWORDS_EN if kw in text_lower)
        score = min(0.95, matches * 0.18)
        # Boost for all-caps or exclamation (panic signal)
        if text.isupper() or text.count("!") > 1:
            score = min(0.95, score + 0.15)
        return score > 0.35, round(score, 3)

    def extract_city(self, text: str) -> Optional[str]:
        text_lower = text.lower()
        for city in CITY_KEYWORDS:
            if city in text_lower:
                return city.title()
        return None


class ONNXClassifier:
    """
    DistilBERT ONNX classifier.
    Load from MODEL_PATH if available.
    """

    def __init__(self, model_path: str):
        import onnxruntime as ort
        from transformers import AutoTokenizer

        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        self.session = ort.InferenceSession(
            os.path.join(model_path, "model.onnx"),
            providers=["CPUExecutionProvider"],
        )
        logger.info("ONNX model loaded", model_path=model_path)

    def predict(self, text: str) -> tuple[bool, float]:
        inputs = self.tokenizer(
            text,
            return_tensors="np",
            max_length=128,
            truncation=True,
            padding="max_length",
        )
        outputs = self.session.run(
            None,
            {
                "input_ids": inputs["input_ids"].astype(np.int64),
                "attention_mask": inputs["attention_mask"].astype(np.int64),
            },
        )
        logits = outputs[0][0]
        # Assume binary: 0=normal, 1=panic
        probs = np.exp(logits) / np.sum(np.exp(logits))
        score = float(probs[1])
        return score > 0.5, round(score, 3)

    def extract_city(self, text: str) -> Optional[str]:
        text_lower = text.lower()
        for city in CITY_KEYWORDS:
            if city in text_lower:
                return city.title()
        return None


# ── Load classifier ───────────────────────────────────────────────────────
def load_classifier():
    settings = get_settings()
    model_path = settings.MODEL_PATH
    onnx_file = Path(model_path) / "model.onnx"

    if onnx_file.exists():
        try:
            return ONNXClassifier(model_path)
        except Exception as e:
            logger.warning("ONNX load failed, using keyword fallback", error=str(e))
    else:
        logger.info("ONNX model not found, using keyword fallback", path=str(onnx_file))

    return KeywordClassifier()


classifier = load_classifier()

# ── FastAPI App ───────────────────────────────────────────────────────────
app = FastAPI(
    title="FuelChain Panic NLP Service",
    version="1.0.0",
    description="Multilingual panic classification for fuel shortage tweets",
)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# Prometheus ASGI endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


class ClassifyRequest(BaseModel):
    text: str
    city: Optional[str] = None
    tweet_id: Optional[str] = None


class ClassifyResponse(BaseModel):
    is_panic: bool
    score: float
    city: Optional[str]
    tweet_id: Optional[str]


@app.get("/health")
async def health():
    return {"status": "ok", "classifier": type(classifier).__name__}


@app.post("/classify", response_model=ClassifyResponse)
async def classify(req: ClassifyRequest) -> ClassifyResponse:
    with inference_latency.time():
        is_panic, score = classifier.predict(req.text)
        city = req.city or classifier.extract_city(req.text)

    classifications.labels(is_panic=str(is_panic)).inc()
    logger.debug("Classified", is_panic=is_panic, score=score, city=city)

    return ClassifyResponse(
        is_panic=is_panic,
        score=score,
        city=city,
        tweet_id=req.tweet_id,
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001, log_config=None)
