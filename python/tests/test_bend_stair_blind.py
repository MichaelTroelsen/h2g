"""The bend column sums siddump's printed bends only; a pattern-stair step
is a tie, so it is invisible to `bend` and visible to `travel`. The
Dimension and the report must say so."""
import fidelity


def test_bend_dimension_declares_stair_blindness():
    d = next(x for x in fidelity.DIMENSIONS if x.key == "bend_ratio")
    assert "BLIND to a pattern-stair" in d.of
    assert "travel" in d.of


def test_report_bend_entry_declares_stair_blindness():
    import inspect
    src = inspect.getsource(fidelity)
    assert "Blind to pattern-stair steps" in src
