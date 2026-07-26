"""
Social Media Kafka Producer

In TWITTER mode: connects to Twitter API v2 filtered stream for fuel panic keywords.
In SIMULATOR mode: generates synthetic panic/non-panic tweets.

Publishes to raw.social.v1

Run:  python -m panic_nlp.social_producer
"""
from __future__ import annotations

import asyncio
import json
import random
import uuid
from datetime import datetime, timezone

import structlog
from aiokafka import AIOKafkaProducer
from prometheus_client import Counter, start_http_server

from shared.config import configure_logging, get_settings

logger = structlog.get_logger(__name__)
tweets_published = Counter("social_producer_tweets_total", "Tweets published", ["mode"])

# ── Simulator data ─────────────────────────────────────────────────────────

PANIC_TWEETS = [
    "No petrol at any pump in {city}! Huge queues everywhere #FuelCrisis",
    "{city} mein petrol khatam! Sab pumps band hain. #petrol #crisis",
    "Bhai {city} mein diesel nahi mil raha, 3 pump check kiye sab dry!",
    "Fuel shortage in {city} is REAL. Queue of 50+ cars at every pump.",
    "Standing in line for 2 hours in {city} for petrol. Country is finished.",
    "Panic buying has emptied all petrol stations in {city}! #India #FuelShortage",
    "{city} ke sabhi petrol pumps band ho gaye! Kal kya hoga?",
    "My car is stuck, no fuel in entire {city}. What is government doing?",
    "BREAKING: Multiple fuel stations closed in {city} citing shortage #FuelCrisis",
    "7 pumps visited in {city}, all out of petrol. This is a disaster.",
]

NORMAL_TWEETS = [
    "Just filled up at the Shell pump in {city}. Quick service today.",
    "Petrol prices stable in {city} this week, no major changes.",
    "Had a smooth experience at the IOCL pump near my house in {city}.",
    "Fuel prices in India remain competitive compared to global rates.",
    "Morning drive in {city} was smooth, fuel situation seems normal.",
    "No issues at my local pump in {city} today.",
    "Government ensuring stable fuel supply says minister.",
    "OMC stocks adequate for next 30 days per official statement.",
    "Just did routine maintenance on my car in {city}, fuel tanks full!",
    "Traffic moving well in {city} today, no fuel queue sightings.",
]

CITIES = [
    "Mumbai", "Delhi", "Bangalore", "Chennai", "Kolkata",
    "Hyderabad", "Pune", "Ahmedabad", "Jaipur", "Lucknow",
    "Ranchi", "Bhopal", "Surat", "Nagpur", "Indore",
]


class TweetSimulator:
    def __init__(self, panic_rate: float = 0.3, tweets_per_second: float = 2.0):
        self.panic_rate = panic_rate
        self.tweets_per_second = tweets_per_second

    async def stream(self):
        while True:
            city = random.choice(CITIES)
            is_panic = random.random() < self.panic_rate

            templates = PANIC_TWEETS if is_panic else NORMAL_TWEETS
            text = random.choice(templates).format(city=city)

            yield {
                "tweet_id": str(uuid.uuid4().int)[:18],
                "text": text,
                "city": city,
                "lang": "en" if random.random() > 0.3 else "hi",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "author_id": str(random.randint(100000, 999999)),
                "simulated": True,
            }

            await asyncio.sleep(1.0 / self.tweets_per_second)


class TwitterV2Stream:
    """
    Twitter API v2 filtered stream consumer.
    Requires TWITTER_BEARER_TOKEN env var.
    """

    STREAM_URL = "https://api.twitter.com/2/tweets/search/stream"
    RULES_URL = "https://api.twitter.com/2/tweets/search/stream/rules"
    FUEL_RULES = [
        {"value": "petrol shortage India lang:en OR lang:hi", "tag": "petrol_en"},
        {"value": "fuel crisis India pump queue", "tag": "fuel_crisis"},
        {"value": "पेट्रोल नहीं है", "tag": "petrol_hi"},
        {"value": "diesel shortage India pump empty", "tag": "diesel_en"},
    ]

    def __init__(self, bearer_token: str):
        self.bearer_token = bearer_token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.bearer_token}"}

    async def setup_rules(self) -> None:
        import httpx
        async with httpx.AsyncClient() as client:
            # Delete existing rules
            r = await client.get(self.RULES_URL, headers=self._headers())
            existing = r.json().get("data", [])
            if existing:
                ids = [rule["id"] for rule in existing]
                await client.post(
                    self.RULES_URL,
                    headers=self._headers(),
                    json={"delete": {"ids": ids}},
                )
            # Add new rules
            await client.post(
                self.RULES_URL,
                headers=self._headers(),
                json={"add": self.FUEL_RULES},
            )
        logger.info("Twitter stream rules configured")

    async def stream(self):
        import httpx
        await self.setup_rules()

        params = {
            "tweet.fields": "created_at,lang,author_id,text",
            "expansions": "author_id",
        }

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "GET", self.STREAM_URL, headers=self._headers(), params=params
            ) as response:
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        tweet = data.get("data", {})
                        if tweet:
                            yield {
                                "tweet_id": tweet.get("id"),
                                "text": tweet.get("text", ""),
                                "city": None,   # NLP will infer city
                                "lang": tweet.get("lang"),
                                "created_at": tweet.get("created_at"),
                                "author_id": tweet.get("author_id"),
                                "simulated": False,
                            }
                    except json.JSONDecodeError:
                        continue


async def run() -> None:
    settings = get_settings()
    configure_logging("social-producer")
    start_http_server(9106)

    producer = AIOKafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode(),
        acks=1,
    )
    await producer.start()

    if settings.SOCIAL_MODE == "twitter" and settings.TWITTER_BEARER_TOKEN:
        logger.info("Using Twitter API v2 stream")
        stream_source = TwitterV2Stream(settings.TWITTER_BEARER_TOKEN).stream()
    else:
        logger.info("Using tweet simulator")
        stream_source = TweetSimulator(panic_rate=0.35, tweets_per_second=3.0).stream()

    try:
        async for tweet in stream_source:
            await producer.send("raw.social.v1", value=tweet)
            tweets_published.labels(mode=settings.SOCIAL_MODE).inc()
            logger.debug("Tweet published", tweet_id=tweet.get("tweet_id"))
    finally:
        await producer.stop()


if __name__ == "__main__":
    asyncio.run(run())
