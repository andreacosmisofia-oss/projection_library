"""Domain layer (Layer 3 in ARCHITECTURE.md): pure business logic.

No FastAPI, no DB session here. Modules take and return plain Pydantic
models so they can be unit-tested in isolation.
"""
