from datetime import datetime
import csv
from collections import defaultdict

class Trade:
    def __init__(self, date, order_type, ticker, total_amount, qty):
        self.date = date
        self.order_type = order_type
        self.ticker = ticker
        self.total_amount = total_amount
        self.qty = qty
        self.price = total_amount / qty
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
        price = total / qty

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

    with open(filename, mode='r') as file:
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

def adjust_match(matches, orders):
    print_match_summary(matches)
    try:
        choice = int(input("\n选择要调整的匹配编号：")) - 1
        m = matches[choice]
    except:
        print("输入无效。")
        return

    sell = m.sell
    m.buy.qty += m.qty
    sell.qty += m.qty

    candidates = [
        b for b in orders
        if b.order_type == "buy" and
           b.ticker == sell.ticker and
           b.qty > 0 and
           b.date <= sell.date  # 保证时间规则：买入发生在卖出前
    ]
    candidates.sort(key=lambda x: x.date)

    print(f"\n可匹配的买单（股票: {sell.ticker}）：")
    for idx, b in enumerate(candidates):
        print(f"{idx + 1}: 日期: {b.date}, 剩余: {b.qty}, 价格: {b.price:.2f}")

    try:
        new_choice = int(input("选择新的买单编号：")) - 1
        new_qty = int(input("输入匹配数量："))
        new_buy = candidates[new_choice]
    except:
        print("输入无效。")
        return

    new_qty = min(new_qty, sell.qty, new_buy.qty)
    new_match = Match(new_buy, sell, new_qty)
    new_buy.qty -= new_qty
    sell.qty -= new_qty
    matches[choice] = new_match
    print("匹配已更新。")

def main():
    filename = input("请输入交易记录文件名（例如 orders.csv）：").strip()
    try:
        orders = load_orders(filename)
    except FileNotFoundError:
        print(f"文件未找到：{filename}")
        return
    except Exception as e:
        print(f"读取文件出错：{e}")
        return

    print("\n请选择自动匹配策略：")
    for k, (name, _) in strategy_map.items():
        print(f"{k}: {name}")
    selected = input("请输入对应数字：").strip()

    if selected not in strategy_map:
        print("无效选择，默认使用最大化利润。")
        selected = "1"

    strategy_name, strategy_func = strategy_map[selected]
    print(f"\n选择策略：{strategy_name}")

    matches = generate_matches(orders, strategy_func)
    print_match_summary(matches)

    while True:
        adjust = input("\n是否继续手动调整匹配？(y/n): ").strip().lower()
        if adjust == 'y':
            adjust_match(matches, orders)
        else:
            break

    print("\n最终匹配结果：")
    print_match_summary(matches)

if __name__ == "__main__":
    main()