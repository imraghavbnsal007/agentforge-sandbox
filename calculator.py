"""A tiny calculator module."""


def add(a, b):
    return a + b


def subtract(a, b):
    return a - b


def modulo(a, b):
    if b == 0:
        raise ValueError("Cannot compute modulo with zero divisor")
    return a % b
