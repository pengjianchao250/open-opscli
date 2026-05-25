from pathlib import Path

from openpyxl import load_workbook

from opscli.seller_sprite.export.xlsx import export_rows_to_xlsx


def test_xlsx_export_writes_template_headers_without_notes(tmp_path: Path):
    output = tmp_path / "seller-sprite.xlsx"

    result = export_rows_to_xlsx(
        rows=[
            {
                "asin": "B00TEST123",
                "title": "Demo Product",
                "amazonChoice": True,
                "coupon": "5%",
            }
        ],
        output_path=output,
        scenario="competitor-lookup",
        site="US",
    )

    assert result.path == str(output)
    assert result.url == output.resolve().as_uri()
    assert output.exists()

    workbook = load_workbook(output)
    sheet = workbook.active
    assert sheet.cell(row=1, column=1).value == "ASIN"
    assert sheet.cell(row=1, column=6).value == "商品标题"
    assert sheet.cell(row=1, column=25).value == "Coupon"
    assert sheet.cell(row=1, column=54).value == "AC关键词"
    assert sheet.cell(row=2, column=1).value == "B00TEST123"
    assert sheet.cell(row=2, column=25).value == "5%"
    assert "Notes" not in workbook.sheetnames


def test_keyword_export_writes_unique_words_sheet(tmp_path: Path):
    output = tmp_path / "keyword.xlsx"

    export_rows_to_xlsx(
        rows=[{"keyword": "flashlight", "keywordCn": "手电筒", "amazonChoice": True}],
        output_path=output,
        scenario="keyword-miner",
        site="JP",
        params={"keyword": "flashlight"},
        high_frequency_rows=[{"keyword": "flashlight", "frequency": 10, "percentage": 0.5}],
    )

    workbook = load_workbook(output)
    assert workbook.sheetnames == ["JP-flashlight(1)_", "Unique Words"]
    unique_words = workbook["Unique Words"]
    assert unique_words.cell(row=1, column=1).value == "词语"
    assert unique_words.cell(row=2, column=1).value == "flashlight"
    assert unique_words.cell(row=2, column=2).value == 10
