use pyo3::prelude::*;

mod features;
mod backtest;
mod signals;
mod risk;
mod orders;

/// High-performance computation core for Horizon Pro.
#[pymodule]
fn horizon_core_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(features::compute_rsi, m)?)?;
    m.add_function(wrap_pyfunction!(features::compute_macd, m)?)?;
    m.add_function(wrap_pyfunction!(features::compute_bollinger, m)?)?;
    m.add_function(wrap_pyfunction!(features::compute_all_indicators, m)?)?;
    m.add_function(wrap_pyfunction!(backtest::run_backtest_fast, m)?)?;
    Ok(())
}
