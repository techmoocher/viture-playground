"""headmusic — Phase 1 hardware foundation for a head-controlled music instrument (VITURE Pro).

Package layout (dependency direction is enforced by tests/test_architecture.py):

    types            shared data types (no dependencies)
    orientation      quaternion/Euler math, quality flags, neutral capture, processor (pure)
    tracking         consumer-side tracking gate (validity + staleness + neutral)
    recording        file schemas, writers, readers, denormalised export
    metrics          timing and stationary angular metrics
    acquisition      the ONLY package that touches hardware: SDK binding, capture shim, sources
    pipeline         wires a source to processor, gate, writers and live state
    viewer, cli      user-facing layers

Terminology: everything here is head(-mounted device) orientation relative to the SDK tracking
frame or to a neutral reference. It is never neck orientation relative to the torso.
"""

__version__ = "0.1.0"
