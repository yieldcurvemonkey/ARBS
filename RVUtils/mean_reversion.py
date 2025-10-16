from datetime import timedelta
from typing import Optional

import numpy as np
import pandas as pd


def simulate_mean_reversion_ou(df: pd.DataFrame, steps: Optional[int] = 252) -> pd.DataFrame:
    def count_while(steps, monte_carlo_df, mean, simulations):
        results = []
        for j in range(simulations):
            i = 0
            while (monte_carlo_df[i, j] < mean) and (i < (steps - 1)):
                i += 1
            results.append(i)
        return np.mean(results)

    def ou_monte_carlo(start_value, mean, sigma, lambda_param, simulations, steps):
        monte_carlo_df = np.zeros((steps, simulations))
        for j in range(simulations):
            sim_path = [start_value]
            for i in range(1, steps):
                w = np.random.normal()
                sim_path.append(sim_path[i - 1] * np.exp(-lambda_param) + mean * (1 - np.exp(-lambda_param)) + np.sqrt(sigma) * w)
            monte_carlo_df[:, j] = sim_path
        return monte_carlo_df

    def get_first_passage_time(start_value, mean, sigma, lambda_param):
        simulations = 150
        monte_carlo_df = ou_monte_carlo(start_value, mean, sigma, lambda_param, simulations, 100)
        return count_while(100, monte_carlo_df, mean, simulations)

    def get_mean_reversion_params(df: pd.DataFrame):
        n = len(df) - 1
        s = df.sum().iloc[0]
        sx = s - df.iloc[-1, 0]
        sy = s - df.iloc[0, 0]
        sxy = (df.iloc[:, 0] * df.iloc[:, 0].shift(1)).sum()
        syy = (df.iloc[1:, 0] ** 2).sum()
        sxx = (df.iloc[:-1, 0] ** 2).sum()

        mean = (sy * sxx - sx * sxy) / (n * (sxx - sxy) - (sx**2 - sx * sy))
        lambda_param = -np.log((sxy - mean * sx - mean * sy + n * mean**2) / (sxx - 2 * mean * sx + n * mean**2))
        alpha = np.exp(-lambda_param)
        sigma_tilde = (1 / n) * (syy - 2 * alpha * sxy + sxx * alpha**2 - 2 * mean * (1 - alpha) * (sy - alpha * sx) + n * mean**2 * (1 - alpha) ** 2)
        sigma_squared = sigma_tilde * 2 * lambda_param / (1 - alpha**2)
        return mean, lambda_param, sigma_squared

    mean, lambda_param, sigma_squared = get_mean_reversion_params(df)
    start_value = df.iloc[-1, 0]

    date_array = [df.index[-1] + timedelta(days=t) for t in range(steps)]
    expected_values = []
    upper_1_sigma, lower_1_sigma = [], []
    upper_2_sigma, lower_2_sigma = [], []

    for t in range(steps):
        if t == 0:
            value = start_value * np.exp(-lambda_param) + mean * (1 - np.exp(-lambda_param))
        else:
            value = expected_values[-1] * np.exp(-lambda_param) + mean * (1 - np.exp(-lambda_param))
        expected_values.append(value)

        drift_variance = (sigma_squared / (2 * lambda_param)) * (1 - np.exp(-2 * lambda_param * (t + 1)))
        standard_deviation = np.sqrt(drift_variance)

        upper_1_sigma.append(value + standard_deviation)
        lower_1_sigma.append(value - standard_deviation)
        upper_2_sigma.append(value + 2 * standard_deviation)
        lower_2_sigma.append(value - 2 * standard_deviation)

    forecast_df = pd.DataFrame(
        {
            "date": date_array,
            "mean_reversion": expected_values,
            "+1_sigma": upper_1_sigma,
            "-1_sigma": lower_1_sigma,
            "+2_sigma": upper_2_sigma,
            "-2_sigma": lower_2_sigma,
        }
    ).set_index("date")

    return forecast_df, get_first_passage_time(start_value, mean, sigma_squared, lambda_param)
