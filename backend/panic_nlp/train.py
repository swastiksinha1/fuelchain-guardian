"""
Panic Classifier Training Script

Generates a synthetic training dataset and fine-tunes
distilbert-base-multilingual-cased for binary panic classification.

Then exports the model to ONNX format for fast inference.

Usage:
    python -m panic_nlp.train
    # Outputs: models/panic_classifier/  (contains model.onnx + tokenizer)

Training takes ~10-20 min on CPU, ~2 min on GPU.
"""
from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Optional

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# ── Synthetic Dataset Generation ──────────────────────────────────────────

PANIC_TEMPLATES_EN = [
    "No petrol at {pump} in {city}! Huge queues everywhere #FuelCrisis",
    "{city} mein petrol khatam ho gaya! Sab pumps closed hain",
    "Diesel shortage in {city}, visited {n} pumps — all empty. #crisis",
    "Standing in queue for {h} hours in {city} for petrol. Disaster!",
    "BREAKING: All fuel stations closed in {city} #FuelShortage #India",
    "My car stuck in {city}, no fuel available anywhere near {area}",
    "Panic buying has cleared every petrol pump in {city}!",
    "{city} fuel dry out confirmed. Multiple pumps shut #PetrolCrisis",
    "Can't find diesel in {city}, queues of {n}+ cars at every pump",
    "Fuel crisis in {city}: government must act NOW #NoFuel",
    "7th pump visited today in {city} — still no petrol. #FuelDryOut",
    "बड़ी खबर: {city} में पेट्रोल खत्म! भारी भीड़ पेट्रोल पंप पर",
    "{city} ke petrol pumps bilkul dry hain! Kya kar rahi hai government?",
    "Long line at every {city} gas station. People panic buying fuel again",
    "Emergency: fuel shortage confirmed in {city} district #FuelEmergency",
]

NORMAL_TEMPLATES_EN = [
    "Just filled up at the IOCL pump in {city}. Good service today!",
    "Petrol prices stable in {city} this week. No major changes.",
    "Smooth experience at the BPCL pump near {area} in {city}.",
    "Government confirms adequate fuel reserves for next 45 days.",
    "Morning drive in {city} was great, fuel situation completely normal.",
    "OMCs confirm: India has 30-day strategic reserves. No shortage.",
    "Fuel supply chain running efficiently, says petroleum minister.",
    "{city} drivers: no queue at the HP pump near {area} right now.",
    "Visited my usual pump in {city}. Filled up in under 5 minutes.",
    "Petrol at ₹{price}/L in {city}. No unusual activity at pumps.",
    "{city} में पेट्रोल की स्थिति सामान्य है। घबराने की जरूरत नहीं।",
    "All fuel pumps operational in {city} and surrounding areas.",
    "No fuel shortage at my local pump in {city}. Stock is fine.",
    "IOCL depot confirms regular supply to all {city} dealers today.",
    "Filling station near me in {city} has plenty of diesel. No queue.",
]

CITIES = [
    "Mumbai", "Delhi", "Bangalore", "Chennai", "Kolkata", "Hyderabad",
    "Pune", "Ahmedabad", "Jaipur", "Lucknow", "Ranchi", "Bhopal",
    "Surat", "Nagpur", "Indore", "Patna", "Chandigarh", "Kochi",
    "Visakhapatnam", "Coimbatore",
]

PUMPS = ["IOCL pump", "BPCL station", "HP petrol pump", "local petrol pump", "fuel station"]
AREAS = ["sector 15", "main road", "ring road", "bus stand", "highway junction", "city center"]


def fill_template(template: str) -> str:
    return template.format(
        city=random.choice(CITIES),
        pump=random.choice(PUMPS),
        area=random.choice(AREAS),
        n=random.randint(3, 12),
        h=random.randint(1, 4),
        price=random.randint(95, 115),
    )


def generate_dataset(n_samples: int = 2000) -> list[dict]:
    """Generate balanced synthetic training data."""
    samples = []

    n_each = n_samples // 2

    for _ in range(n_each):
        text = fill_template(random.choice(PANIC_TEMPLATES_EN))
        samples.append({"text": text, "label": 1})   # panic

    for _ in range(n_each):
        text = fill_template(random.choice(NORMAL_TEMPLATES_EN))
        samples.append({"text": text, "label": 0})   # normal

    random.shuffle(samples)
    logger.info("Dataset generated", total=len(samples), panic=n_each, normal=n_each)
    return samples


def train_and_export(
    output_dir: str = "models/panic_classifier",
    n_samples: int = 2000,
    epochs: int = 3,
    batch_size: int = 16,
) -> None:
    """Fine-tune DistilBERT and export to ONNX."""
    try:
        import torch
        from datasets import Dataset
        from transformers import (
            AutoModelForSequenceClassification,
            AutoTokenizer,
            Trainer,
            TrainingArguments,
        )
        from optimum.exporters.onnx import main_export
    except ImportError:
        raise RuntimeError("Install requirements-nlp.txt: pip install -r requirements-nlp.txt")

    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, f1_score

    MODEL_NAME = "distilbert-base-multilingual-cased"
    os.makedirs(output_dir, exist_ok=True)

    logger.info("Loading tokenizer and model", model=MODEL_NAME)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME, num_labels=2)

    # Generate data
    data = generate_dataset(n_samples)
    train_data, val_data = train_test_split(data, test_size=0.15, random_state=42)

    def tokenize(examples):
        return tokenizer(examples["text"], truncation=True, padding="max_length", max_length=128)

    train_ds = Dataset.from_list(train_data).map(tokenize, batched=True)
    val_ds = Dataset.from_list(val_data).map(tokenize, batched=True)

    train_ds = train_ds.rename_column("label", "labels")
    val_ds = val_ds.rename_column("label", "labels")
    train_ds.set_format("torch")
    val_ds.set_format("torch")

    def compute_metrics(pred):
        logits, labels = pred
        preds = np.argmax(logits, axis=1)
        return {
            "accuracy": accuracy_score(labels, preds),
            "f1": f1_score(labels, preds),
        }

    training_args = TrainingArguments(
        output_dir=os.path.join(output_dir, "checkpoints"),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        evaluation_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="f1",
        logging_steps=50,
        no_cuda=not torch.cuda.is_available(),
        report_to="none",
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        tokenizer=tokenizer,
        compute_metrics=compute_metrics,
    )

    logger.info("Starting training", epochs=epochs, train_samples=len(train_data))
    trainer.train()

    # Save tokenizer
    tokenizer.save_pretrained(output_dir)

    # Export to ONNX
    logger.info("Exporting to ONNX")
    onnx_path = os.path.join(output_dir, "model.onnx")
    try:
        from optimum.onnxruntime import ORTModelForSequenceClassification
        ort_model = ORTModelForSequenceClassification.from_pretrained(
            output_dir, export=True
        )
        ort_model.save_pretrained(output_dir)
        logger.info("ONNX export complete", path=onnx_path)
    except Exception as e:
        logger.warning("ONNX export via optimum failed, trying torch.onnx", error=str(e))
        # Fallback manual ONNX export
        dummy_input = tokenizer(
            "test", return_tensors="pt", padding="max_length", max_length=128
        )
        torch.onnx.export(
            model,
            (dummy_input["input_ids"], dummy_input["attention_mask"]),
            onnx_path,
            input_names=["input_ids", "attention_mask"],
            output_names=["logits"],
            dynamic_axes={
                "input_ids": {0: "batch_size"},
                "attention_mask": {0: "batch_size"},
            },
            opset_version=12,
        )
        logger.info("Manual ONNX export complete", path=onnx_path)

    # Save dataset for reference
    dataset_path = os.path.join(output_dir, "training_data.jsonl")
    with open(dataset_path, "w") as f:
        for sample in data:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")

    logger.info(
        "Training complete",
        output_dir=output_dir,
        onnx_model=onnx_path,
        dataset=dataset_path,
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="models/panic_classifier")
    parser.add_argument("--samples", type=int, default=2000)
    parser.add_argument("--epochs", type=int, default=3)
    args = parser.parse_args()
    train_and_export(args.output, args.samples, args.epochs)
