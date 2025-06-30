import re
import numpy as np


class Brakets:
    """
    Sequential-and-parallel scheduler.

    ● If `personalized_input=True`  →  follow the user-supplied `cmd`.
    ● If `personalized_input=False` →  ignore `cmd` and auto-create one
      that lists *every* destination key once (“A,B,C,…”).

    Destinations may be Python lists **or** NumPy arrays.
    Channel names are treated case-insensitively.
    """

    # ------------------------------------------------------------------ #
    def __init__(self,
                 cmd: str | list = "A+B,C,D+E",
                 destinations: dict[str, list | np.ndarray] | None = None,
                 personalized_input: bool = True):

        # ---------- default demo table -------------------------------------
        if destinations is None:
            destinations = {'A': [100, 101],
                            'b': np.array([110]),        # note the lower-case
                            'C': [120, 121],
                            'd': np.array([130, 131]),
                            'E': [140],
                            'F': [150]}

        # ---------- normalise destination table (upper-case keys) ----------
        # Also coerce every value to a 1-D NumPy array for consistent length
        self.destinations = {k.upper(): np.asarray(v).ravel()
                             for k, v in destinations.items()}

        # ---------- build / parse the command ------------------------------
        if not personalized_input:                    # auto: A,B,C,…
            cmd_letters = ','.join(self.destinations.keys())
            cmd = self._parse_plus_comma(cmd_letters)
        elif isinstance(cmd, str):                   # user text → parse
            cmd = self._parse_plus_comma(cmd)

        # make every leaf upper-case so look-ups are case-insensitive
        self.cmd = self._upperise(cmd)

        # keep channel order exactly as it appears in the (now upper-case) dict
        self.all_channels = list(self.destinations.keys())

        # ---------- allocate output ----------------------------------------
        total_cols = self._length(self.cmd, parallel=False)
        self.output = np.full((len(self.all_channels), total_cols), np.nan)

        # ---------- fill ----------------------------------------------------
        self._unpack(self.cmd, start_col=0, parallel=False)

    # ====================================================================== #
    #  Helpers
    # ====================================================================== #
    @staticmethod
    def _parse_plus_comma(text: str) -> list:
        """'A+B , c , d+E' → [['A','B'], 'c', ['d','E']]   (whitespace ignored)"""
        out: list = []
        for chunk in re.split(r'\s*,\s*', text.strip()):
            if not chunk:
                continue
            parts = [p for p in re.split(r'\s*\+\s*', chunk) if p]
            out.append(parts if len(parts) > 1 else parts[0])
        return out

    @staticmethod
    def _upperise(node):
        """Recursively turn every string leaf into upper-case."""
        if isinstance(node, list):
            return [Brakets._upperise(sub) for sub in node]
        return node.upper()

    # ------------------------------------------------------------------ #
    def _val_len(self, values: np.ndarray) -> int:
        """Length of a 1-D NumPy array (already flattened)."""
        return values.size

    def _length(self, node, *, parallel: bool) -> int:
        """Recursive column count."""
        if isinstance(node, list):
            if parallel:            # inner list ⇒ parallel: max
                return max((self._length(sub, parallel=False) for sub in node),
                           default=0)
            # outer list ⇒ sequential: sum
            return sum(self._length(sub,
                                     parallel=isinstance(sub, list))
                       for sub in node)

        # single channel leaf
        vals = self.destinations.get(node, np.asarray([]))
        return self._val_len(vals)

    # ------------------------------------------------------------------ #
    def _unpack(self, node, *, start_col: int, parallel: bool):
        """Recursive writer into self.output."""
        if isinstance(node, list):
            if parallel:            # all branches share the same start_col
                for sub in node:
                    self._unpack(sub, start_col=start_col, parallel=False)
            else:                   # sequential: walk the cursor
                col = start_col
                for sub in node:
                    self._unpack(sub,
                                 start_col=col,
                                 parallel=isinstance(sub, list))
                    col += self._length(sub,
                                        parallel=isinstance(sub, list))
        else:                       # single channel
            vals = self.destinations.get(node)
            if vals is None or vals.size == 0:
                return                                # skip unknown / empty

            row = self.all_channels.index(node)
            n = self._val_len(vals)
            self.output[row, start_col:start_col + n] = vals

    # ====================================================================== #
    #  Convenience: pretty print
    # ====================================================================== #
    def __repr__(self):
        return f"Brakets(output=\n{self.output})"


# ------------------------------------------------------------------------- #
#  Demos
# ------------------------------------------------------------------------- #
if __name__ == "__main__":

    print("— personalised, mixed case in cmd & destinations —")
    demo1 = Brakets(cmd="a+B,CCC,c,d+e+F",
                    destinations={'a': [1, 2],
                                  'B': np.array([3]),
                                  'c': [4, 5],
                                  'E': [99],      # not referenced → ignored
                                  'f': np.array([6])},
                    personalized_input=True)
    print(demo1.output)

    print("\n— auto-generated cmd (personalised=False) —")
    demo2 = Brakets(cmd="",                        # ignored
                    destinations={'A': np.array([10, 11])
                                  },
                    personalized_input=False)
    print(demo2.output)
