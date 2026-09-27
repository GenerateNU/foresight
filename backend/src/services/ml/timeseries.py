from statsmodels.tsa.statespace.sarimax import SARIMAX

from services.ml.base import Model


class TimeSeriesModel(Model):
    """SARIMAX forecaster for the daily average price series.

    Captures trend/weekly seasonality in price itself (order + seasonal_order)
    while also using same-day demand drivers (occupancy, competitor price,
    weekend/holiday/event flags, average lead time) as exogenous regressors,
    since price isn't just autocorrelated noise -- it responds to demand.
    """

    name = "sarimax"

    def __init__(self, order=(1, 1, 1), seasonal_order=(1, 1, 1, 7), **params):
        super().__init__(**params)
        self.order = order
        self.seasonal_order = seasonal_order

    def fit(self, x, y):
        """Fits the SARIMAX model on a contiguous daily series.

        Args:
            x (pd.DataFrame): Exogenous regressors, daily frequency,
                same index as y.
            y (pd.Series): Daily average price, daily frequency.

        Returns:
            TimeSeriesModel: The trained model.
        """
        self._model = SARIMAX(
            y,
            exog=x,
            order=self.order,
            seasonal_order=self.seasonal_order,
            enforce_stationarity=False,
            enforce_invertibility=False,
        ).fit(disp=False, **self.params)
        return self

    def predict(self, x):
        """Forecasts the point price for each step in x.

        Args:
            x (pd.DataFrame): Exogenous regressors for the forecast
                horizon; must immediately follow the training period.

        Returns:
            np.ndarray: One forecast per row of x.
        """
        forecast = self._fitted().get_forecast(steps=len(x), exog=x)
        return forecast.predicted_mean.to_numpy()

    def predict_interval(self, x, alpha=0.05):
        """Forecasts a value and a (1 - alpha) interval for each step in x.

        Args:
            x (pd.DataFrame): Exogenous regressors for the forecast horizon.
            alpha (float): Significance level; 0.05 gives a 95% interval.

        Returns:
            tuple[np.ndarray, np.ndarray, np.ndarray]: Forecasts, lower
                bounds, and upper bounds, one per row of x.

        Raises:
            RuntimeError: If fit has not been called yet.
        """
        forecast = self._fitted().get_forecast(steps=len(x), exog=x)
        pred = forecast.predicted_mean.to_numpy()
        ci = forecast.conf_int(alpha=alpha)
        lower, upper = ci.iloc[:, 0].to_numpy(), ci.iloc[:, 1].to_numpy()
        return pred, lower, upper
