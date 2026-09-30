"""黃金單位轉換工具"""
# 黃金單位轉換（以克為基準）
GOLD_UNIT_CONVERSIONS = {
    "盎司": 31.1035,  # 1 盎司 = 31.1035 克
    "g": 1.0,        # 1 克 = 1 克
    "錢": 3.75,      # 1 錢 = 3.75 克
    "兩": 37.5       # 1 兩 = 37.5 克 = 10 錢
}


def convert_to_grams(quantity: float, unit: str) -> float:
    """將數量轉換為克"""
    if unit not in GOLD_UNIT_CONVERSIONS:
        return quantity  # 預設為克
    return quantity * GOLD_UNIT_CONVERSIONS[unit]


def convert_from_grams(grams: float, target_unit: str) -> float:
    """從克轉換為目標單位"""
    if target_unit not in GOLD_UNIT_CONVERSIONS:
        return grams  # 預設為克
    return grams / GOLD_UNIT_CONVERSIONS[target_unit]


def convert_between_units(quantity: float, from_unit: str, to_unit: str) -> float:
    """在兩個單位之間轉換"""
    grams = convert_to_grams(quantity, from_unit)
    return convert_from_grams(grams, to_unit)
