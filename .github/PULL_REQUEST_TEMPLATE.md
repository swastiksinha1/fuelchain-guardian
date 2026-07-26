## Summary
Brief description of what this PR does.

## Type of Change
- [ ] Bug fix
- [ ] New feature / module
- [ ] Refactor
- [ ] Documentation
- [ ] Infrastructure / DevOps

## Checklist
- [ ] Unit tests added / updated (`pytest tests/test_unit.py -v` passes)
- [ ] Type hints added to all new Python functions
- [ ] Structured logging (`structlog`) used instead of `print()`
- [ ] Prometheus metrics added for new counters/latency
- [ ] No secrets committed (`.env` not included)
- [ ] Docker Compose `up` still works end-to-end

## Kafka Topics Affected
List any new or changed Kafka topics and their schema changes.

## Database Schema Changes
Alembic migration added? (Required for any model changes)
