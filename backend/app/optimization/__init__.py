"""Optimisation layer.

:class:`ClassicalBaseline` is implemented. The QUBO builder, obfuscator, QAOA
solver and solution mapper are Phase 3/4 -- their interfaces and encodings are
specified in their module docstrings.
"""

from .classical_baseline import ClassicalBaseline, OptimizationOutcome
from .qubo_builder import QuboProblem, QUBOBuilder

__all__ = ["ClassicalBaseline", "OptimizationOutcome", "QuboProblem", "QUBOBuilder"]
