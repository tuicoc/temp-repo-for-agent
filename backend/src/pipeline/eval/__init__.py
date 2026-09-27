"""The offline test: scenarios through the real graph. ``docs/design.md`` section 9, figure H.

Its own composition root. It reads the organisers' scenario format as is,
drives the hot graph turn by turn with the scenario's written customer turns
(the ASR version when there is one), runs ``after_call`` synchronously
between calls (call 2 needs what call 1 wrote), moves the virtual clock by
``days_later``, resets the organisers' mock per scenario, and writes one
trace line per turn in their schema. The same run with the memory switch
off is the baseline.

- :mod:`.runner`: ``run`` (one command), ``compare`` (refuses different
  manifests), ``replay`` (no API call).

Status: not built.
"""
