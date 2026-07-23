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


def test_keyword_research_export_matches_official_workbook_contract(tmp_path: Path):
    output = tmp_path / "keyword-research.xlsx"
    row = {
        "keyword": "fathers day gifts",
        "keywordCn": "父亲节礼物",
        "searchRank": 1,
        "searches": 10124360,
        "searchesCr": 4.9992,
        "purchases": 443447,
        "purchaseRate": 0.0438,
        "impressions": 267193010,
        "clicks": 4135940,
        "products": 1566,
        "supplyDemandRatio": 6465.11,
        "spr": 10052,
        "titleDensity": 0,
        "monopolyClickRate": 0.2878,
        "cvsShareRate": 0.0129,
        "goodsValue": 0.171,
        "avgPrice": "$19.99",
        "avgReviews": 20341,
        "avgRating": 4.5,
        "bidMin": 1.03,
        "bid": 1.32,
        "bidMax": 1.6,
        "searchMonthCv": 6347161,
        "searchMonthCr": 1.6804,
        "searchNearlyCv": 119308,
        "searchNearlyCr": 2.5434,
        "departments": "Clothing, Shoes & Jewelry; Home & Kitchen; Garden & Outdoor",
        "gkDatas": [{"asin": "B0H6WT6Q8C"}, {"asin": "B0H4G1XJQD"}],
    }

    export_rows_to_xlsx(
        rows=[row],
        output_path=output,
        scenario="keyword-research",
        site="US",
        period="2026-06",
    )

    workbook = load_workbook(output)
    assert workbook.sheetnames == ["Keywords(1)", "Notes"]
    sheet = workbook["Keywords(1)"]
    assert [cell.value for cell in sheet[1]] == [
        "关键词", "关键词翻译", "ABA排名", "月搜索量", "搜索增长率", "月购买量", "购买率",
        "展示量", "点击量", "商品数", "需供比", "SPR", "标题密度", "点击总占比", "转化总占比",
        "货流值", "均价", "评分数", "评分值", "PPC竞价-最低($)", "PPC竞价-推荐($)",
        "PPC竞价-最高($)", "同比增长值", "同比增长率", "近3个月增长值", "近3个月增长率",
        "所属类目", "前10ASIN",
    ]
    assert sheet.freeze_panes == "A2"
    assert sheet["A1"].fill.fgColor.rgb == "FFE98A00"
    assert sheet["A1"].font.name == "Calibri"
    assert sheet["A1"].font.sz == 10
    assert sheet["A1"].font.bold is False
    assert sheet.column_dimensions["A"].width == 28
    assert sheet.column_dimensions["AB"].width == 120
    assert sheet["G2"].value == 0.0438
    assert sheet["Q2"].value == "$19.99"
    assert sheet["AB2"].value == "B0H6WT6Q8C,B0H4G1XJQD"
    assert workbook["Notes"]["A1"].value == "卖家精灵官网：https://www.sellersprite.com"
