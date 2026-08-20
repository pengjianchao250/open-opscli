from opscli.keepa.category_formatter import format_category_export


def test_category_formatter_splits_arrays_and_derives_readable_fields():
    formatted = format_category_export(
        [
            {
                "domainId": 1,
                "catId": 281052,
                "parent": 502394,
                "name": "Digital Cameras",
                "avgBuyBox": 25499,
                "avgRating": 42,
                "children": [3109924011, 7242008011],
                "relatedCategories": [672123011],
                "topBrands": ["Sony", "Canon"],
            }
        ],
        site="US",
    )

    category = formatted.categories[0]
    assert category["catId"] == "281052"
    assert category["parent"] == "502394"
    assert category["avgBuyBoxAmount"] == 254.99
    assert category["avgRatingStars"] == 4.2
    assert category["childrenCount"] == 2
    assert "children" not in category
    assert formatted.children[0] == {
        "catId": "281052",
        "childIndex": 0,
        "childCategoryId": "3109924011",
    }
    assert formatted.related[0]["relatedCategoryId"] == "672123011"
    assert formatted.brands[1]["brand"] == "Canon"


def test_category_formatter_marks_blank_category_without_url():
    formatted = format_category_export(
        [{"domainId": 1, "catId": 9223372036854775807, "name": "?"}],
        site="US",
    )

    assert formatted.categories[0]["isBlankCategory"] is True
    assert formatted.categories[0]["categoryUrl"] is None


def test_category_formatter_outputs_lookup_parent_objects_separately():
    formatted = format_category_export(
        [{"domainId": 1, "catId": 281052, "name": "Digital Cameras"}],
        site="US",
        parent_rows=[
            {
                "domainId": 1,
                "catId": 502394,
                "name": "Camera & Photo",
                "children": [281052],
            }
        ],
    )

    assert formatted.parents[0]["catId"] == "502394"
    assert formatted.extra_sheets()["category_parents"][0]["name"] == "Camera & Photo"
    assert formatted.parent_children[0]["childCategoryId"] == "281052"
