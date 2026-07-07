from string_utils import count_words, reverse_string


def test_reverse_string():
    assert reverse_string("abc") == "cba"


def test_count_words():
    assert count_words("hello brave new world") == 4
