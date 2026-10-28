"""Small OpenAI helpers. Credentials stay out of prompts, settings, and logs."""

# Provider adapter, not a research algorithm (REPORT.md, component 2).
# The user's OpenAI requirement supplies generation and embedding services;
# choosing these models does not reproduce or inherit any paper's results.
# API references:
# https://developers.openai.com/api/docs/guides/structured-outputs#json-mode
# https://developers.openai.com/api/docs/guides/embeddings

import json
import math
import os
from pathlib import Path

from dotenv import dotenv_values
from openai import APIError, APIStatusError, OpenAI


GENERATION_MODEL = "gpt-6-luna"
EMBEDDING_MODEL = "text-embedding-3-small"
MAX_OUTPUT_TOKENS = 4096
ENV_FILE = Path(__file__).resolve().parent.parent / ".env.local"


class ModelError(ValueError):
    """The API was unavailable or returned unusable data."""


class ModelOutputError(ModelError):
    """A generated reply was malformed, but the service answered."""

    def __init__(self, message, response):
        super().__init__(message)
        self.response = response


def api_key():
    """Use an environment key first, then the repo's ignored local env file."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        try:
            key = (dotenv_values(ENV_FILE, interpolate=False).get("OPENAI_API_KEY") or "").strip()
        except (OSError, UnicodeError):
            raise ModelError("Cannot read .env.local; set OPENAI_API_KEY in the environment") from None
    if not key:
        raise ModelError("Set OPENAI_API_KEY in the environment or the repo's .env.local")
    return key


def connect(timeout):
    # Pin the destination so OPENAI_BASE_URL cannot redirect the repo's key.
    return OpenAI(api_key=api_key(), base_url="https://api.openai.com/v1",
                  timeout=timeout, max_retries=0)


def api_error(error):
    """Do not log SDK error bodies: authentication errors can contain key fragments."""
    if isinstance(error, APIStatusError):
        if error.status_code == 429:
            reasons = {
                "insufficient_quota": "API quota exhausted; check API billing and usage limits",
                "credit_balance_exhausted": "API credits exhausted; add credits in API billing",
                "organization_spend_limit_exceeded": "Organization spend limit reached; check API limits",
                "project_spend_limit_exceeded": "Project spend limit reached; check project settings",
                "organization_usage_limit_exceeded": "Organization usage limit reached; check API limits",
                "rate_limit_exceeded": "Temporary rate limit; wait before rerunning or pace API calls",
                "slow_down": "Request rate increased too quickly; wait before rerunning and pace API calls",
                "rate_limit_error": "Temporary rate limit; wait before rerunning or pace API calls",
            }
            # Match only known labels. Never echo an arbitrary code, type, or message.
            for label in [error.code, error.type]:
                if isinstance(label, str) and label in reasons:
                    return ModelError(f"OpenAI HTTP 429 ({label}); {reasons[label]}")
            return ModelError("OpenAI HTTP 429; rate limit or exhausted API quota; check API limits and billing")
        return ModelError(f"OpenAI HTTP {error.status_code}; check credentials, model access, and API limits")
    return ModelError("OpenAI request failed; check network access and --timeout")


# JSON mode is an API transport choice, not OntoEKG's Pydantic validation or
# proof of schema/semantic correctness. Downstream Python checks the records.
def ask_json(messages, model=GENERATION_MODEL, timeout=120):
    options = {}
    if model == GENERATION_MODEL:
        options["reasoning"] = {"effort": "none"}
    try:
        with connect(timeout) as client:
            reply = client.responses.create(
                model=model, input=messages, text={"format": {"type": "json_object"}},
                max_output_tokens=MAX_OUTPUT_TOKENS, store=False, **options,
            )
    except APIError as error:
        raise api_error(error) from None
    if reply.status == "failed":
        raise ModelError("OpenAI returned a failed response; check API service status")
    if reply.status != "completed":
        raise ModelOutputError("OpenAI response was incomplete", reply.model_dump(mode="json"))
    for item in reply.output:
        if item.type == "message":
            for part in item.content:
                if part.type == "refusal":
                    raise ModelOutputError("OpenAI declined this request", reply.model_dump(mode="json"))
    try:
        result = json.loads(reply.output_text)
    except (TypeError, ValueError):
        raise ModelOutputError("OpenAI did not return a JSON object", reply.model_dump(mode="json")) from None
    if not isinstance(result, dict):
        raise ModelOutputError("OpenAI output must be a JSON object", reply.model_dump(mode="json"))
    return result


# Local numerical/data-integrity checks, not a research quality evaluation.
def check_vectors(vectors, count):
    if not isinstance(vectors, list) or len(vectors) != count:
        raise ModelError("Embedding count does not match input count")
    size = None
    for vector in vectors:
        if not isinstance(vector, list) or not vector:
            raise ModelError("Empty embedding")
        if size is not None and len(vector) != size:
            raise ModelError("Embedding lengths differ")
        size = len(vector)
        for number in vector:
            if type(number) not in [int, float] or not math.isfinite(number):
                raise ModelError("Embedding contains an invalid number")
        length = math.hypot(*vector)
        if not math.isfinite(length) or length == 0:
            raise ModelError("Embedding length must be finite and nonzero")
    return vectors


def embed(texts, model=EMBEDDING_MODEL, timeout=120):
    if not texts:
        return []
    try:
        with connect(timeout) as client:
            reply = client.embeddings.create(model=model, input=texts, encoding_format="float")
    except APIError as error:
        raise api_error(error) from None
    items = sorted(reply.data, key=lambda item: item.index)
    if [item.index for item in items] != list(range(len(texts))):
        raise ModelError("Embedding indexes do not match inputs")
    return check_vectors([item.embedding for item in items], len(texts))


# Standard cosine similarity used by placement_context's DOLCE/ITSMO-inspired
# ranking ("Similarity computation approaches"):
# https://datascience.codata.org/articles/10.5334/dsj-2025-023
# This arithmetic is generic; no similarity cutoff proves semantic equivalence.
def cosine(first, second):
    check_vectors([first, second], 2)
    first_length = math.hypot(*first)
    second_length = math.hypot(*second)
    score = 0
    for a, b in zip(first, second):
        score += (a / first_length) * (b / second_length)
    return score
