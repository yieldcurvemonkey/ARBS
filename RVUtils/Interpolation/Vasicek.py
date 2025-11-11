# ABOUTME: Vasicek short-rate model interpolation
# ABOUTME: Interest rate curve fitting using Vasicek mean-reverting process
from typing import Tuple, Union, Any

import matplotlib.pyplot as plt
import numpy as np
import numpy.typing as npt


class Simulation:
    def __init__(self, simulated_paths: np.ndarray, dt: float) -> None:
        self._sim = self._is_valid_attr(simulated_paths)
        self._dt = dt

    @property
    def get_sim(self) -> np.ndarray:
        return self.__getattribute__("_sim")

    @property
    def get_nb_sim(self) -> int:
        return self.__getattribute__("_sim").shape[1]

    @property
    def get_steps(self) -> int:
        return self.__getattribute__("_sim").shape[0]

    @property
    def get_dt(self) -> float:
        return self.__getattribute__("_dt")

    @staticmethod
    def _is_valid_attr(attr: Any) -> np.ndarray:
        assert isinstance(attr, np.ndarray), "Class Constructor takes only numpy arrays or list as arguments"
        return attr

    def yield_curve(self) -> Tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
        discount_factor: np.ndarray = self.discount_factor()
        yield_curve = (np.mean(discount_factor, axis=1) ** (-1 / np.full(self.get_steps, self.get_dt).cumsum())) - 1
        return np.full(self.get_steps, self.get_dt).cumsum(), yield_curve

    def discount_factor(self) -> np.array:
        rieman_sum: np.ndarray = np.zeros(shape=self.get_sim.shape)
        discount_factor: np.ndarray = np.zeros(shape=self.get_sim.shape)
        for sim in range(self.get_nb_sim):
            rieman_sum[:, sim] = np.cumsum(np.multiply(self.get_sim[:, sim], self.get_dt))
            discount_factor[:, sim] = np.exp(-rieman_sum[:, sim])
        return discount_factor

    def plot_discount_curve(self, average: bool = False) -> None:
        discount_factor: np.ndarray = self.discount_factor()
        t: np.ndarray = np.full(self.get_steps, self.get_dt).cumsum()
        fig, ax = plt.subplots(1)
        fig.canvas.set_window_title("Discount Factor")
        fig.suptitle("Discount Factor")
        ax.set_xlabel("Time, t")
        ax.set_ylabel("Simulated Discount Factor")
        if average:
            ax.plot(t, np.mean(discount_factor, axis=1), c="navy")
        else:
            ax.plot(t, discount_factor)

    def plot_simulation(self) -> None:
        t: np.ndarray = np.full(self.get_steps, self.get_dt).cumsum()
        fig, ax = plt.subplots(1)
        fig.suptitle("Simulated Paths")
        fig.canvas.set_window_title("Simulated Paths")
        ax.set_xlabel("Time, t")
        ax.set_ylabel("Simulated Yield")
        ax.plot(t, self.get_sim, lw=0.5)
        plt.show()
        return fig


class Vasicek:

    def __init__(
        self,
        alpha: float,
        beta: float,
        sigma: float,
        rt: float,
        time: float,
        delta_time: float,
    ) -> None:
        self._alpha = alpha
        self._beta = beta
        self._sigma = sigma
        self._rt = rt
        self._dt = delta_time
        self._steps = int(time / delta_time)

    def get_attr(self, attr: str) -> Union[float, int]:
        return self.__getattribute__(attr)

    def _sigma_part(self, n: int) -> float:
        return self.get_attr("_sigma") * np.sqrt(self.get_attr("_dt")) * np.random.normal(size=n)

    def _mu_dt(self, rt: np.ndarray) -> float:
        return self.get_attr("_alpha") * (self.get_attr("_beta") - rt) * self.get_attr("_dt")

    def simulate_paths(self, n: int) -> np.array:
        simulation = np.zeros(shape=(self.get_attr("_steps"), n))
        simulation[0, :] = self._rt
        for i in range(1, self.get_attr("_steps"), 1):
            dr = self._mu_dt(simulation[i - 1, :]) + self._sigma_part(n)
            simulation[i, :] = simulation[i - 1, :] + dr
        return Simulation(simulation, self.get_attr("_dt"))

    @staticmethod
    def plot_calibrated(
        simul: Simulation,
        instantaneous_forward: Tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]],
    ) -> None:
        fig = plt.figure(figsize=(12.5, 8))
        fig.suptitle("Model Fitting Curve T=0")
        fig.canvas.set_window_title("Model Fitting Curve T=0")
        ax1 = fig.add_subplot(111)
        ax1.set_xlabel("t, years")
        ax1.set_ylabel("Yield")
        ax1.plot(
            np.linspace(1, simul.get_steps, simul.get_steps) * simul.get_dt,
            simul.get_sim,
            lw=0.5,
        )
        ax1.plot(
            np.linspace(1, simul.get_steps, simul.get_steps) * simul.get_dt,
            simul.yield_curve().get_rate,
            lw=3,
            c="Navy",
            label="Vasicek Term Structure",
        )
        ax1.plot(
            instantaneous_forward.get_time,
            instantaneous_forward.get_rate,
            c="darkred",
            label="Initial Term Structure",
            lw=3,
        )
        plt.legend()
        plt.show()
        return fig
