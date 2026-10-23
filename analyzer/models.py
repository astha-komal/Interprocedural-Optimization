"""
models.py
---------
Core data model: the Function class described in Review 2, Section 3.2
("The Function class stores the function name, return type, parameters
and body, along with direct calls, indirect calls, pointer assignments
and returned functions.")
"""
from dataclasses import dataclass, field


@dataclass
class Function:
    name: str
    return_type: str
    parameters: list          # list[(type, param_name)]
    body: str
    start_line: int = 0

    # populated later by discover_calls()
    direct_calls: set = field(default_factory=set)        # names called directly: foo(...)
    indirect_calls: set = field(default_factory=set)      # pointer variable names called: fp(...)
    pointer_assignments: dict = field(default_factory=dict)  # var_name -> set(target function names)
    returned_functions: set = field(default_factory=set)  # function names returned as values (return foo;)

    @property
    def param_count(self) -> int:
        return len(self.parameters)

    @property
    def line_count(self) -> int:
        return len([ln for ln in self.body.splitlines() if ln.strip()])

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "return_type": self.return_type,
            "parameters": [{"type": t, "name": n} for t, n in self.parameters],
            "line_count": self.line_count,
            "direct_calls": sorted(self.direct_calls),
            "indirect_calls": sorted(self.indirect_calls),
            "pointer_assignments": {k: sorted(v) for k, v in self.pointer_assignments.items()},
            "returned_functions": sorted(self.returned_functions),
        }
