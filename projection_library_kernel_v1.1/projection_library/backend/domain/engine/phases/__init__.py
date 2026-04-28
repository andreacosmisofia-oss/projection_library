"""Engine phases. M9.0 ships stubs; the actual phase logic lands in M9.1-M9.11."""

from backend.domain.engine.phases.e0_setup import phase_e0_setup
from backend.domain.engine.phases.e1_pl_driver import phase_e1
from backend.domain.engine.phases.e2_fa_da import phase_e2
from backend.domain.engine.phases.e3_nwc import phase_e3
from backend.domain.engine.phases.e3_1_ifrs15 import phase_e3_1
from backend.domain.engine.phases.e4_nfp import phase_e4
from backend.domain.engine.phases.e5_provisions_eb import phase_e5
from backend.domain.engine.phases.e6_tax_def_equity import phase_e6
from backend.domain.engine.phases.e7_pl_bottom import phase_e7
from backend.domain.engine.phases.e7_5_cit_nwc import phase_e7_5
from backend.domain.engine.phases.e8_cf_close import phase_e8

__all__ = [
    "phase_e0_setup",
    "phase_e1",
    "phase_e2",
    "phase_e3",
    "phase_e3_1",
    "phase_e4",
    "phase_e5",
    "phase_e6",
    "phase_e7",
    "phase_e7_5",
    "phase_e8",
]
