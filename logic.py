import time
import threading
import logging
import queue
from datetime import datetime, timezone
from eth_account import Account as EthAccount
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from hyperliquid.utils.types import Cloid
import numpy as np
from hyperliquid_monitor.monitor import HyperliquidMonitor
from hyperliquid_monitor.types import Trade
import signal

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Config:
    def __init__(self, token, min_price, max_price, bin_step, order_size, api_url, secret_key):
        self.token = token
        self.min_price = float(min_price)
        self.max_price = float(max_price)
        self.bin_step = float(bin_step)
        self.order_size = float(order_size)
        self.api_url = api_url
        self.secret_key = secret_key

class ExchangeClient:
    def __init__(self, config: Config):
        self.config = config
        self.account = EthAccount.from_key(config.secret_key)
        logger.info(f"Connected address: {self.account.address}")
        self.info = Info(config.api_url, skip_ws=True)
        self.exchange = Exchange(self.account, config.api_url)

    def get_close_price(self):
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        day_ms = 24 * 3600 * 1000
        start_ms = now_ms - 2 * day_ms
        print(f"Fetching candles for token: {self.config.token}")
        candles = self.info.candles_snapshot(self.config.token, "1d", start_ms, now_ms)
        print("Candles response:", candles)
        return float(candles[-1]["c"])

    def place_order(self, price: float, side: str, active_orders: dict):
        is_buy = side.lower() == "buy"
        cloid = Cloid.from_int(int(price * 10000) + (1 if is_buy else 2))
        price_key = round(float(price), 4)
        req = {"limit": {"tif": "Gtc"}, "clientOrderId": cloid}
        try:
            resp = self.exchange.order(
                self.config.token,
                is_buy,
                self.config.order_size,
                price,
                req
            )
            if resp.get("status") == "ok":
                active_orders[price_key] = side.lower()
                logger.info(f"Placed {side} order @ {price_key}")
                return True
        except Exception as e:
            logger.error(f"Failed to place {side} order @ {price}: {e}")
        return False

    def cancel_all(self):
        state = self.info.user_state(self.account.address)
        for order in state.get("orders", []):
            cloid_str = order.get("clientOrderId")
            if not cloid_str:
                continue
            cloid = Cloid.from_str(cloid_str)
            try:
                self.exchange.cancel_by_cloid(self.config.token, cloid)
                logger.info(f"Cancelled order with cloid: {cloid}")
            except Exception as e:
                logger.error(f"Failed to cancel order {cloid}: {e}")

class GridManager:
    def __init__(self, config: Config):
        self.config = config

    def build(self, last_close):
        levels = [round(p, 4) for p in np.arange(
            self.config.min_price, 
            self.config.max_price + self.config.bin_step/2, 
            self.config.bin_step
        )]
        closest = min(levels, key=lambda x: abs(x - round(last_close, 4)))
        levels.remove(closest)
        buys = [p for p in levels if p < closest]
        sells = [p for p in levels if p > closest]
        logger.info(f"Grid built: buys={buys}, sells={sells}")
        return buys, sells

class RunningBot:
    def __init__(self, config: Config):
        self.config = config
        self.client = ExchangeClient(config)
        self.active_orders = {}
        self.monitor = None
        self.thread = None
        self.running = False
        self.log_queue = queue.Queue()

    def log(self, message):
        logger.info(message)
        self.log_queue.put(message)

    def start(self):
        if threading.current_thread() == threading.main_thread():
            signal.signal(signal.SIGINT, self.handle_shutdown)

        if self.running:
            self.log("Bot is already running")
            return False

        try:
            self.log("Cancelling existing orders...")
            self.client.cancel_all()
            time.sleep(2)

            last_close = self.client.get_close_price()
            self.log(f"Last close price: {last_close}")
            buys, sells = GridManager(self.config).build(last_close)

            for p in sorted(buys):
                self.client.place_order(p, "buy", self.active_orders)
            for p in sorted(sells):
                self.client.place_order(p, "sell", self.active_orders)

            self.monitor = HyperliquidMonitor([self.client.account.address], callback=self.on_fill)
            self.thread = threading.Thread(target=self.monitor.start, daemon=True)
            self.thread.start()

            self.running = True
            self.log("Bot started successfully")
            return True
        except Exception as e:
            self.log(f"Error starting bot: {e}")
            return False

    def on_fill(self, trade: Trade):
        try:
            if trade.coin != self.config.token or trade.trade_type != "FILL":
                return

            price_key = round(trade.price, 4)
            self.log(f"Fill detected @ {price_key}")

            side = self.active_orders.pop(price_key, None)
            if not side:
                self.log(f"No active order found @ {price_key}")
                return

            self.log(f"Processing {side} fill @ {price_key}")

            if side == "buy":
                new_price = price_key + self.config.bin_step
                new_side = "sell"
            else:
                new_price = price_key - self.config.bin_step
                new_side = "buy"

            self.log(f"Placing {new_side} order @ {new_price}")

            if self.config.min_price <= new_price <= self.config.max_price:
                self.client.place_order(new_price, new_side, self.active_orders)
            else:
                self.log(f"Price {new_price} out of range - order skipped")
        except Exception as e:
            self.log(f"Fill processing error: {e}")

    def stop(self):
        if not self.running:
            return

        self.log("Stopping bot...")
        if self.monitor:
            self.monitor.stop()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5.0)
        self.client.cancel_all()
        self.running = False
        self.log("Bot stopped")

# Global tracking dictionary
running_bots = {}

def start_bot(bot_id, config_dict):
    try:
        print(f"Starting bot {bot_id} with config: {config_dict}")

        config = Config(
            token=config_dict['token_symbol'],
            min_price=config_dict['min_price'],
            max_price=config_dict['max_price'],
            bin_step=config_dict['bin_step'],
            order_size=config_dict['order_size'],
            api_url=constants.MAINNET_API_URL,
            secret_key=config_dict['private_key']
        )

        bot = RunningBot(config)
        started = bot.start()
        print(f"bot.start() returned: {started}")

        if started:
            running_bots[bot_id] = bot
            return True
        else:
            print(f"❌ Bot {bot_id} failed to start.")
            return False

    except Exception as e:
        print(f"❗ Exception while starting bot {bot_id}: {e}")
        return False

def stop_bot(bot_id):
    if bot_id in running_bots:
        bot = running_bots[bot_id]
        bot.stop()
        del running_bots[bot_id]
        return True
    return False

def get_bot_logs(bot_id):
    if bot_id in running_bots:
        bot = running_bots[bot_id]
        logs = []
        while not bot.log_queue.empty():
            logs.append(bot.log_queue.get())
        return logs
    return []