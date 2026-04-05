// Backtest engine: vectorised event-driven backtester.

use numpy::PyReadonlyArray1;
use pyo3::prelude::*;
use pyo3::types::PyDict;

/// Run a vectorized backtest over price bars with signal array.
/// Returns dict with: total_return, sharpe_ratio, max_drawdown, win_rate, num_trades.
///
/// signals: 1 = buy, -1 = sell, 0 = hold
/// commission_bps: commission in basis points (e.g. 10.0 = 0.10%)
#[pyfunction]
pub fn run_backtest_fast(
    py: Python<'_>,
    close: PyReadonlyArray1<f64>,
    signals: PyReadonlyArray1<i32>,
    initial_capital: f64,
    commission_bps: f64,
) -> PyResult<Py<PyDict>> {
    let close = close.as_array();
    let signals = signals.as_array();
    let n = close.len();
    let commission_rate = commission_bps / 10000.0;

    let mut cash = initial_capital;
    let mut position: f64 = 0.0;
    let mut entry_price: f64 = 0.0;
    let mut equity_curve = vec![initial_capital; n];
    let mut trade_returns: Vec<f64> = Vec::new();

    for i in 0..n {
        equity_curve[i] = cash + position * close[i];
        match signals[i] {
            1 if position == 0.0 => {
                let cost = cash * commission_rate;
                let investable = cash - cost;
                position = investable / close[i];
                entry_price = close[i];
                cash = 0.0;
            }
            -1 if position > 0.0 => {
                let proceeds = position * close[i];
                let cost = proceeds * commission_rate;
                cash = proceeds - cost;
                trade_returns.push((close[i] - entry_price) / entry_price);
                position = 0.0;
            }
            _ => {}
        }
    }

    // Close any open position at the end (equity_curve already marks it correctly)
    if position > 0.0 {
        trade_returns.push((close[n - 1] - entry_price) / entry_price);
    }

    let total_return = (equity_curve[n - 1] - initial_capital) / initial_capital;

    // Daily returns for Sharpe calculation
    let mut daily_returns = vec![0.0f64; n];
    for i in 1..n {
        if equity_curve[i - 1] > 0.0 {
            daily_returns[i] = (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1];
        }
    }

    let mean_ret = daily_returns[1..].iter().sum::<f64>() / (n - 1) as f64;
    let variance = daily_returns[1..].iter().map(|r| (r - mean_ret).powi(2)).sum::<f64>()
        / (n - 2).max(1) as f64;
    let std_ret = variance.sqrt();
    let sharpe = if std_ret > 0.0 {
        (mean_ret / std_ret) * (252.0_f64).sqrt()
    } else {
        0.0
    };

    // Maximum drawdown
    let mut peak = equity_curve[0];
    let mut max_dd = 0.0f64;
    for &eq in &equity_curve {
        if eq > peak {
            peak = eq;
        }
        let dd = (peak - eq) / peak;
        if dd > max_dd {
            max_dd = dd;
        }
    }

    let wins = trade_returns.iter().filter(|&&r| r > 0.0).count();
    let num_trades = trade_returns.len();
    let win_rate = if num_trades > 0 { wins as f64 / num_trades as f64 } else { 0.0 };

    let dict = PyDict::new_bound(py);
    dict.set_item("total_return", total_return)?;
    dict.set_item("sharpe_ratio", sharpe)?;
    dict.set_item("max_drawdown", max_dd)?;
    dict.set_item("win_rate", win_rate)?;
    dict.set_item("num_trades", num_trades)?;
    Ok(dict.into())
}
