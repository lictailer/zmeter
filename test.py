import re
import numpy as np


# -------------------------------------------
# helper: "A+B, C , D+E" → [['A','B'], 'C', ['D','E']]
# -------------------------------------------



class Brakets:
    """
    Sequential-and-parallel scheduler.

    Parameters
    ----------
    cmd : str | list
        A command such as ``"A+B,C,D+E"`` **or** the already-parsed
        list structure (e.g. ``[['A','B'],'C',['D','E']]``).
        *Ignored* when ``personalized_input=False``.
    destinations : dict[str, list[int]]
        Mapping from channel letters to their destination numbers.
    personalized_input : bool, default True
        • **True**  – follow the given ``cmd`` strictly (no extra rows/cols).  
        • **False** – ignore ``cmd`` and auto-create one that puts **all**
          destination keys in a single parallel group:  
          ``A+B+C+…``  →  ``[['A','B','C',…]]``.

    Notes
    -----
    * Letters appearing in the (effective) command but missing from
      ``destinations`` are silently skipped.
    * Extra keys in ``destinations`` are ignored when *personalised*;
      in the *auto* mode they are all included because the auto-cmd
      contains every key.
    """

    # -------------------------------------------------- construction
    def __init__(self,
                 cmd='A+B,C,D+E',
                 destinations=None,
                 personalized_input=True):

        # default table for quick demos
        if destinations is None:
            destinations = {'A': [100, 101],
                            'B': [110],
                            'C': [120, 121],
                            'D': [130, 131],
                            'E': [140],
                            'F': [150]}

        # --- determine which command string / structure to use ---------------
        if not personalized_input:           # auto-generate: A+B+…
            cmd_letters = ','.join(destinations.keys())
            cmd = self.parse_plus_comma(cmd_letters)          # → [['A','B',…]]
        elif isinstance(cmd, str):                       # user supplied text
            cmd = self.parse_plus_comma(cmd)

        self.cmd          = cmd
        self.destinations = destinations
        self.all_channels = list(destinations.keys())

        # --- allocate the output array strictly for *cmd* --------------------
        total_cols = self._length(cmd, parallel=False)
        self.output = np.full((len(self.all_channels), total_cols), np.nan)

        # --- fill it ---------------------------------------------------------
        self._unpack(cmd, start_col=0, parallel=False)

    # -------------------------------------------------- helpers
    def _length(self, node, *, parallel: bool) -> int:
        """recursive column count"""
        if isinstance(node, list):
            if parallel:    # inner list ⇒ parallel: take max
                return max((self._length(sub, parallel=False) for sub in node),
                           default=0)
            # outer list ⇒ sequential: sum
            return sum(self._length(sub,
                                     parallel=isinstance(sub, list))
                       for sub in node)
        # single letter
        return len(self.destinations.get(node, []))

    def _unpack(self, node, *, start_col: int, parallel: bool):
        """recursive writer"""
        if isinstance(node, list):
            if parallel:    # keep the same start_col for every branch
                for sub in node:
                    self._unpack(sub, start_col=start_col, parallel=False)
            else:           # sequential: advance cursor
                col = start_col
                for sub in node:
                    self._unpack(sub,
                                 start_col=col,
                                 parallel=isinstance(sub, list))
                    col += self._length(sub,
                                        parallel=isinstance(sub, list))
        else:               # single letter
            vals = self.destinations.get(node)
            if vals is None:
                return                   # skip missing channel
            row = self.all_channels.index(node)
            for val in vals:
                self.output[row, start_col] = val
                start_col += 1

    def parse_plus_comma(self, text: str):
        out = []
        for chunk in re.split(r'\s*,\s*', text.strip()):
            if not chunk:
                continue
            parts = [p for p in re.split(r'\s*\+\s*', chunk) if p]
            out.append(parts if len(parts) > 1 else parts[0])
        return out

# -------------------------------------------------- demos
if __name__ == "__main__":

    # 1️⃣ personalised = True → follow user cmd exactly
    demo1 = Brakets(cmd="A+B,CCC,C,D+E+F+HHH",
                    destinations={'A': [1, 2],
                                  'B': [3],
                                  'C': [4, 5],
                                  'D': [6]},          # D will be ignored
                    personalized_input=True)
    print("Personalised (strict cmd):\n", demo1.output)

    # 2️⃣ personalised = False → ignore cmd, include everyone (parallel group)
    demo2 = Brakets(cmd="(whatever)",
                    destinations={'A': [10, 11],
                                  'B': [12],
                                  'C': [13, 14],
                                  'D': [15]},
                    personalized_input=False)
    print("\nAuto cmd (all channels in series):\n", demo2.output)
