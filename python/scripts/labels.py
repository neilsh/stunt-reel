"""The GitHub issue label names the scripts apply, search and map to Status.

One statement of every name a script uses, so a rename lands here and in
``docs/agents/triage-labels.md``, never as a scattered string literal. The scheme is prefixed:
``status:`` is the state an issue is in, ``type:`` what finishing it means, ``env:`` where it
can run, and ``area:`` the part of the project a recurring search follows
(``docs/agents/triage-labels.md``). Each prefix carries one color.

This module sits beside the scripts, not in the package, because ``project_sync.py`` runs on a
bare runner with no toolchain: importing ``stunt_reel`` would load its ``tac`` modules too, and
no package module needs a label name.
"""

from __future__ import annotations

#: Exactly one per open leaf issue; a session claims by swapping the last two.
NEEDS_TRIAGE = "status:needs-triage"
NEEDS_INFO = "status:needs-info"
READY_FOR_AGENT = "status:ready-for-agent"
READY_FOR_HUMAN = "status:ready-for-human"
IN_PROGRESS = "status:in-progress"

#: Beside the state label, on an issue or a pull request.
LOCAL_ONLY = "env:local-only"

#: Created by ``parity_agreement.py`` for a flag no open agreement issue covers.
CLASS_AGREEMENT = "area:class-agreement"
