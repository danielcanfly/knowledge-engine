from pathlib import Path


def test_m7_closeout_documents_pin_dry_run_and_next_gate() -> None:
    note = Path("docs/batches/m7-closeout-note.md").read_text(encoding="utf-8")
    evidence = Path("docs/batches/m7-evidence-index.md").read_text(encoding="utf-8")

    assert "28854451008" in note
    assert "open_source_review" in note
    assert "8132965719" in evidence
    assert "6ccc6cc9c8c88b96371982837e83aaa8dc909fbe643dec2f70407789e5f868d1" in evidence
    assert "no state-changing action occurred" in evidence
