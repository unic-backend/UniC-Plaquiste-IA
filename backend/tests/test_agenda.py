"""Agenda : lecture des dates et heures données par l'IA (heure de Dakar)."""
import pytest


@pytest.mark.parametrize("raw, iso", [
    ("2026-10-30 10:00", "2026-10-30T10:00:00+00:00"),
    ("2026-10-30 10h", "2026-10-30T10:00:00+00:00"),
    ("2026-10-30 9h30", "2026-10-30T09:30:00+00:00"),
    ("30/10/2026 10h30", "2026-10-30T10:30:00+00:00"),
    ("30/10/2026 10:30", "2026-10-30T10:30:00+00:00"),
])
def test_heures_ecrites_a_la_senegalaise(raw, iso):
    """« 10h », « 9h30 », « 30/10/2026 » : un rendez-vous n'est jamais refusé pour une question d'écriture (heure de Dakar)."""
    from app import agenda
    assert agenda.parse_dt(raw).isoformat() == iso
