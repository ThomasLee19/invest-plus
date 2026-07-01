"""
Educational/reference finance content authoring script.

Writes a small curated set of hand-written, accurate educational articles
into data/educational/*.md, satisfying the corpus requirement for
reference content alongside filings and news. Content is authored directly
here (not scraped from Investopedia or similar sites, for ToS reasons).

Run:
    python scripts/fetch_educational.py

Output:
    data/educational/*.md
"""

from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "educational"

ARTICLES = {
    "pe_ratio.md": """# Price-to-Earnings (P/E) Ratio

The P/E ratio is a company's share price divided by its earnings per share
(EPS): `P/E = Price per Share / EPS`. It expresses how much investors are
willing to pay today for one dollar of the company's annual earnings.

There are two common variants:

- **Trailing P/E** uses EPS from the most recent 12 reported months.
- **Forward P/E** uses analysts' projected EPS for the next 12 months.

A high P/E can mean the market expects strong future earnings growth, or
that the stock is overvalued relative to its current earnings. A low P/E
can mean the stock is undervalued, or that the market expects earnings to
decline. P/E ratios are most meaningful when compared within the same
industry, since capital intensity, growth rates, and accounting practices
vary widely across sectors. A company with no earnings (a net loss) has no
meaningful P/E ratio, since the denominator is negative or zero.
""",
    "market_cap.md": """# Market Capitalization

Market capitalization ("market cap") is the total market value of a
company's outstanding shares: `Market Cap = Share Price x Shares
Outstanding`. It is a measure of company size as priced by the market,
distinct from revenue or total assets.

Common size buckets used by investors:

- **Mega-cap**: roughly $200 billion and above
- **Large-cap**: roughly $10 billion to $200 billion
- **Mid-cap**: roughly $2 billion to $10 billion
- **Small-cap**: roughly $300 million to $2 billion
- **Micro-cap**: below roughly $300 million

Market cap changes constantly as the share price moves, even though the
number of shares outstanding is relatively stable (it changes mainly
through buybacks, new share issuance, or stock splits). Market cap should
not be confused with **enterprise value**, which adjusts market cap for a
company's debt and cash to estimate the total cost of acquiring the
business.
""",
    "10k_vs_10q.md": """# 10-K vs. 10-Q Filings

Public companies registered with the U.S. Securities and Exchange
Commission (SEC) must periodically disclose their financial condition.
The two most common periodic reports are the 10-K and the 10-Q.

**Form 10-K** is the annual report. It is the most comprehensive filing a
company makes, including audited annual financial statements, a detailed
discussion of business operations and strategy, a full risk-factors
section, and management's discussion and analysis (MD&A) of financial
condition and results of operations.

**Form 10-Q** is the quarterly report, filed for each of the first three
fiscal quarters (no 10-Q is filed for the fourth quarter, since the 10-K
covers the full year). It contains unaudited financial statements and a
lighter MD&A section, and is intended to keep investors updated between
annual reports.

A related filing, **Form 8-K**, is event-driven rather than periodic: it
must be filed within four business days of a major corporate event (e.g.
an executive departure, an acquisition, or a significant agreement), and
is typically much shorter than a 10-K or 10-Q.
""",
    "balance_sheet.md": """# The Balance Sheet

The balance sheet is one of the three core financial statements. It shows
a company's financial position at a single point in time (a "snapshot"),
in contrast to the income statement and cash flow statement, which cover
a period of time.

It is built around the accounting equation:

`Assets = Liabilities + Shareholders' Equity`

- **Assets** are what the company owns or controls: cash, accounts
  receivable, inventory, property and equipment, and intangible assets
  like patents or goodwill. Assets are typically ordered by liquidity.
- **Liabilities** are what the company owes: accounts payable,
  short-term and long-term debt, and other obligations.
- **Shareholders' equity** is the residual claim on assets after
  liabilities are subtracted — what would theoretically be left for
  owners if all liabilities were paid off. It includes paid-in capital
  and retained earnings.

Because the equation must always balance, the balance sheet is a check on
internal consistency: total assets must equal total liabilities plus
equity at all times.
""",
    "income_statement.md": """# The Income Statement

The income statement (also called the "profit and loss statement" or
"P&L") reports a company's financial performance over a period of time —
a quarter or a fiscal year — in contrast to the balance sheet, which is a
single-point-in-time snapshot.

Its structure flows from revenue down to net income:

1. **Revenue** (or "net sales"): money earned from the company's core
   business activities.
2. **Cost of goods sold (COGS)**: direct costs of producing goods or
   services sold. Revenue minus COGS is **gross profit**.
3. **Operating expenses**: costs not directly tied to production, such
   as R&D, sales and marketing, and general administrative costs.
   Gross profit minus operating expenses is **operating income**
   (also called EBIT, earnings before interest and taxes).
4. **Non-operating items**: interest expense, interest income, and
   one-time gains or losses.
5. **Taxes**: income tax expense.
6. **Net income**: the "bottom line" — what remains after all expenses,
   interest, and taxes are subtracted from revenue.

Dividing net income by shares outstanding gives earnings per share (EPS),
one of the most widely watched per-share metrics.
""",
    "cash_flow_statement.md": """# The Cash Flow Statement

The cash flow statement reconciles net income (an accounting figure that
includes non-cash items like depreciation) with the actual cash a company
generated or used during a period. A company can be profitable on its
income statement while still running out of cash, which is why analysts
treat the cash flow statement as a check on earnings quality.

It is divided into three sections:

- **Operating activities**: cash generated or used by core business
  operations, starting from net income and adjusting for non-cash items
  (depreciation, amortization) and changes in working capital
  (receivables, payables, inventory).
- **Investing activities**: cash used for or generated by long-term
  investments, such as purchasing property and equipment (capital
  expenditures, or "capex"), or buying and selling securities and other
  businesses.
- **Financing activities**: cash flows between the company and its
  capital providers — issuing or repaying debt, issuing or repurchasing
  stock, and paying dividends.

**Free cash flow** (operating cash flow minus capital expenditures) is a
commonly used measure of the cash a company generates after the
reinvestment needed to maintain or grow the business.
""",
    "dividend_yield.md": """# Dividend Yield

Dividend yield expresses a company's annual dividend payment as a
percentage of its current share price: `Dividend Yield = Annual Dividend
per Share / Share Price`.

It is a measure of cash return relative to the price paid for a stock, and
is most often used to compare income-generating potential across stocks,
or against alternatives like bonds or savings accounts.

A few nuances matter when interpreting dividend yield:

- Yield rises when the share price falls (with the dividend held
  constant), so an unusually high yield can be a warning sign that the
  market expects a dividend cut, rather than a sign of an attractive
  income stream.
- Not all companies pay dividends — many growth-oriented companies
  reinvest all earnings back into the business instead.
- Dividend yield says nothing about total return on its own; it should be
  considered alongside share price appreciation/depreciation and the
  company's payout ratio (the share of earnings paid out as dividends),
  which indicates how sustainable the dividend is.
""",
    "eps.md": """# Earnings Per Share (EPS)

EPS measures the portion of a company's net income allocated to each
outstanding share of common stock: `EPS = Net Income / Weighted Average
Shares Outstanding`. It is one of the most widely cited metrics in
quarterly earnings reports and is a key input to the P/E ratio.

Two common variants:

- **Basic EPS** uses the actual weighted average number of shares
  outstanding during the period.
- **Diluted EPS** additionally accounts for securities that could convert
  into common stock — stock options, convertible bonds, and restricted
  stock units — and is therefore always less than or equal to basic EPS.
  Diluted EPS is generally considered the more conservative, realistic
  figure.

Companies also frequently report **adjusted EPS** (or "non-GAAP EPS"),
which excludes items management considers one-time or non-recurring (such
as restructuring charges or stock-based compensation). Adjusted EPS is
not standardized across companies, so it should be compared to GAAP EPS
rather than taken at face value.
""",
}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 60)
    print("Educational finance content authoring script")
    print(f"Output dir: {OUTPUT_DIR}")
    print("=" * 60)

    written = 0
    for filename, content in ARTICLES.items():
        dest_path = OUTPUT_DIR / filename
        if dest_path.exists():
            print(f"  [skip] {filename} already exists")
            continue
        dest_path.write_text(content, encoding="utf-8")
        print(f"  [ok] {filename}")
        written += 1

    print("\n" + "=" * 60)
    print(f"Done. Wrote {written} articles ({len(ARTICLES)} total)")
    print("=" * 60)


if __name__ == "__main__":
    main()
