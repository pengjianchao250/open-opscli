from opscli.seller_sprite.api.keyword_research import parse_keyword_research_html


KEYWORD_RESEARCH_HTML = """
<table id="table-condition-search"><tbody>
  <tr>
    <td><input data-keyword="fathers day gifts"></td>
    <td>1</td>
    <td>
      <span data-keyword="fathers day gifts"><a>fathers day gifts</a></span>
      <br><span>父亲节礼物</span>
      <a href="https://www.amazon.com/dp/B0H6WT6Q8C?psc=1">商品1</a>
      <a href="https://www.amazon.com/dp/B0H4G1XJQD?psc=1">商品2</a>
    </td>
    <td></td><td></td>
    <td>10,124,360<br>337,479</td>
    <td>443,447<br>4.38%</td>
    <td>267,193,010<br>4,135,940</td>
    <td>500%</td>
    <td>6,347,161 (168%)<br>119,308 (254%)</td>
    <td>28.78%<br>1.29%</td>
    <td>1</td>
    <td>17.1%</td>
    <td>
      <input ppc-item-obj value="bidMin:1.03,bid:1.32,bidMax:1.6,exactPpc:1.27">
      $1.06<br>$1.27<br>$1.43
    </td>
    <td>$1.32<br>1.03 - 1.60</td>
    <td>6,465.1<br>1,566</td>
    <td>$19.99<br>20,341 (4.5)</td>
    <td></td>
  </tr>
  <tr><td colspan="20">
    所属类目:<br>Clothing, Shoes &amp; Jewelry(40%)<br>Home &amp; Kitchen(10%)<br>
    市场周期: 季节性市场(6月旺季)<br>SPR: 10,052<br>标题密度: 0
  </td></tr>
  <tr><td colspan="20"></td></tr>
</tbody></table>
"""


def test_keyword_research_html_parser_extracts_official_export_fields():
    rows = parse_keyword_research_html(KEYWORD_RESEARCH_HTML)

    assert rows == [
        {
            "keyword": "fathers day gifts",
            "keywordCn": "父亲节礼物",
            "searchRank": 1,
            "searches": 10124360,
            "searchesCr": 5.0,
            "purchases": 443447,
            "purchaseRate": 0.0438,
            "impressions": 267193010,
            "clicks": 4135940,
            "products": 1566,
            "supplyDemandRatio": 6465.1,
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
            "searchMonthCr": 1.68,
            "searchNearlyCv": 119308,
            "searchNearlyCr": 2.54,
            "departments": "Clothing, Shoes & Jewelry; Home & Kitchen",
            "gkDatas": [{"asin": "B0H6WT6Q8C"}, {"asin": "B0H4G1XJQD"}],
            "marketPeriod": "季节性市场(6月旺季)",
        }
    ]


def test_keyword_research_html_parser_preserves_title_density_na():
    html = KEYWORD_RESEARCH_HTML.replace("标题密度: 0", "标题密度: N/A")

    rows = parse_keyword_research_html(html)

    assert rows[0]["titleDensity"] == "N/A"
