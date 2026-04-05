// Feature engine: high-performance technical indicator computations via PyO3 + numpy.

use numpy::ndarray::Array1;
use numpy::{IntoPyArray, PyArray1, PyReadonlyArray1};
use pyo3::prelude::*;
use pyo3::types::PyDict;

/// Compute RSI using Wilder's smoothing. Returns NaN for first `period` values.
#[pyfunction]
pub fn compute_rsi(py: Python<'_>, prices: PyReadonlyArray1<f64>, period: usize) -> Py<PyArray1<f64>> {
    let prices = prices.as_array();
    let n = prices.len();
    let mut rsi = Array1::<f64>::from_elem(n, f64::NAN);
    if n <= period {
        return rsi.into_pyarray_bound(py).into();
    }

    let mut gains = vec![0.0f64; n];
    let mut losses = vec![0.0f64; n];
    for i in 1..n {
        let change = prices[i] - prices[i - 1];
        if change > 0.0 {
            gains[i] = change;
        } else {
            losses[i] = -change;
        }
    }

    let mut avg_gain: f64 = gains[1..=period].iter().sum::<f64>() / period as f64;
    let mut avg_loss: f64 = losses[1..=period].iter().sum::<f64>() / period as f64;

    rsi[period] = if avg_loss == 0.0 {
        100.0
    } else {
        100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
    };

    let period_f = period as f64;
    for i in (period + 1)..n {
        avg_gain = (avg_gain * (period_f - 1.0) + gains[i]) / period_f;
        avg_loss = (avg_loss * (period_f - 1.0) + losses[i]) / period_f;
        rsi[i] = if avg_loss == 0.0 {
            100.0
        } else {
            100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
        };
    }
    rsi.into_pyarray_bound(py).into()
}

/// Compute MACD. Returns (macd_line, signal_line, histogram).
#[pyfunction]
pub fn compute_macd(
    py: Python<'_>,
    prices: PyReadonlyArray1<f64>,
    fast: usize,
    slow: usize,
    signal: usize,
) -> (Py<PyArray1<f64>>, Py<PyArray1<f64>>, Py<PyArray1<f64>>) {
    let prices = prices.as_array();
    let n = prices.len();
    let ema_fast = ema(&prices.to_vec(), fast);
    let ema_slow = ema(&prices.to_vec(), slow);

    let mut macd_line = Array1::<f64>::from_elem(n, f64::NAN);
    for i in 0..n {
        if !ema_fast[i].is_nan() && !ema_slow[i].is_nan() {
            macd_line[i] = ema_fast[i] - ema_slow[i];
        }
    }

    let signal_arr = ema(&macd_line.to_vec(), signal);
    let signal_line = Array1::from_vec(signal_arr);

    let mut histogram = Array1::<f64>::from_elem(n, f64::NAN);
    for i in 0..n {
        if !macd_line[i].is_nan() && !signal_line[i].is_nan() {
            histogram[i] = macd_line[i] - signal_line[i];
        }
    }

    (
        macd_line.into_pyarray_bound(py).into(),
        signal_line.into_pyarray_bound(py).into(),
        histogram.into_pyarray_bound(py).into(),
    )
}

/// Compute Bollinger Bands. Returns (upper, middle, lower).
#[pyfunction]
pub fn compute_bollinger(
    py: Python<'_>,
    prices: PyReadonlyArray1<f64>,
    period: usize,
    num_std: f64,
) -> (Py<PyArray1<f64>>, Py<PyArray1<f64>>, Py<PyArray1<f64>>) {
    let prices = prices.as_array();
    let n = prices.len();
    let mut upper = Array1::<f64>::from_elem(n, f64::NAN);
    let mut middle = Array1::<f64>::from_elem(n, f64::NAN);
    let mut lower = Array1::<f64>::from_elem(n, f64::NAN);

    for i in (period - 1)..n {
        let window = &prices.as_slice().unwrap()[i + 1 - period..=i];
        let mean: f64 = window.iter().sum::<f64>() / period as f64;
        let variance: f64 = window.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / period as f64;
        let std = variance.sqrt();
        middle[i] = mean;
        upper[i] = mean + num_std * std;
        lower[i] = mean - num_std * std;
    }
    (
        upper.into_pyarray_bound(py).into(),
        middle.into_pyarray_bound(py).into(),
        lower.into_pyarray_bound(py).into(),
    )
}

/// Compute all indicators at once. Returns Python dict of name -> numpy array.
#[pyfunction]
pub fn compute_all_indicators(
    py: Python<'_>,
    close: PyReadonlyArray1<f64>,
    high: PyReadonlyArray1<f64>,
    low: PyReadonlyArray1<f64>,
    volume: PyReadonlyArray1<f64>,
) -> PyResult<Py<PyDict>> {
    let close_arr = close.as_array();
    let high_arr = high.as_array();
    let low_arr = low.as_array();
    let _volume_arr = volume.as_array(); // reserved for future OBV/VWAP indicators
    let n = close_arr.len();
    let dict = PyDict::new_bound(py);

    dict.set_item("rsi", compute_rsi(py, close.clone(), 14))?;
    let (macd, signal, hist) = compute_macd(py, close.clone(), 12, 26, 9);
    dict.set_item("macd", macd)?;
    dict.set_item("macd_signal", signal)?;
    dict.set_item("macd_hist", hist)?;
    let (bb_upper, bb_middle, bb_lower) = compute_bollinger(py, close.clone(), 20, 2.0);
    dict.set_item("bb_upper", bb_upper)?;
    dict.set_item("bb_middle", bb_middle)?;
    dict.set_item("bb_lower", bb_lower)?;

    // ATR (Average True Range, period=14)
    let mut atr = Array1::<f64>::from_elem(n, f64::NAN);
    if n > 14 {
        let mut tr = vec![0.0f64; n];
        for i in 1..n {
            let hl = high_arr[i] - low_arr[i];
            let hc = (high_arr[i] - close_arr[i - 1]).abs();
            let lc = (low_arr[i] - close_arr[i - 1]).abs();
            tr[i] = hl.max(hc).max(lc);
        }
        atr[14] = tr[1..=14].iter().sum::<f64>() / 14.0;
        for i in 15..n {
            atr[i] = (atr[i - 1] * 13.0 + tr[i]) / 14.0;
        }
    }
    dict.set_item("atr", atr.into_pyarray_bound(py))?;

    // SMAs and EMAs
    let close_vec = close_arr.to_vec();
    dict.set_item("sma_20", Array1::from_vec(sma(&close_vec, 20)).into_pyarray_bound(py))?;
    dict.set_item("sma_50", Array1::from_vec(sma(&close_vec, 50)).into_pyarray_bound(py))?;
    dict.set_item("ema_12", Array1::from_vec(ema(&close_vec, 12)).into_pyarray_bound(py))?;
    dict.set_item("ema_26", Array1::from_vec(ema(&close_vec, 26)).into_pyarray_bound(py))?;

    Ok(dict.into())
}

// --- internal helpers (not exposed to Python) ---

fn ema(data: &[f64], period: usize) -> Vec<f64> {
    let n = data.len();
    let mut result = vec![f64::NAN; n];
    if n < period {
        return result;
    }
    let valid: Vec<f64> = data[..period].iter().filter(|x| !x.is_nan()).copied().collect();
    if valid.is_empty() {
        return result;
    }
    let sma_val: f64 = valid.iter().sum::<f64>() / valid.len() as f64;
    result[period - 1] = sma_val;
    let multiplier = 2.0 / (period as f64 + 1.0);
    for i in period..n {
        if !data[i].is_nan() && !result[i - 1].is_nan() {
            result[i] = (data[i] - result[i - 1]) * multiplier + result[i - 1];
        }
    }
    result
}

fn sma(data: &[f64], period: usize) -> Vec<f64> {
    let n = data.len();
    let mut result = vec![f64::NAN; n];
    if n < period {
        return result;
    }
    let mut sum: f64 = data[..period].iter().sum();
    result[period - 1] = sum / period as f64;
    for i in period..n {
        sum += data[i] - data[i - period];
        result[i] = sum / period as f64;
    }
    result
}
