"""Nodes f0-f6: thin wrappers around existing engine code."""
from .f0_intake import f0_intake
from .f1_crystallographer import f1_crystallographer
from .f2_path_planner import f2_path_planner
from .f3_runner import f3_runner
from .f4_reviewer import f4_reviewer
from .f5_analyst import f5_analyst
from .f6_skeptic import f6_skeptic

FUNCS = {"f0": f0_intake, "f1": f1_crystallographer, "f2": f2_path_planner, "f3": f3_runner, "f4": f4_reviewer, "f5": f5_analyst, "f6": f6_skeptic}
