from src.calculator import divide

def test_divide_by_zero():
    assert divide(10, 0) == 0

def test_divide_normal():
    assert divide(10, 2) == 5
