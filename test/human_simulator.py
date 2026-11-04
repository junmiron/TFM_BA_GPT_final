"""Thin shim over lib/human_simulator.py.

The implementation lives in lib/ so app2.py and the headless roleplay harness
share one copy. This module exists so test/roleplay_e2e.py and the existing
tests keep their import path and can assert against the canned persona/brief.
"""

from lib.human_simulator import DEFAULT_PERSONA as PERSONA
from lib.human_simulator import HumanSimulator, build_human_simulator

TASK_BRIEF = (
    "Design a Laundry Shop Staff App (v1): a Windows PC server app plus an "
    "Android mobile app. Staff check in customer orders/bags, generate and "
    "print QR tags per order/bag, track item status (Received, In Cleaning, "
    "Quality Check, Ready for Pickup, Picked Up), assign shelf locations, scan "
    "QR to open records, check out orders, and manually backup/export data "
    "from the PC. PC works offline with a local DB (no sync); Android is "
    "online-only. Single Staff role with full access."
)

__all__ = ["HumanSimulator", "build_human_simulator", "PERSONA", "TASK_BRIEF"]

