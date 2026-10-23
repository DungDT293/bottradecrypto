from decimal import Decimal

from storage.ledger import classify_position_outcome, summarize_events, weighted_average


def test_ledger_summary_identity_and_signed_funding():
    summary = summarize_events([
        {"event_type": "REALIZED_PNL", "amount": "10"},
        {"event_type": "FEE", "amount": "2"},
        {"event_type": "FUNDING_FEE", "amount": "-1"},
    ])
    assert summary.realized_pnl == Decimal("10")
    assert summary.commission_cost == Decimal("2")
    assert summary.funding_signed == Decimal("-1")
    assert summary.cash_flow == Decimal("0")
    assert summary.net_pnl == Decimal("7")
    assert summary.completeness == "FULL"


def test_position_outcome_and_dca_average():
    assert weighted_average([(Decimal("2"), Decimal("100")), (Decimal("3"), Decimal("110"))]) == Decimal("106")
    assert classify_position_outcome(Decimal("0")) == "BE"
    assert classify_position_outcome(Decimal("1")) == "WIN"
    assert classify_position_outcome(Decimal("-1")) == "LOSS"


def test_transfers_do_not_change_pnl():
    summary = summarize_events([
        {"event_type": "DEPOSIT", "amount": "5000"},
        {"event_type": "WITHDRAWAL", "amount": "-100"},
        {"event_type": "REALIZED_PNL", "amount": "2"},
    ])
    assert summary.cash_flow == Decimal("4900")
    assert summary.net_pnl == Decimal("2")


def test_empty_ledger_is_unknown():
    summary = summarize_events([])
    assert summary.completeness == "UNKNOWN"
    assert summary.net_pnl == Decimal("0")
