import pytest

from calculator import add, modulo, subtract


def test_add():
    assert add(2, 3) == 5


def test_add_negative():
    assert add(-1, -2) == -3


def test_subtract():
    assert subtract(5, 3) == 2


def test_modulo():
    assert modulo(10, 3) == 1


def test_modulo_negative():
    assert modulo(-10, 3) == 2


def test_modulo_zero_division():
    with pytest.raises(ValueError):
        modulo(5, 0)
