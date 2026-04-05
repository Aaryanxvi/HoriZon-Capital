use pyo3::prelude::*;

mod features;
mod backtest;
mod signals;
mod risk;
mod orders;

/// High-performance computation core for Horizon Pro.
#[pymodule]
fn horizon_core_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Feature engine functions will be registered here as they're implemented
    Ok(())
}
