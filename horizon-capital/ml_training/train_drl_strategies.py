"""Phase 2: Train DRL strategy agents (PPO, A2C, DDPG) via stable-baselines3.

This is a Phase 2 upgrade. For MVP, rule-based strategies are used.

Usage:
    python train_drl_strategies.py --algo a2c --output artifacts/a2c_strategy.zip
"""

import argparse
from pathlib import Path

import gymnasium as gym
import numpy as np
import pandas as pd
import yfinance as yf

# Phase 2 imports (uncomment when ready):
# from stable_baselines3 import A2C, PPO, DDPG
# from stable_baselines3.common.vec_env import DummyVecEnv


class TradingEnv(gym.Env):
    """Custom Gymnasium environment for stock trading.

    Observation: 23 technical indicators + position info
    Action: continuous [-1, 1] where -1=full sell, 0=hold, 1=full buy
    Reward: portfolio return * risk adjustment
    """

    metadata = {"render_modes": []}

    def __init__(self, df: pd.DataFrame, initial_balance: float = 1_000_000):
        super().__init__()
        self.df = df.reset_index(drop=True)
        self.initial_balance = initial_balance

        # 23 indicators + balance + shares_held + unrealized_pnl
        self.observation_space = gym.spaces.Box(
            low=-np.inf, high=np.inf, shape=(26,), dtype=np.float32
        )
        # Continuous action: -1 (sell all) to 1 (buy all)
        self.action_space = gym.spaces.Box(
            low=-1.0, high=1.0, shape=(1,), dtype=np.float32
        )

        self.reset()

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.current_step = 0
        self.balance = self.initial_balance
        self.shares_held = 0
        self.net_worth = self.initial_balance
        self.prev_net_worth = self.initial_balance
        return self._get_observation(), {}

    def _get_observation(self):
        row = self.df.iloc[self.current_step]
        # Technical indicators (first 23 columns after OHLCV)
        indicators = row.values[:23].astype(np.float32)
        # Portfolio state
        portfolio = np.array([
            self.balance / self.initial_balance,
            self.shares_held * row.get("close", row.iloc[3]) / self.initial_balance,
            (self.net_worth - self.initial_balance) / self.initial_balance,
        ], dtype=np.float32)
        return np.concatenate([indicators, portfolio])

    def step(self, action):
        current_price = self.df.iloc[self.current_step].get("close", self.df.iloc[self.current_step].iloc[3])
        action_value = float(action[0])

        # Execute trade
        if action_value > 0.1:  # Buy
            shares_to_buy = int((self.balance * action_value) / current_price)
            cost = shares_to_buy * current_price
            self.balance -= cost
            self.shares_held += shares_to_buy
        elif action_value < -0.1:  # Sell
            shares_to_sell = int(self.shares_held * abs(action_value))
            revenue = shares_to_sell * current_price
            self.balance += revenue
            self.shares_held -= shares_to_sell

        # Update net worth
        self.prev_net_worth = self.net_worth
        self.net_worth = self.balance + self.shares_held * current_price

        # Reward: risk-adjusted return
        ret = (self.net_worth - self.prev_net_worth) / self.prev_net_worth
        reward = ret * 100  # Scale up

        # Next step
        self.current_step += 1
        terminated = self.current_step >= len(self.df) - 1
        truncated = False

        return self._get_observation(), reward, terminated, truncated, {}


def prepare_data(ticker: str, period: str = "5y") -> pd.DataFrame:
    """Fetch and prepare data with technical indicators."""
    from ta.trend import SMAIndicator, EMAIndicator, MACD as MACD_TA
    from ta.momentum import RSIIndicator, StochasticOscillator
    from ta.volatility import BollingerBands, AverageTrueRange

    df = yf.download(ticker, period=period, interval="1d", progress=False)
    df.columns = [c.lower() for c in df.columns]

    # Technical indicators
    df["sma_10"] = SMAIndicator(df["close"], window=10).sma_indicator()
    df["sma_20"] = SMAIndicator(df["close"], window=20).sma_indicator()
    df["sma_50"] = SMAIndicator(df["close"], window=50).sma_indicator()
    df["ema_10"] = EMAIndicator(df["close"], window=10).ema_indicator()
    df["ema_20"] = EMAIndicator(df["close"], window=20).ema_indicator()

    macd = MACD_TA(df["close"])
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_diff"] = macd.macd_diff()

    df["rsi_14"] = RSIIndicator(df["close"], window=14).rsi()

    bb = BollingerBands(df["close"], window=20, window_dev=2)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_width"] = bb.bollinger_wband()

    df["atr_14"] = AverageTrueRange(df["high"], df["low"], df["close"], window=14).average_true_range()

    stoch = StochasticOscillator(df["high"], df["low"], df["close"])
    df["stoch_k"] = stoch.stoch()
    df["stoch_d"] = stoch.stoch_signal()

    df["returns"] = df["close"].pct_change()
    df["vol_20"] = df["returns"].rolling(20).std() * np.sqrt(252)
    df["log_volume"] = np.log1p(df["volume"])

    # Normalize
    for col in df.columns:
        if col not in ["open", "high", "low", "close", "volume"]:
            mean = df[col].mean()
            std = df[col].std()
            if std > 0:
                df[col] = (df[col] - mean) / std

    df = df.dropna()
    return df


def main():
    parser = argparse.ArgumentParser(description="Train DRL strategy agent")
    parser.add_argument("--algo", choices=["a2c", "ppo", "ddpg"], default="a2c")
    parser.add_argument("--ticker", default="AAPL")
    parser.add_argument("--timesteps", type=int, default=1_000_000)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    if args.output is None:
        args.output = f"artifacts/{args.algo}_strategy.zip"

    print(f"Preparing data for {args.ticker}...")
    df = prepare_data(args.ticker)
    print(f"Data shape: {df.shape}")

    print(f"Creating trading environment...")
    env = TradingEnv(df)

    print(f"Training {args.algo.upper()} for {args.timesteps} timesteps...")
    print("NOTE: This is a Phase 2 feature. Uncomment stable-baselines3 imports to use.")
    print("For MVP, rule-based strategies are used instead.")

    # Phase 2: Uncomment to train
    # algos = {"a2c": A2C, "ppo": PPO, "ddpg": DDPG}
    # model = algos[args.algo]("MlpPolicy", env, verbose=1)
    # model.learn(total_timesteps=args.timesteps)
    # model.save(args.output)
    # print(f"Model saved to {args.output}")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Would save to {output_path} (Phase 2)")


if __name__ == "__main__":
    main()
