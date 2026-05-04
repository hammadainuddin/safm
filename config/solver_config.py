"""Solver factory — swap GLPK/Gurobi/HiGHS here only. No LP code touches this directly."""

import os
from pyomo.opt import SolverFactory


SOLVER_OPTIONS: dict = {
    "glpk":   {"tmlim": 300},
    "gurobi": {"MIPGap": 0.001, "TimeLimit": 300, "OutputFlag": 0},
    "highs":  {"time_limit": 300},
    "cbc":    {"seconds": 300},
}


def get_solver(solver_name: str = None):
    """Return a configured Pyomo SolverFactory instance.

    Priority: explicit argument > SAF_SOLVER env var > glpk default.
    Raises RuntimeError if the solver is not available on this system.
    """
    name = solver_name or os.environ.get("SAF_SOLVER", "glpk")
    solver = SolverFactory(name)
    if not solver.available():
        raise RuntimeError(
            f"Solver '{name}' is not available. "
            "Install it or set the SAF_SOLVER environment variable to an available solver."
        )
    return solver, SOLVER_OPTIONS.get(name, {})
