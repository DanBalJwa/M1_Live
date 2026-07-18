from core import generate_keywords, load_categories, parse_coupang_html


def main() -> None:
    categories = load_categories()
    assert categories, "categories.json could not be loaded"

    keywords = generate_keywords(["패션잡화", "신발", "신발용품", "깔창"], "", 8, categories)
    assert "안전화깔창" in keywords, keywords

    sample = '''
    <li class="search-product">
      <a href="/vp/products/1">
        <div class="name">테스트 기능성 깔창</div>
        <strong class="price-value">12,900</strong>
        <span class="rating-total-count">(321)</span>
        <span>로켓배송</span>
      </a>
    </li>
    '''
    result = parse_coupang_html("기능성깔창", sample)
    assert result["sampleCount"] == 1, result
    assert result["prices"]["avg"] == 12900, result
    assert result["reviews"]["total"] == 321, result
    assert result["delivery"]["rocketRatio"] == 100.0, result
    print("All local smoke tests passed.")


if __name__ == "__main__":
    main()
