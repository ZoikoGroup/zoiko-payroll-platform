"""Belgium: scripts/be_rebase_content_workbook moves a filled workbook onto another pack's row ids (offline).

The import matches rows by database id, which differs between databases (production vs the local pack the AI draft
was exported from). The rebase replaces ONLY the ids, matched by natural key, keeps every value / source / note, and
refuses (nothing written) on a row with no match or a duplicate key. SYNTHETIC workbooks only."""
import pytest


def _book(sheets: dict):
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(list(row))
    return wb


def _filled():
    return _book({
        "Scalar keys": [("rowId", "key", "employeeRatePct", "sourceDocumentId", "reviewerNote"),
                        ("11", "be_onss_employee_rate", "1.5", "SYN-SRC-1", "note kept"),
                        ("12", "be_rounding_withholding", None, "SYN-SRC-2", None)],
        "Parallel tolerances": [("rowId", "key", "flatAmount"), ("31", "be_parallel_tolerance_net", "0.01")],
        "Earning classification": [("rowId", "component", "obligation", "treatment"),
                                   ("41", "SALARY", "ONSS_EMPLOYEE", "INCLUDED"),
                                   ("42", "BONUS", "WITHHOLDING_EXCEPTIONAL", "INCLUDED")],
        "Slab keys": [("rowId", "key", "minAmount"), (None, "be_wht_exceptional_rule", "0")],
    })


def _target():
    return _book({
        "Scalar keys": [("rowId", "key"), ("70011", "be_rounding_withholding"), ("70010", "be_onss_employee_rate")],
        "Parallel tolerances": [("rowId", "key"), ("70031", "be_parallel_tolerance_net")],
        "Earning classification": [("rowId", "component", "obligation"), ("70142", "BONUS", "WITHHOLDING_EXCEPTIONAL"),
                                   ("70141", "SALARY", "ONSS_EMPLOYEE")],
    })


def _cells(wb, sheet):
    return [tuple(r) for r in wb[sheet].iter_rows(values_only=True)]


def test_only_the_ids_move_matched_by_natural_key():
    from scripts.be_rebase_content_workbook import be_rebase, be_target_ids

    filled = _filled()
    report = be_rebase(filled, be_target_ids(_target()))
    assert dict(report) == {"Scalar keys": 2, "Parallel tolerances": 1, "Earning classification": 2}
    assert _cells(filled, "Scalar keys")[1:] == [("70010", "be_onss_employee_rate", "1.5", "SYN-SRC-1", "note kept"),
                                                ("70011", "be_rounding_withholding", None, "SYN-SRC-2", None)]
    assert [r[0] for r in _cells(filled, "Earning classification")[1:]] == ["70141", "70142"]
    assert _cells(filled, "Slab keys")[1] == (None, "be_wht_exceptional_rule", "0")      # new rows untouched


def test_a_row_missing_from_the_target_refuses():
    from scripts.be_rebase_content_workbook import be_rebase, be_target_ids

    target = _target()
    target["Parallel tolerances"].delete_rows(2)
    with pytest.raises(SystemExit, match="be_parallel_tolerance_net"):
        be_rebase(_filled(), be_target_ids(target))


def test_a_duplicate_key_in_the_target_refuses():
    from scripts.be_rebase_content_workbook import be_target_ids

    target = _target()
    target["Scalar keys"].append(("70099", "be_onss_employee_rate"))
    with pytest.raises(SystemExit, match="twice"):
        be_target_ids(target)
