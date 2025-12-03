from datetime import datetime
import csv
import io
from collections import defaultdict
from flask import Flask, request, render_template, send_file

app = Flask(__name__)

# -------------------------
# Trade / Matching logic
# -------------------------

class Trade:
    def __init__(self, date, order_type, ticker, total_amount, qty):
        self.date = date
        self.order_type = order_type
        self.ticker = ticker
        self.total_amount = total_amount
        self.qty = qty
        # protect division by zero just in case
        self.price = (total_amount / qty) if qty != 0 else 0.0
        self.original_qty = qty
        self.matched_qty = 0

class Match:
    def __init__(self, buy, sell, qty):
        self.buy = buy
        self.sell = sell
        self.qty = qty
        self.profit = (sell.price - buy.price) * qty
        self.holding_period_days = abs((sell.date - buy.date).days)
        self.is_wash_sale = self._check_wash_sale()

    def _check_wash_sale(self):
        return (
            (self.sell.date - self.buy.date).days <= 30 and
            (self.sell.date - self.buy.date).days > 0 and
            self.sell.price < self.buy.price
        )

    @property
    def is_short_term(self):
        return self.holding_period_days <= 365

    @property
    def is_long_term(self):
        return self.holding_period_days > 365

# Objective functions
def objective_profit(matches): return sum(m.profit for m in matches)
def objective_loss(matches): return -sum(m.profit for m in matches)
def objective_short_term_profit(matches): return sum(m.profit for m in matches if m.is_short_term)
def objective_long_term_profit(matches): return sum(m.profit for m in matches if m.is_long_term)
def objective_short_term_loss(matches): return -sum(m.profit for m in matches if m.is_short_term)
def objective_long_term_loss(matches): return -sum(m.profit for m in matches if m.is_long_term)
def objective_minimal_loss(matches): return abs(min(0, sum(m.profit for m in matches)))

strategy_map = {
    "1": ("最大化利润", objective_profit),
    "2": ("最大化亏损", objective_loss),
    "3": ("最大化短期利润", objective_short_term_profit),
    "4": ("最大化长期利润", objective_long_term_profit),
    "5": ("最大化短期亏损", objective_short_term_loss),
    "6": ("最大化长期亏损", objective_long_term_loss),
    "7": ("最小化亏损（靠近0）", objective_minimal_loss)
}

def apply_wash_sale(records):
    ticker_buys = defaultdict(list)
    wash_sales = []

    for record in records:
        date = record['date']
        type_ = record['type']
        ticker = record['ticker']
        total = record['total_amount']
        qty = record['qty']
        price = total / qty if qty != 0 else 0.0

        if type_ == 'buy':
            buy = {
                'date': date,
                'ticker': ticker,
                'qty': qty,
                'price': price,
                'orig_total': total,
                'adjusted': False
            }
            ticker_buys[ticker].append(buy)

        elif type_ == 'sell':
            for buy in ticker_buys[ticker]:
                days_diff = (date - buy['date']).days
                if 0 < days_diff <= 30 and not buy['adjusted']:
                    loss_per_unit = buy['price'] - price
                    if loss_per_unit > 0:
                        adjustment = loss_per_unit
                        old_price = buy['price']
                        buy['price'] += adjustment
                        buy['orig_total'] += adjustment * buy['qty']
                        buy['adjusted'] = True
                        wash_sales.append({
                            'ticker': ticker,
                            'sell_date': date,
                            'buy_date': buy['date'],
                            'adjustment_per_unit': adjustment,
                            'qty': buy['qty'],
                            'total_adjustment': adjustment * buy['qty'],
                            'old_price': old_price,
                            'new_price': buy['price']
                        })
                        break

    return wash_sales

def load_orders(filename):
    orders = []
    records = []

    with open(filename, mode='r', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            date = datetime.strptime(row['date'], "%Y-%m-%d").date()
            record = {
                'date': date,
                'type': row['type'],
                'ticker': row['ticker'],
                'total_amount': float(row['total amount']),
                'qty': int(row['qty'])
            }
            records.append(record)

    wash_sales = apply_wash_sale(records)

    for r in records:
        trade = Trade(r['date'], r['type'], r['ticker'], r['total_amount'], r['qty'])
        for ws in wash_sales:
            if trade.order_type == "buy" and trade.ticker == ws['ticker'] and trade.date == ws['buy_date']:
                trade.price = ws['new_price']
                trade.total_amount = trade.price * trade.qty
        orders.append(trade)

    return orders

def generate_matches(orders, strategy_func):
    buys = [o for o in orders if o.order_type == "buy"]
    sells = [o for o in orders if o.order_type == "sell"]
    buys.sort(key=lambda x: x.date)
    sells.sort(key=lambda x: x.date)

    all_matches = []
    for sell in sells:
        for buy in buys:
            if (
                sell.ticker == buy.ticker and
                sell.qty > 0 and
                buy.qty > 0 and
                buy.date <= sell.date
            ):
                match_qty = min(sell.qty, buy.qty)
                all_matches.append(Match(buy, sell, match_qty))

    result = []
    used_buy = set()
    used_sell = set()

    # sort by strategy evaluation on single-match basis (descending)
    for m in sorted(all_matches, key=lambda m: -strategy_func([m])):
        if m.buy in used_buy or m.sell in used_sell:
            continue
        qty = min(m.buy.qty, m.sell.qty)
        match = Match(m.buy, m.sell, qty)
        result.append(match)
        m.buy.qty -= qty
        m.sell.qty -= qty
        used_buy.add(m.buy)
        used_sell.add(m.sell)

    return result

def print_match_summary(matches):
    print("\n当前匹配记录：")
    short_term_profit = 0
    long_term_profit = 0
    for i, m in enumerate(matches):
        term = "短期" if m.is_short_term else "长期"
        wash_flag = "（洗售）" if m.is_wash_sale else ""
        print(f"{i + 1}: 股票: {m.sell.ticker}, 卖出: {m.sell.date}, 买入: {m.buy.date}, {term}{wash_flag}, 数量: {m.qty}, 收益: {m.profit:.2f}")
        if m.is_short_term:
            short_term_profit += m.profit
        else:
            long_term_profit += m.profit
    total_profit = short_term_profit + long_term_profit
    print(f"\n短期总利润: {short_term_profit:.2f}")
    print(f"长期总利润: {long_term_profit:.2f}")
    print(f"总利润: {total_profit:.2f}")

# -------------------------
# Flask web routes
# -------------------------

@app.route("/")
def index():
    # Make sure to create templates/index.html as previous instructions show.
    return render_template("index.html")


def load_orders_from_stream(stream):
    """
    stream: text-mode file-like object (e.g. io.StringIO)
    returns: list of Trade objects (with wash-sale adjustments applied)
    """
    reader = csv.DictReader(stream)
    records = []

    for row in reader:
        date = datetime.strptime(row['date'], "%Y-%m-%d").date()
        record = {
            'date': date,
            'type': row['type'],
            'ticker': row['ticker'],
            'total_amount': float(row['total amount']),
            'qty': int(row['qty'])
        }
        records.append(record)

    wash_sales = apply_wash_sale(records)
    orders = []

    for r in records:
        trade = Trade(r['date'], r['type'], r['ticker'], r['total_amount'], r['qty'])
        for ws in wash_sales:
            if trade.order_type == "buy" and trade.ticker == ws['ticker'] and trade.date == ws['buy_date']:
                trade.price = ws['new_price']
                trade.total_amount = trade.price * trade.qty
        orders.append(trade)

    return orders


@app.route("/process", methods=["POST"])
def process():
    file = request.files.get("file")
    strategy = request.form.get("strategy")

    if not file:
        return "No file uploaded", 400

    # decode bytes to text, create a text stream
    file_stream = io.StringIO(file.stream.read().decode("utf-8"))

    try:
        orders = load_orders_from_stream(file_stream)
    except Exception as e:
        return f"Error parsing uploaded CSV: {e}", 400

    # Pick strategy safely (default to "1")
    strategy = strategy or "1"
    if strategy not in strategy_map:
        strategy = "1"
    strategy_name, strategy_func = strategy_map[strategy]

    # Generate matches
    matches = generate_matches(orders, strategy_func)

    # Convert matches to a CSV file (in memory)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ticker", "sell_date", "buy_date",
        "term", "qty", "profit", "is_wash"
    ])
    for m in matches:
        writer.writerow([
            m.sell.ticker,
            m.sell.date.isoformat(),
            m.buy.date.isoformat(),
            "short" if m.is_short_term else "long",
            m.qty,
            f"{m.profit:.2f}",
            "yes" if m.is_wash_sale else "no"
        ])

    output.seek(0)
    mem_bytes = io.BytesIO(output.getvalue().encode("utf-8"))

    return send_file(
        mem_bytes,
        mimetype="text/csv",
        as_attachment=True,
        download_name="match_results.csv"
    )

# -------------------------
# Run server
# -------------------------

if __name__ == "__main__":
    # Run the Flask dev server (change host/port as needed)
    app.run(debug=True)