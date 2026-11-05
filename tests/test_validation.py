import pytest

from app.validation import ApiError, parse_point, parse_polygon, parse_radius

SQUARE = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}


def test_point_ok_and_range():
    assert parse_point({"lat": "39.9", "lon": "-75.1"}) == (39.9, -75.1)
    for bad in ({"lat": "91", "lon": "0"}, {"lat": "x", "lon": "0"}, {"lon": "0"}):
        with pytest.raises(ApiError):
            parse_point(bad)


def test_radius_default_and_limits():
    assert parse_radius({}) == 1000.0
    with pytest.raises(ApiError):
        parse_radius({"radius": "999999"})


def test_polygon_validation():
    assert parse_polygon(SQUARE) == SQUARE
    with pytest.raises(ApiError):
        parse_polygon({"type": "Point", "coordinates": [0, 0]})
    open_ring = {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [2, 2]]]}
    with pytest.raises(ApiError):
        parse_polygon(open_ring)
    with pytest.raises(ApiError):
        parse_polygon({"type": "Polygon", "coordinates": [[[0, 200], [0, 1], [1, 1], [0, 200]]]})
