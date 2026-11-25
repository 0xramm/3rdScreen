"""Smoke tests for the pure logic in app.py. Run directly: python test_app.py"""
from app import compute_grid_layout, serialize_state, Source


def test_grid_layout_covers_canvas_with_no_gaps():
    for n in range(1, 6):
        rects = compute_grid_layout(1920, 1080, n)
        assert len(rects) == n
        max_x = max(x + w for x, y, w, h in rects)
        max_y = max(y + h for x, y, w, h in rects)
        assert max_x == 1920, f"n={n} right edge {max_x}"
        assert max_y == 1080, f"n={n} bottom edge {max_y}"
        for x, y, w, h in rects:
            assert x >= 0 and y >= 0 and w > 0 and h > 0


def test_grid_layout_empty():
    assert compute_grid_layout(1920, 1080, 0) == []


def test_serialize_state_roundtrip():
    mon = {"left": 0, "top": 0, "width": 1920, "height": 1080}
    sources = [Source("Display 1", mon, 10, 20, 300, 400)]
    data = serialize_state(1920, 1080, sources)
    assert data["output_w"] == 1920
    assert data["output_h"] == 1080
    assert data["sources"][0] == {
        "name": "Display 1", "mon_info": mon, "x": 10, "y": 20, "w": 300, "h": 400,
    }


if __name__ == "__main__":
    test_grid_layout_covers_canvas_with_no_gaps()
    test_grid_layout_empty()
    test_serialize_state_roundtrip()
    print("OK")
