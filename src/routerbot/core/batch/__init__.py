"""Batch processing and async request queue.

Provides:
- OpenAI-compatible Batch API for bulk LLM request processing
- Async request queue with submit/poll pattern
- Priority queue system (high/medium/low)
- Background worker pool for job execution
- Batch progress tracking and spend aggregation
"""
