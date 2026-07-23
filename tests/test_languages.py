from rekounts.languages import LANGUAGES, label_for_code, code_for_label, labels


def test_labels_list_order():
    assert labels() == ["Auto-detect", "English", "Tagalog"]


def test_code_for_label():
    assert code_for_label("Auto-detect") == "auto"
    assert code_for_label("English") == "en"
    assert code_for_label("Tagalog") == "tl"


def test_label_for_code():
    assert label_for_code("auto") == "Auto-detect"
    assert label_for_code("en") == "English"
    assert label_for_code("tl") == "Tagalog"


def test_unknown_code_falls_back_to_first_label():
    assert label_for_code("zz") == "Auto-detect"


def test_languages_mapping_shape():
    assert LANGUAGES == [("Auto-detect", "auto"), ("English", "en"), ("Tagalog", "tl")]
