import pandas as pd
import pandas_ta as ta
from binance.client import Client
from binance.enums import *
import time
import os
import json
from concurrent.futures import ThreadPoolExecutor

# Load Config
def load_config(config_file="config.json"):
    with open(config_file, "r") as file:
        return json.load(file)

config = load_config()

# Binance API keys from config
API_KEY = config["api_key"]
API_SECRET = config["api_secret"]

# Initialize Binance client
client = Client(API_KEY, API_SECRET)

# Parameters from config
symbols = config["symbols"]
RSI_PERIOD = config["rsi_period"]
TIME_INTERVAL = config["time_interval"]
TRAILING_STOP = config["trailing_stop_loss_percentage"]  # Percentage for trailing stop
PROFIT_TARGET = config["profit_target"]  # 2% profit target

# Helper Functions
def get_historical_klines(symbol, interval, limit=100):
    """Fetch historical price data."""
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    close_prices = [float(kline[4]) for kline in klines]
    return close_prices

def calculate_rsi(prices, period):
    """Calculate RSI."""
    df = pd.DataFrame(prices, columns=["close"])
    df["RSI"] = ta.rsi(df["close"], length=period)
    return df["RSI"].iloc[-1]

def calculate_bollinger_bands(prices, window=20, std_dev=2):
    """Calculate Bollinger Bands."""
    rolling_mean = prices.rolling(window=window).mean()
    rolling_std = prices.rolling(window=window).std()
    upper_band = rolling_mean + (rolling_std * std_dev)
    lower_band = rolling_mean - (rolling_std * std_dev)
    return upper_band.iloc[-1], lower_band.iloc[-1]

def get_price(symbol):
    """Get current price of the symbol."""
    ticker = client.get_symbol_ticker(symbol=symbol)
    return float(ticker["price"])

def check_if_symbol_in_balance(symbol):
    """Check how much of the symbol is in the account balance."""
    balance = client.get_account()['balances']
    for asset in balance:
        if asset['asset'] == symbol.replace('USDT', ''):
            return float(asset['free'])
    return 0

def place_buy_order(symbol, amount_usdt, rounding):
    """Place a market buy order."""
    price = get_price(symbol)
    quantity = amount_usdt / price
    if rounding == "floor":
        quantity = int(quantity)
    elif rounding == "round":
        quantity = round(quantity)
    
    print(f"Placing buy order: {quantity} {symbol} at price {price:.8f} USDT.")
    order = client.order_market_buy(symbol=symbol, quantity=quantity)
    write_purchase_price(symbol, price)
    return order

def place_sell_order(symbol, quantity):
    """Place a market sell order."""
    print(f"Selling {quantity} {symbol}!")
    order = client.order_market_sell(symbol=symbol, quantity=quantity)
    return order

def write_purchase_price(symbol, price):
    """Write the purchase price to a file."""
    with open(f"{symbol}_purchase_price.txt", "w") as file:
        file.write(f"{price:.8f}")

def read_purchase_price(symbol):
    """Read the purchase price from a file."""
    try:
        with open(f"{symbol}_purchase_price.txt", "r") as file:
            return float(file.read().strip())
    except FileNotFoundError:
        return None

def clear_purchase_price(symbol):
    """Clear the purchase price file."""
    if os.path.exists(f"{symbol}_purchase_price.txt"):
        os.remove(f"{symbol}_purchase_price.txt")

def dynamic_rsi_threshold(current_price, upper_band, lower_band):
    """Adjust RSI threshold dynamically based on Bollinger Bands."""
    if current_price > upper_band:
        return 30  # Conservative, buy only when RSI is very low
    elif current_price < lower_band:
        return 24  # Aggressive, more likely to buy
    else:
        return 27  # Default

def should_sell_with_trailing_stop(purchase_price, current_price, profit_target, trailing_stop):
    """Check if we should sell based on trailing stop."""
    target_price = purchase_price * (1 + profit_target / 100)
    trailing_price = current_price * (1 - trailing_stop / 100)
    return current_price >= target_price and trailing_price > purchase_price

# Core Logic for Each Symbol
def process_symbol(symbol_data):
    symbol = symbol_data["symbol"]
    rounding = symbol_data["rounding"]
    amount_usdt = symbol_data["amount_usdt"]

    try:
        balance = check_if_symbol_in_balance(symbol)
        current_price = get_price(symbol)
        purchase_price = read_purchase_price(symbol)
        balance_in_usd = balance * current_price

        # Print symbol header and details
        print(f"\n{'-' * 28} {symbol} {'-' * 28}")
        print(f"Current {symbol} balance: {balance:.2f}")
        print(f"Current price: {current_price:.8f} USDT")

        # Print purchase price if exists
        if purchase_price:
            print(f"Purchase price: {purchase_price:.8f} USDT")

        # Check balance and profit conditions
        if balance_in_usd > 1:
            profit_percentage = ((current_price - purchase_price) / purchase_price) * 100 if purchase_price else 0
            print(f"Profit: {profit_percentage:.2f}%")

            if purchase_price and profit_percentage >= PROFIT_TARGET:
                print(f"Target profit reached! Selling {symbol}.")
                place_sell_order(symbol, balance)
                clear_purchase_price(symbol)
            elif purchase_price and should_sell_with_trailing_stop(purchase_price, current_price, PROFIT_TARGET, TRAILING_STOP):
                print(f"Trailing stop triggered! Selling {symbol}.")
                place_sell_order(symbol, balance)
                clear_purchase_price(symbol)
            else:
                print("Profit target not reached yet.")
        else:
            print("Balance worth less than $1. Skipping profit check.")

        # Calculate RSI and dynamic RSI threshold
        prices = get_historical_klines(symbol, Client.KLINE_INTERVAL_5MINUTE)
        upper_band, lower_band = calculate_bollinger_bands(pd.Series(prices))
        rsi_threshold = dynamic_rsi_threshold(current_price, upper_band, lower_band)
        rsi = calculate_rsi(prices, RSI_PERIOD)

        print(f"RSI: {rsi:.2f} (Dynamic Buy Signal: {rsi < rsi_threshold}, Threshold: {rsi_threshold})")

        # Check buy conditions
        if rsi < rsi_threshold and balance_in_usd < 1:
            print(f"Conditions met! Buying {symbol}.")
            place_buy_order(symbol, amount_usdt, rounding)

        print("-" * 60)

    except Exception as e:
        print(f"Error processing {symbol}: {e}")

# Main Function
def main():
    while True:
        # Process each symbol one by one in the main loop, with a clear output
        for symbol_data in symbols:
            process_symbol(symbol_data)

        print("***********************************  ", time.strftime("%Y-%m-%d %H:%M:%S"), "  ***********************************")
        time.sleep(TIME_INTERVAL)

if __name__ == "__main__":
    main()
